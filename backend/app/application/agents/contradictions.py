"""Agente de Contradicciones: contradicciones internas e inconsistencias."""

import json

from ...domain.entities import AppSettings
from .base import call_agent_json, normalize_finding, truncate_doc

SYSTEM = """Detector de contradicciones en papers. SOLO JSON compacto, sin markdown:
{"evaluacion_general":"1-2 frases","hallazgos":[{"cita":"copia literal 8-25 palabras","cita_secundaria":"fragmento que contradice","tipo":"contradiccion|inconsistencia","severidad":"baja|media|alta","explicacion":"el conflicto"}]}
Hasta 8 hallazgos. Incluye SIEMPRE cita_secundaria. Citas EXACTAS. Si es coherente, hallazgos=[]. Español."""


async def run_contradictions(
    settings: AppSettings, text: str, reader_output: dict | None = None
) -> tuple[dict, list[dict]]:
    reader_output = reader_output or {}
    context = json.dumps(
        {
            "resumen": reader_output.get("resumen", ""),
            "tema_principal": reader_output.get("tema_principal", ""),
        },
        ensure_ascii=False,
    )
    extra = f"Contexto (opcional): {context}\n\n" if reader_output.get("resumen") else ""
    result = await call_agent_json(
        settings,
        SYSTEM,
        f"{extra}Documento a analizar:\n\n{truncate_doc(text)}",
        settings.contradictions_instructions,
        max_tokens=1200,
    )
    findings = []
    for raw in result.get("hallazgos", []) or []:
        f = normalize_finding(raw, agent="contradictions", default_kind="contradiccion")
        if f:
            findings.append(f)
    return result, findings
