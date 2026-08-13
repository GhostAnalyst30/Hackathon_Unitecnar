from ...config import MAX_DOC_HEAD_CHARS, MAX_DOC_MID_CHARS, MAX_DOC_TAIL_CHARS
from ...domain.entities import AppSettings
from ...domain.services import VALID_KINDS, VALID_SEVERITIES
from ...infrastructure.llm import chat_completion, extract_json


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
    content = await chat_completion(
        settings,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=max_tokens,
    )
    return extract_json(content)
