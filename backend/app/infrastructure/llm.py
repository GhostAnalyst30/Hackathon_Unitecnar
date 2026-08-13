"""Adaptador LLM: clientes OpenAI-compatibles con pool, fallbacks y errores opacos.

Si el modelo principal no responde, se prueban los de respaldo configurados.
Los fallos técnicos no se exponen al usuario.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from openai import AsyncOpenAI

from ..config import LLM_MAX_TOKENS, LLM_TIMEOUT, PROVIDER_BASE_URLS
from ..domain.entities import AppSettings

logger = logging.getLogger("llm")

PUBLIC_READ_ERROR = (
    "El servidor no pudo leer los datos. Inténtalo de nuevo en un momento."
)
PUBLIC_CONFIG_ERROR = "Falta configurar el modelo o la API key en Configuración."


class LLMNotConfigured(Exception):
    pass


class LLMEmptyResponse(Exception):
    pass


def public_error_message(exc: BaseException) -> str:
    if isinstance(exc, LLMNotConfigured):
        return PUBLIC_CONFIG_ERROR
    return PUBLIC_READ_ERROR


_clients: dict[tuple[str, str], AsyncOpenAI] = {}


def parse_model_list(raw: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\s,;]+", raw or "") if part.strip()]


def _unique_models(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for model in group:
            key = model.lower()
            if key and key not in seen:
                seen.add(key)
                out.append(model)
    return out


def chat_model_chain(settings: AppSettings) -> list[str]:
    return _unique_models(
        [settings.chat_model.strip()],
        parse_model_list(getattr(settings, "chat_fallback_models", "") or ""),
    )


def ocr_model_chain(settings: AppSettings) -> list[str]:
    return _unique_models(
        [settings.ocr_model.strip()],
        parse_model_list(getattr(settings, "ocr_fallback_models", "") or ""),
    )


def resolve_chat_config(settings: AppSettings) -> tuple[str, str, str]:
    if settings.provider == "custom":
        base_url = settings.base_url.strip()
    else:
        base_url = PROVIDER_BASE_URLS.get(settings.provider, "")
    api_key = settings.api_key.strip()
    model = settings.chat_model.strip()
    if not base_url or not api_key or not model:
        raise LLMNotConfigured(PUBLIC_CONFIG_ERROR)
    return base_url, api_key, model


def resolve_ocr_config(settings: AppSettings) -> tuple[str, str, str]:
    base_url = settings.ocr_base_url.strip()
    api_key = settings.ocr_api_key.strip() or settings.api_key.strip()
    model = settings.ocr_model.strip()
    if not base_url or not api_key or not model:
        raise LLMNotConfigured(PUBLIC_CONFIG_ERROR)
    return base_url, api_key, model


def make_client(base_url: str, api_key: str) -> AsyncOpenAI:
    key = (base_url.rstrip("/"), api_key)
    client = _clients.get(key)
    if client is None:
        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=LLM_TIMEOUT,
            max_retries=1,
            default_headers={
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "GhostAnalyst",
            },
        )
        _clients[key] = client
    return client


def _message_text(message) -> str:
    if message is None:
        return ""
    content = getattr(message, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("text"):
                parts.append(block["text"])
            elif hasattr(block, "text") and block.text:
                parts.append(block.text)
        if parts:
            return "\n".join(parts)
    reasoning = getattr(message, "reasoning", None)
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    return ""


def _openrouter_extras(settings: AppSettings) -> dict:
    if settings.provider != "openrouter":
        return {}
    return {"extra_body": {"provider": {"sort": "throughput"}}}


async def _complete_once(
    client: AsyncOpenAI,
    settings: AppSettings,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> str:
    last_error = "sin contenido"
    for attempt in range(2):
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **_openrouter_extras(settings),
            )
        except Exception as exc:  # noqa: BLE001
            last_error = type(exc).__name__
            logger.warning("Modelo %s falló (%s): %s", model, last_error, exc)
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        choices = getattr(resp, "choices", None) or []
        if choices:
            text = _message_text(choices[0].message)
            if text.strip():
                return text
        last_error = "respuesta vacía"
        await asyncio.sleep(0.5 * (attempt + 1))
    raise LLMEmptyResponse(last_error)


async def chat_completion(
    settings: AppSettings,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = LLM_MAX_TOKENS,
    model: str | None = None,
) -> str:
    base_url, api_key, primary = resolve_chat_config(settings)
    client = make_client(base_url, api_key)
    chain = [model] if model else chat_model_chain(settings)
    last_exc: Exception | None = None
    for index, candidate in enumerate(chain):
        try:
            text = await _complete_once(
                client, settings, candidate, messages, temperature, max_tokens
            )
            if index:
                logger.info("Usando modelo de respaldo %s", candidate)
            return text
        except LLMNotConfigured:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("No se pudo usar %s, paso al siguiente.", candidate)
    raise LLMEmptyResponse(PUBLIC_READ_ERROR) from last_exc


async def ocr_image(settings: AppSettings, image_data_url: str, prompt: str) -> str:
    base_url, api_key, _primary = resolve_ocr_config(settings)
    client = make_client(base_url, api_key)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }
    ]
    last_exc: Exception | None = None
    for index, candidate in enumerate(ocr_model_chain(settings)):
        try:
            text = await _complete_once(
                client, settings, candidate, messages, 0, LLM_MAX_TOKENS
            )
            if index:
                logger.info("OCR usando modelo de respaldo %s", candidate)
            return text
        except LLMNotConfigured:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("OCR no pudo usar %s, paso al siguiente.", candidate)
    raise LLMEmptyResponse(PUBLIC_READ_ERROR) from last_exc


def extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON válido de la respuesta de un modelo."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        raise ValueError("respuesta no estructurada")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                return json.loads(candidate)
    raise ValueError("respuesta incompleta")
