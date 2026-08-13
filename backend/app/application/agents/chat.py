"""Agente conversacional: responde sobre el documento y propone sugerencias
de edición estructuradas que el usuario aplica con un clic (human-in-the-loop).
"""

import json

from ...domain.entities import AppSettings, ChatMessage, Document
from ...infrastructure.llm import chat_completion, extract_json
from .base import truncate_doc

SYSTEM = """Eres el asistente de edición de un analizador personal de papers académicos.
Conoces el documento completo y los hallazgos de los agentes de análisis
(información importante, alertas, contradicciones, referencias).

Ayudas al usuario a entender y mejorar su documento. Cuando el usuario pida
correcciones o detectes una mejora concreta, propón sugerencias de edición.

Responde ÚNICAMENTE con un JSON válido con esta forma exacta:
{
  "respuesta": "tu respuesta conversacional en español, clara y útil",
  "sugerencias": [
    {
      "original": "fragmento TEXTUAL EXACTO del documento a reemplazar (cópialo literal)",
      "sugerido": "texto propuesto que lo reemplaza",
      "motivo": "por qué se propone este cambio"
    }
  ]
}

Reglas:
- "original" debe ser una copia literal de un fragmento del documento actual,
  de lo contrario la sugerencia no podrá aplicarse.
- Si no hay cambios que proponer, devuelve "sugerencias": [].
- Nunca apliques cambios tú mismo: el usuario siempre decide."""


def _findings_summary(document: Document) -> str:
    items = [
        {
            "agente": f.agent,
            "tipo": f.kind,
            "severidad": f.severity,
            "cita": f.quote[:200],
            "explicacion": f.explanation,
        }
        for f in document.findings
    ]
    return json.dumps(items, ensure_ascii=False)


async def run_chat(
    settings: AppSettings,
    document: Document,
    history: list[ChatMessage],
    user_message: str,
) -> tuple[str, list[dict]]:
    system = SYSTEM
    if (settings.chat_instructions or "").strip():
        system += (
            "\n\nInstrucciones adicionales del usuario (respétalas siempre):\n"
            + settings.chat_instructions.strip()
        )

    context = (
        f"DOCUMENTO ACTUAL ({document.filename}):\n{truncate_doc(document.content_text)}\n\n"
        f"PUNTAJE DE VALIDACIÓN: {document.score}\n"
        f"CLASIFICACIÓN: {document.classification}\n"
        f"HALLAZGOS DE LOS AGENTES: {_findings_summary(document)}"
    )

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Contexto (no es un mensaje del usuario):\n{context}"},
        {
            "role": "assistant",
            "content": '{"respuesta": "Contexto recibido. Estoy listo para ayudarte con tu documento.", "sugerencias": []}',
        },
    ]
    for msg in history[-12:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})

    raw = await chat_completion(settings, messages, temperature=0.4)
    try:
        parsed = extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        return raw.strip(), []

    reply = str(parsed.get("respuesta", "")).strip() or raw.strip()
    suggestions = []
    for s in parsed.get("sugerencias", []) or []:
        original = str(s.get("original", "")).strip()
        suggested = str(s.get("sugerido", "")).strip()
        if original and suggested:
            suggestions.append(
                {
                    "original": original,
                    "suggested": suggested,
                    "reason": str(s.get("motivo", "")).strip(),
                }
            )
    return reply, suggestions
