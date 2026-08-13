"""Agente de Referencias: extrae bibliografía, evalúa su relevancia y
VERIFICA cada fuente contra la Crossref REST API (existencia real, DOI, año).
"""

import json

from ...domain.entities import AppSettings
from ...infrastructure.crossref import verify_references
from .base import call_agent_json, normalize_finding, truncate_doc

SYSTEM = """Eres un agente revisor de referencias bibliográficas de papers académicos.
Tu tarea:
1. Extraer las referencias bibliográficas del documento (texto completo de cada una).
2. Evaluar la relevancia de cada una respecto al tema del documento.
3. Detectar problemas: citas en el texto sin referencia, referencias no citadas,
   referencias visiblemente desactualizadas o irrelevantes, formato inconsistente.

Responde ÚNICAMENTE con un JSON válido con esta forma exacta:
{
  "analisis": "evaluación general de la calidad de la bibliografía",
  "referencias": [
    {
      "referencia": "texto completo de la referencia tal como aparece en el documento",
      "relevancia": "alta|media|baja",
      "comentario": "por qué es o no relevante para el tema"
    }
  ],
  "hallazgos": [
    {
      "cita": "fragmento TEXTUAL EXACTO del documento con el problema (máximo 40 palabras)",
      "tipo": "referencia|alerta",
      "severidad": "baja|media|alta",
      "explicacion": "descripción del problema con esta referencia o cita"
    }
  ]
}

Reglas: las citas de "hallazgos" deben ser copias literales del documento.
Si el documento no tiene bibliografía, repórtalo como un hallazgo tipo "alerta"
con severidad "alta" usando como cita el título o primera línea del documento.
Responde en español."""


async def run_references(
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
        settings.references_instructions,
    )

    findings = []
    for raw in result.get("hallazgos", []) or []:
        f = normalize_finding(raw, agent="references", default_kind="referencia")
        if f:
            findings.append(f)

    # Verificación de fuentes contra Crossref
    references = result.get("referencias", []) or []
    ref_texts = [str(r.get("referencia", "")).strip() for r in references]
    verifications = await verify_references([t for t in ref_texts if t])

    verified_count = 0
    unverified_count = 0
    v_iter = iter(verifications)
    for ref in references:
        if not str(ref.get("referencia", "")).strip():
            continue
        verification = next(v_iter, {})
        ref.update(verification)
        if verification.get("verificada") is True:
            verified_count += 1
        elif verification.get("verificada") is False:
            unverified_count += 1
            findings.append(
                {
                    "agent": "references",
                    "kind": "referencia",
                    "severity": "media",
                    "quote": str(ref.get("referencia", ""))[:300],
                    "quote_secondary": None,
                    "explanation": (
                        "No se encontró esta fuente en Crossref: puede ser inexistente, "
                        "estar mal citada o no estar indexada. Verifícala manualmente."
                    ),
                }
            )

    result["verificacion_crossref"] = {
        "total": len([t for t in ref_texts if t]),
        "verificadas": verified_count,
        "no_encontradas": unverified_count,
    }
    return result, findings
