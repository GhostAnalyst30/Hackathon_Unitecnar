"""Agente conversacional: responde sobre el documento y propone sugerencias
de edición estructuradas que el usuario aplica con un clic (human-in-the-loop).
"""

import asyncio
import json

from ...config import LLM_CHAIN_ROUNDS
from ...domain.entities import AppSettings, ChatMessage, Document
from ...infrastructure.llm import (
    LLMEmptyResponse,
    LLMNotConfigured,
    LLMQuotaExceeded,
    PUBLIC_READ_ERROR,
    chat_completion,
    chat_model_chain,
    describe_llm_error,
    extract_json,
    is_free_model,
    notify_model_retry,
    retry_target_label,
)
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

    chain = chat_model_chain(settings)
    last_raw = ""
    last_exc: Exception | None = None
    rounds = max(1, LLM_CHAIN_ROUNDS)
    skip_free = False
    for round_i in range(rounds):
        if round_i:
            if skip_free and all(is_free_model(m) for m in chain):
                break
            await asyncio.sleep(3.0)
        for index, model in enumerate(chain):
            if skip_free and is_free_model(model):
                continue
            try:
                raw = await chat_completion(
                    settings,
                    messages,
                    temperature=0.4,
                    model=model,
                    chain_rounds=1,
                )
                last_raw = raw
                try:
                    parsed = extract_json(raw)
                except (ValueError, json.JSONDecodeError) as exc:
                    last_exc = exc
                    label = retry_target_label(chain, index, round_i, rounds)
                    if label:
                        notify_model_retry(model, label, "JSON inválido")
                    continue
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
            except LLMNotConfigured:
                raise
            except LLMQuotaExceeded as exc:
                last_exc = exc
                skip_free = True
                paid = next((m for m in chain[index + 1 :] if not is_free_model(m)), None)
                if paid:
                    notify_model_retry(model, paid, describe_llm_error(exc))
                    continue
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                label = retry_target_label(chain, index, round_i, rounds)
                if label:
                    notify_model_retry(model, label, describe_llm_error(exc))
    if last_raw.strip():
        return last_raw.strip(), []
    if isinstance(last_exc, LLMQuotaExceeded):
        raise last_exc
    raise LLMEmptyResponse(PUBLIC_READ_ERROR) from last_exc
