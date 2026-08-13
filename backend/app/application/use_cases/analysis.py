"""Caso de uso de análisis: pipeline LangGraph con arquitectura mixta.

    ingesta -> (lector ∥ contradicciones ∥ referencias) -> clasificador

- La ingesta extrae el texto; los tres agentes LLM corren EN PARALELO.
- Referencias además verifica las fuentes contra la Crossref REST API.
- El clasificador espera a los tres (join), agrega hallazgos y aplica el puntaje
  del dominio (por defecto sin LLM extra).
- Al terminar, el documento queda en `awaiting_review`: el humano decide.

Varios documentos se procesan concurrentemente con un semáforo asyncio.
"""

import asyncio
import json
import logging
import re
import traceback
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from ...config import MAX_CONCURRENT_ANALYSES
from ...domain.entities import AgentOutput, Document, Finding, ProcessLog
from ...domain.services import anchor_findings
from ...infrastructure.db import SessionLocal
from ...infrastructure.events import publish_document_event
from ...infrastructure.ingest import ingest_file
from ...infrastructure.llm import chat_model_chain, public_error_message, retry_hook
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


def _log(document_id: str, agent: str, message: str) -> None:
    with SessionLocal() as session:
        row = ProcessLog(document_id=document_id, agent=agent, message=message)
        session.add(row)
        session.commit()
        log_id = row.id
        created = row.created_at
    publish_document_event(
        document_id,
        "agent_log",
        agent=agent,
        message=message,
        log_id=log_id,
        created_at=created,
    )


def _clear_logs(document_id: str) -> None:
    with SessionLocal() as session:
        doc = session.get(Document, document_id)
        if doc is None:
            return
        for old in list(doc.process_logs):
            session.delete(old)
        session.commit()


def _clip(text: str, n: int = 180) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _chain_note(settings) -> str:
    n = len(chat_model_chain(settings))
    if n <= 1:
        return " Si no responde, reintento el mismo modelo varias veces."
    return (
        f" Si no responde, recorro {n - 1} respaldo(s) configurado(s) "
        "antes de marcar error."
    )


def _bind_retry_log(document_id: str, agent: str):
    def _notify(failed: str, nxt: str, reason: str) -> None:
        _log(
            document_id,
            agent,
            f"{failed} no respondió ({reason}); reintento con {nxt}…",
        )

    return retry_hook.set(_notify)


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
        _set_status(document_id, "analyzing")
        _log(
            document_id,
            "ingest",
            "Re-análisis: reutilizo el texto ya editado y salto la extracción. "
            "Arranco los tres agentes en paralelo."
            + _chain_note(settings),
        )
        return {"text": existing_text}

    _set_status(document_id, "extracting")
    _log(
        document_id,
        "ingest",
        "Extrayendo la estructura del documento (títulos, párrafos, listas, páginas)…"
        + _chain_note(settings),
    )
    token = _bind_retry_log(document_id, "ingest")
    try:
        html, text, ocr_used = await ingest_file(file_path, file_format, settings)
    finally:
        retry_hook.reset(token)

    with SessionLocal() as session:
        doc = session.get(Document, document_id)
        doc.content_html = html
        doc.content_text = text
        doc.ocr_used = ocr_used
        session.commit()

    pages = html.count("— Página ")
    ocr_note = " Se usó OCR en páginas escaneadas." if ocr_used else ""
    _set_status(document_id, "analyzing")
    _log(
        document_id,
        "ingest",
        f"Estructura lista ({pages or 1} página(s), {len(text):,} caracteres).{ocr_note} "
        "Arranco lector, contradicciones y referencias en paralelo."
        + _chain_note(settings),
    )
    return {"text": text}


async def _node_reader(state: PipelineState) -> dict:
    document_id = state["document_id"]
    with SessionLocal() as session:
        settings = get_settings(session)
    _log(
        document_id,
        "reader",
        "Leyendo el documento: identifico estructura, resumen e información clave…"
        + _chain_note(settings),
    )
    token = _bind_retry_log(document_id, "reader")
    try:
        output, findings = await run_reader(settings, state["text"])
    finally:
        retry_hook.reset(token)
    _save_agent_output(document_id, "reader", output)
    resumen = _clip(str(output.get("resumen", "")), 160)
    _log(
        document_id,
        "reader",
        f"Lectura lista. {len(findings)} fragmento(s) importante(s). {resumen}",
    )
    return {"reader_output": output, "reader_findings": findings}


