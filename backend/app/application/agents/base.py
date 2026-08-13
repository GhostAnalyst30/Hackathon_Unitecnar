import asyncio

from ...config import LLM_CHAIN_ROUNDS, MAX_DOC_HEAD_CHARS, MAX_DOC_MID_CHARS, MAX_DOC_TAIL_CHARS
from ...domain.entities import AppSettings
from ...domain.services import VALID_KINDS, VALID_SEVERITIES
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


def truncate_doc(text: str) -> str:
    """Envía inicio, un fragmento central y el final (para citar más secciones)."""
    budget = MAX_DOC_HEAD_CHARS + MAX_DOC_MID_CHARS + MAX_DOC_TAIL_CHARS
    if len(text) <= budget:
        return text
    head = text[:MAX_DOC_HEAD_CHARS]
    tail = text[-MAX_DOC_TAIL_CHARS:]
    mid_start = max(MAX_DOC_HEAD_CHARS, (len(text) - MAX_DOC_MID_CHARS) // 2)
    mid = text[mid_start : mid_start + MAX_DOC_MID_CHARS]
    return (
        f"{head}\n\n[... fragmento central ...]\n\n{mid}\n\n"
        f"[... salto a conclusiones / referencias ...]\n\n{tail}"
    )


def bibliography_slice(text: str) -> str:
    """Para el agente de referencias: tema breve + bloque de bibliografía."""
    lower = text.lower()
    markers = (
        "\nreferences\n",
        "\nreferencias\n",
        "\nbibliography\n",
        "\nbibliografía\n",
        "\nbibliografia\n",
        "\nworks cited\n",
    )
    idx = -1
    for marker in markers:
        found = lower.rfind(marker)
        if found > idx:
            idx = found
    head = text[:2200]
    if idx != -1:
        return f"{head}\n\n--- BIBLIOGRAFÍA ---\n{text[idx:idx + 9000]}"
    return truncate_doc(text)


def normalize_finding(raw: dict, agent: str, default_kind: str) -> dict | None:
    quote = str(raw.get("cita") or raw.get("quote") or "").strip()
    explanation = str(raw.get("explicacion") or raw.get("explanation") or "").strip()
    if not quote and not explanation:
        return None
    kind = str(raw.get("tipo") or raw.get("kind") or default_kind).strip().lower()
    if kind not in VALID_KINDS:
        kind = default_kind
    severity = str(raw.get("severidad") or raw.get("severity") or "media").strip().lower()
    if severity not in VALID_SEVERITIES:
        severity = "media"
    quote_secondary = str(raw.get("cita_secundaria") or raw.get("quote_secondary") or "").strip()
    return {
        "agent": agent,
        "kind": kind,
        "severity": severity,
        "quote": quote,
        "quote_secondary": quote_secondary or None,
        "explanation": explanation,
    }


async def call_agent_json(
    settings: AppSettings,
    system_prompt: str,
    user_prompt: str,
    custom_instructions: str = "",
    max_tokens: int = 1100,
) -> dict:
    system = system_prompt
    if custom_instructions.strip():
        system += (
            "\n\nInstrucciones adicionales del usuario (respétalas siempre):\n"
            + custom_instructions.strip()
        )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]
    chain = chat_model_chain(settings)
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
                content = await chat_completion(
                    settings,
                    messages,
                    max_tokens=max_tokens,
                    model=model,
                    chain_rounds=1,
                )
                return extract_json(content)
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
    if isinstance(last_exc, LLMQuotaExceeded):
        raise last_exc
    raise LLMEmptyResponse(PUBLIC_READ_ERROR) from last_exc
