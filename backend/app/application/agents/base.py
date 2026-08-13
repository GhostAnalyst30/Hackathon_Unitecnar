from ...config import MAX_DOC_CHARS
from ...domain.entities import AppSettings
from ...domain.services import VALID_KINDS, VALID_SEVERITIES
from ...infrastructure.llm import chat_completion, extract_json


def truncate_doc(text: str) -> str:
    if len(text) <= MAX_DOC_CHARS:
        return text
    return (
        text[:MAX_DOC_CHARS]
        + "\n\n[... documento truncado por longitud; analiza lo disponible ...]"
    )


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
) -> dict:
    system = system_prompt
    if custom_instructions.strip():
        system += (
            "\n\nInstrucciones adicionales del usuario (respétalas siempre):\n"
            + custom_instructions.strip()
        )
    content = await chat_completion(
        settings,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
    )
    return extract_json(content)