async def _node_contradictions(state: PipelineState) -> dict:
    document_id = state["document_id"]
    with SessionLocal() as session:
        settings = get_settings(session)
    _log(
        document_id,
        "contradictions",
        "Comparando afirmaciones entre secciones para detectar contradicciones e inconsistencias…"
        + _chain_note(settings),
    )
    token = _bind_retry_log(document_id, "contradictions")
    try:
        output, findings = await run_contradictions(
            settings, state["text"], state.get("reader_output")
        )
    finally:
        retry_hook.reset(token)
    _save_agent_output(document_id, "contradictions", output)
    eval_txt = _clip(str(output.get("evaluacion_general", "")), 140)
    _log(
        document_id,
        "contradictions",
        f"Encontré {len(findings)} contradicción(es)/inconsistencia(s). {eval_txt}",
    )
    return {"contradictions_output": output, "contradictions_findings": findings}


async def _node_references(state: PipelineState) -> dict:
    document_id = state["document_id"]
    with SessionLocal() as session:
        settings = get_settings(session)
    _log(
        document_id,
        "references",
        "Extrayendo la bibliografía y verificando cada fuente en Crossref…"
        + _chain_note(settings),
    )
    token = _bind_retry_log(document_id, "references")
    try:
        output, findings = await run_references(
            settings, state["text"], state.get("reader_output")
        )
    finally:
        retry_hook.reset(token)
    _save_agent_output(document_id, "references", output)
    xr = output.get("verificacion_crossref") or {}
    _log(
        document_id,
        "references",
        "Crossref: "
        f"{xr.get('verificadas', 0)} verificada(s), "
        f"{xr.get('no_encontradas', 0)} no indexada(s) de {xr.get('total', 0)} "
        "(las no indexadas no restan puntaje). "
        f"{len(findings)} marca(s) en bibliografía.",
    )
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
    local = not (settings.classifier_instructions or "").strip()
    _log(
        document_id,
        "classifier",
        "Agregando hallazgos de los tres agentes y calculando el puntaje"
        + (
            " (sin llamada extra al modelo)…"
            if local
            else "…" + _chain_note(settings)
        ),
    )
    token = _bind_retry_log(document_id, "classifier")
    try:
        output, score = await run_classifier(
            settings,
            state.get("reader_output", {}),
            state.get("contradictions_output", {}),
            state.get("references_output", {}),
            all_findings,
        )
    finally:
        retry_hook.reset(token)
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
    _log(
        document_id,
        "classifier",
        f"Clasificación: {output['clasificacion']}. Puntaje {score}/100. "
        f"{_clip(str(output.get('justificacion', '')), 160)} "
        "Esperando tu decisión.",
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
    # Fan-out: los tres agentes LLM a la vez
    graph.add_edge("ingest", "reader")
    graph.add_edge("ingest", "contradictions")
    graph.add_edge("ingest", "references")
    # Join: el clasificador espera a los tres
    graph.add_edge(["reader", "contradictions", "references"], "classifier")
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
            _clear_logs(document_id)
            _log(document_id, "ingest", "Documento en cola. Inicio el pipeline de agentes.")
            with SessionLocal() as session:
                model = get_settings(session).chat_model
            if any(token in model.lower() for token in ("550b", "ultra-550", "nemotron-3-ultra")):
                _log(
                    document_id,
                    "ingest",
                    "El modelo actual es enorme y suele tardar o devolver vacío en el cupo "
                    "gratis. En Configuración elige «Gratis · rápido · Gemma 4 26B».",
                )
            await get_graph().ainvoke(
                {"document_id": document_id, "skip_ingest": skip_ingest}
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Pipeline falló para %s:\n%s", document_id, traceback.format_exc())
            friendly = public_error_message(exc)
            _log(document_id, "ingest", friendly)
            _set_status(document_id, "error", error=friendly)


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
