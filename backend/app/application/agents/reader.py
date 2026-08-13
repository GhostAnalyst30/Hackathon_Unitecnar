"""Agente Lector: estructura del paper, resumen e información importante."""

from ...domain.entities import AppSettings
from .base import call_agent_json, normalize_finding, truncate_doc

SYSTEM = """Eres un agente lector experto en análisis de papers académicos.
Tu tarea: leer el documento y devolver un análisis estructurado.

Responde ÚNICAMENTE con un JSON válido con esta forma exacta:
{
  "resumen": "resumen claro del documento en 4-8 frases",
  "estructura": ["lista de secciones o partes detectadas"],
  "tema_principal": "tema central del documento",
  "hallazgos": [
    {
      "cita": "fragmento TEXTUAL EXACTO copiado del documento (sin parafrasear, máximo 40 palabras)",
      "tipo": "importante",
      "severidad": "baja|media|alta",
      "explicacion": "por qué este fragmento es información clave"
    }
  ]
}

Reglas para "cita": debe ser una copia literal, carácter por carácter, de un
fragmento del documento, para poder resaltarlo. Incluye entre 4 y 10 hallazgos
con la información más relevante (objetivos, métodos, resultados, conclusiones,
datos numéricos clave). Responde en español."""


async def run_reader(settings: AppSettings, text: str) -> tuple[dict, list[dict]]:
    result = await call_agent_json(
        settings,
        SYSTEM,
        f"Documento a analizar:\n\n{truncate_doc(text)}",
        settings.reader_instructions,
    )
    findings = []
    for raw in result.get("hallazgos", []) or []:
        f = normalize_finding(raw, agent="reader", default_kind="importante")
        if f:
            findings.append(f)
    return result, findings
