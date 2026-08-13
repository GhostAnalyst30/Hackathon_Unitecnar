"""Caso de uso de análisis: pipeline LangGraph con arquitectura mixta.

    ingesta -> lector -> (contradicciones ∥ referencias) -> clasificador

- Ingesta y lector son secuenciales (dependencia de datos).
- Contradicciones y referencias corren EN PARALELO (fan-out del grafo);
  referencias además verifica las fuentes contra la Crossref REST API.
- El clasificador espera a ambos (join), agrega hallazgos y aplica el puntaje
  del dominio.
- Al terminar, el documento queda en `awaiting_review`: el humano decide.

Varios documentos se procesan concurrentemente con un semáforo asyncio.
"""

import asyncio
import json
import logging
import traceback
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from ...config import MAX_CONCURRENT_ANALYSES
from ...domain.entities import AgentOutput, Document, Finding
from ...domain.services import anchor_findings
from ...infrastructure.db import SessionLocal
from ...infrastructure.events import publish_document_event
from ...infrastructure.ingest import ingest_file
from ..agents.classifier import run_classifier
from ..agents.contradictions import run_contradictions
from ..agents.reader import run_reader
from ..agents.references import run_references
from .settings import get_settings

logger = logging.getLogger("analysis")

_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)
_tasks: set[asyncio.Task] = set()


class PipelineState(TypedDict, total=False):
    document_id: str
    skip_ingest: bool
    text: str
    reader_output: dict
    reader_findings: list
    contradictions_output: dict
    contradictions_findings: list
    references_output: dict
    references_findings: list


def _set_status(document_id: str, status: str, **fields) -> None:
    with SessionLocal() as session:
        doc = session.get(Document, document_id)
        if doc is None:
            return
        doc.status = status
        for key, value in fields.items():
            setattr(doc, key, value)
        session.commit()
    publish_document_event(
        document_id, status, **{k: v for k, v in fields.items() if k != "content_html"}
    )


def _save_agent_output(document_id: str, agent: str, output: dict) -> None:
    with SessionLocal() as session:
        session.add(
            AgentOutput(
                document_id=document_id,
                agent=agent,
                output_json=json.dumps(output, ensure_ascii=False),
            )
        )
        session.commit()
    publish_document_event(document_id, "agent_done", agent=agent)


async def _node_ingest(state: PipelineState) -> dict:
    document_id = state["document_id"]
    with SessionLocal() as session:
        doc = session.get(Document, document_id)
        settings = get_settings(session)
        file_path = Path(doc.file_path)
        file_format = doc.file_format
        existing_text = doc.content_text

    if state.get("skip_ingest") and existing_text.strip():
        return {"text": existing_text}

    _set_status(document_id, "extracting")
    html, text, ocr_used = await ingest_file(file_path, file_format, settings)

    with SessionLocal() as session:
        doc = session.get(Document, document_id)
        doc.content_html = html
        doc.content_text = text
        doc.ocr_used = ocr_used
        session.commit()
    return {"text": text}


async def _node_reader(state: PipelineState) -> dict:
    document_id = state["document_id"]
    _set_status(document_id, "analyzing")
    with SessionLocal() as session:
        settings = get_settings(session)
    output, findings = await run_reader(settings, state["text"])
    _save_agent_output(document_id, "reader", output)
    return {"reader_output": output, "reader_findings": findings}


async def _node_contradictions(state: PipelineState) -> dict:
    document_id = state["document_id"]
    with SessionLocal() as session:
        settings = get_settings(session)
    output, findings = await run_contradictions(settings, state["text"], state["reader_output"])
    _save_agent_output(document_id, "contradictions", output)
    return {"contradictions_output": output, "contradictions_findings": findings}


async def _node_references(state: PipelineState) -> dict:
    document_id = state["document_id"]
    with SessionLocal() as session:
        settings = get_settings(session)
    output, findings = await run_references(settings, state["text"], state["reader_output"])
    _save_agent_output(document_id, "references", output)
    return {"references_output": output, "references_findings": findings}


async def _node_classifier(state: PipelineState) -> dict:
    document_id = state["document_id"]
    all_findings = (
        state.get("reader_findings", [])
        + state.get("contradictions_findings", [])
        + state.get("references_findings", [])
    )
    with SessionLocal() as session:
        settings = get_settings(session)
    output, score = await run_classifier(
        settings,
        state.get("reader_output", {}),
        state.get("contradictions_output", {}),
        state.get("references_output", {}),
        all_findings,
    )
    _save_agent_output(document_id, "classifier", output)

    # Persistir hallazgos (reemplaza los del análisis anterior) y anclarlos al texto
    with SessionLocal() as session:
        doc = session.get(Document, document_id)
        for old in list(doc.findings):
            session.delete(old)
        session.flush()
        finding_rows = [
            Finding(
                document_id=document_id,
                agent=f["agent"],
                kind=f["kind"],
                severity=f["severity"],
                quote=f["quote"],
                quote_secondary=f.get("quote_secondary"),
                explanation=f["explanation"],
            )
            for f in all_findings
        ]
        anchor_findings(doc.content_text, finding_rows)
        session.add_all(finding_rows)
        doc.score = score
        doc.classification = output["clasificacion"]
        doc.status = "awaiting_review"
        doc.error = None
        session.commit()

    publish_document_event(
        document_id,
        "awaiting_review",
        score=score,
        classification=output["clasificacion"],
    )
    return {}


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("ingest", _node_ingest)
    graph.add_node("reader", _node_reader)
    graph.add_node("contradictions", _node_contradictions)
    graph.add_node("references", _node_references)
    graph.add_node("classifier", _node_classifier)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "reader")
    # Fan-out paralelo
    graph.add_edge("reader", "contradictions")
    graph.add_edge("reader", "references")
    # Join: el clasificador espera a ambos
    graph.add_edge(["contradictions", "references"], "classifier")
    graph.add_edge("classifier", END)
    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def _run_pipeline(document_id: str, skip_ingest: bool) -> None:
    async with _semaphore:
        try:
            await get_graph().ainvoke(
                {"document_id": document_id, "skip_ingest": skip_ingest}
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Pipeline falló para %s:\n%s", document_id, traceback.format_exc())
            _set_status(document_id, "error", error=str(exc))


def enqueue_analysis(document_id: str, skip_ingest: bool = False) -> None:
    task = asyncio.create_task(_run_pipeline(document_id, skip_ingest))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def recover_interrupted_documents() -> None:
    """Al arrancar, marca como error los análisis que quedaron a medias
    (p. ej. por un reinicio del servidor) para que puedan re-analizarse."""
    from sqlalchemy import select

    with SessionLocal() as session:
        stuck = session.scalars(
            select(Document).where(Document.status.in_(["queued", "extracting", "analyzing"]))
        ).all()
        for doc in stuck:
            doc.status = "error"
            doc.error = "El análisis se interrumpió (reinicio del servidor). Usa «Re-analizar»."
        if stuck:
            session.commit()
            logger.info("Recuperados %d documentos con análisis interrumpido", len(stuck))
