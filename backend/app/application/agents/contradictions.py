"""Agente de Contradicciones: contradicciones internas e inconsistencias."""

import json

from ...domain.entities import AppSettings
from .base import call_agent_json, normalize_finding, truncate_doc

SYSTEM = """Eres un agente detector de contradicciones e inconsistencias en papers académicos.
Tu tarea: comparar afirmaciones dentro del documento y encontrar:
- Contradicciones directas (afirmaciones que se niegan mutuamente)
- Inconsistencias (datos, cifras o métodos que no cuadran entre secciones)
- Afirmaciones sin sustento que contradicen los datos presentados

Responde ÚNICAMENTE con un JSON válido con esta forma exacta:
{
  "evaluacion_general": "evaluación breve de la coherencia interna del documento",
  "hallazgos": [
    {
      "cita": "fragmento TEXTUAL EXACTO del documento donde está el problema (máximo 40 palabras)",
      "cita_secundaria": "fragmento TEXTUAL EXACTO que contradice al primero, si aplica",
      "tipo": "contradiccion|inconsistencia",
      "severidad": "baja|media|alta",
      "explicacion": "descripción clara del conflicto entre ambos fragmentos"
    }
  ]
}

Reglas: las citas deben ser copias literales del documento para poder resaltarlas.
Si el documento es coherente, devuelve "hallazgos": []. No inventes problemas.
Responde en español."""


async def run_contradictions(
    settings: AppSettings, text: str, reader_output: dict
) -> tuple[dict, list[dict]]:
    context = json.dumps(
        {
            "resumen": reader_output.get("resumen", ""),
            "tema_principal": reader_output.get("tema_principal", ""),
        },
        ensure_ascii=False,
    )
    result = await call_agent_json(
        settings,
        SYSTEM,
        f"Contexto del agente lector: {context}\n\nDocumento a analizar:\n\n{truncate_doc(text)}",
        settings.contradictions_instructions,
    )
    findings = []
    for raw in result.get("hallazgos", []) or []:
        f = normalize_finding(raw, agent="contradictions", default_kind="contradiccion")
        if f:
            findings.append(f)
    return result, findings
