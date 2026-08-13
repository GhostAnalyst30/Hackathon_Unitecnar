"""Agente Clasificador: agrega hallazgos, aplica el puntaje de validación
del dominio y clasifica el documento.
"""

import json

from ...domain.entities import AppSettings
from ...domain.services import VALID_CLASSIFICATIONS, compute_score
from .base import call_agent_json

SYSTEM = """Eres el agente clasificador final de un pipeline de revisión de papers.
Recibes el resumen del documento y todos los hallazgos de los agentes anteriores
(lector, contradicciones, referencias — incluida la verificación de fuentes en
Crossref), junto con un puntaje de validación de 0 a 100 calculado a partir de
la severidad de las alertas.

Tu tarea: clasificar el documento y justificar la decisión para que un humano
decida si lo valida o lo descarta.

Responde ÚNICAMENTE con un JSON válido con esta forma exacta:
{
  "clasificacion": "aprobable|revisar|alto_riesgo",
  "justificacion": "explicación clara de la clasificación citando los hallazgos más graves",
  "recomendaciones": ["lista de acciones concretas para mejorar el documento"]
}

Criterio orientativo: puntaje >= 80 suele ser "aprobable", 50-79 "revisar",
< 50 "alto_riesgo"; ajusta si la naturaleza de los hallazgos lo amerita.
Responde en español."""


async def run_classifier(
    settings: AppSettings,
    reader_output: dict,
    contradictions_output: dict,
    references_output: dict,
    findings: list[dict],
) -> tuple[dict, int]:
    score = compute_score(findings)
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
        json.dumps(summary, ensure_ascii=False, indent=2),
        settings.classifier_instructions,
    )
    classification = str(result.get("clasificacion", "revisar")).strip().lower()
    if classification not in VALID_CLASSIFICATIONS:
        classification = "revisar"
    result["clasificacion"] = classification
    result["puntaje"] = score
    return result, score
