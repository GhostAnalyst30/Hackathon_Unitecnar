"""Agente Clasificador: agrega hallazgos y aplica el puntaje del dominio.

Por defecto es determinista (sin llamada LLM): el cuello de botella era una
cuarta ronda de inferencia. Solo usa el modelo si hay instrucciones custom.
"""

import json

from ...domain.entities import AppSettings
from ...domain.services import VALID_CLASSIFICATIONS, compute_score
from .base import call_agent_json

SYSTEM = """Clasificador final. SOLO JSON compacto, sin markdown:
{"clasificacion":"aprobable|revisar|alto_riesgo","justificacion":"1-3 frases citando lo grave","recomendaciones":["acciones concretas"]}
Criterio: puntaje >= 80 aprobable, 50-79 revisar, < 50 alto_riesgo. Español."""

_KIND_LABEL = {
    "alerta": "alertas",
    "contradiccion": "contradicciones",
    "inconsistencia": "inconsistencias",
    "referencia": "problemas de referencias",
}


def _local_classification(
    score: int,
    findings: list[dict],
    reader_output: dict,
    contradictions_output: dict,
    references_output: dict,
) -> dict:
    if score >= 80:
        classification = "aprobable"
    elif score >= 50:
        classification = "revisar"
    else:
        classification = "alto_riesgo"

    parts: list[str] = [f"Puntaje de validación {score}/100."]
    resumen = str(reader_output.get("resumen") or "").strip()
    if resumen:
        parts.append(_clip(resumen, 180))
    coherencia = str(contradictions_output.get("evaluacion_general") or "").strip()
    if coherencia:
        parts.append(coherencia)
    refs = str(references_output.get("analisis") or "").strip()
    if refs:
        parts.append(refs)

    xr = references_output.get("verificacion_crossref") or {}
    if xr.get("total"):
        parts.append(
            f"Crossref: {xr.get('verificadas', 0)} verificada(s) de {xr.get('total', 0)}."
        )

    grave = [
        f
        for f in findings
        if f.get("severity") == "alta" and f.get("kind") != "importante"
    ]
    if grave:
        parts.append(f"{len(grave)} hallazgo(s) de severidad alta.")

    counts: dict[str, int] = {}
    for f in findings:
        kind = f.get("kind")
        if kind in _KIND_LABEL:
            counts[kind] = counts.get(kind, 0) + 1

    recomendaciones: list[str] = []
    if counts.get("contradiccion"):
        recomendaciones.append("Unifica las afirmaciones marcadas como contradicción.")
    if counts.get("inconsistencia"):
        recomendaciones.append("Revisa cifras, fechas y definiciones inconsistentes.")
    if counts.get("referencia") or xr.get("no_encontradas"):
        recomendaciones.append("Corrige o verifica las referencias no encontradas en Crossref.")
    if counts.get("alerta"):
        recomendaciones.append("Atiende las alertas resaltadas antes de validar.")
    if not recomendaciones:
        recomendaciones.append("Revisión humana de los fragmentos resaltados.")

    return {
        "clasificacion": classification,
        "justificacion": " ".join(p for p in parts if p),
        "recomendaciones": recomendaciones,
        "puntaje": score,
        "modo": "local",
    }


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


async def run_classifier(
    settings: AppSettings,
    reader_output: dict,
    contradictions_output: dict,
    references_output: dict,
    findings: list[dict],
) -> tuple[dict, int]:
    score = compute_score(findings)
    if not (settings.classifier_instructions or "").strip():
        return _local_classification(
            score, findings, reader_output, contradictions_output, references_output
        ), score

    summary = {
        "puntaje_validacion": score,
        "resumen_documento": reader_output.get("resumen", ""),
        "evaluacion_coherencia": contradictions_output.get("evaluacion_general", ""),
        "evaluacion_referencias": references_output.get("analisis", ""),
        "verificacion_crossref": references_output.get("verificacion_crossref", {}),
        "hallazgos": [
            {
                "agente": f["agent"],
                "tipo": f["kind"],
                "severidad": f["severity"],
                "explicacion": f["explanation"],
            }
            for f in findings
        ],
    }
    result = await call_agent_json(
        settings,
        SYSTEM,
        json.dumps(summary, ensure_ascii=False),
        settings.classifier_instructions,
        max_tokens=500,
    )
    classification = str(result.get("clasificacion", "revisar")).strip().lower()
    if classification not in VALID_CLASSIFICATIONS:
        classification = "revisar"
    result["clasificacion"] = classification
    result["puntaje"] = score
    result["modo"] = "llm"
    return result, score
