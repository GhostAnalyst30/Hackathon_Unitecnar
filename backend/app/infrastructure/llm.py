"""Adaptador LLM: clientes OpenAI-compatibles con pool y respuestas cortas.

Reutiliza el cliente HTTP, limita tokens y reintenta si el proveedor gratuito
devuelve `choices` vacío (típico en OpenRouter :free saturado).
"""

from __future__ import annotations

import asyncio
import json
import re

from openai import AsyncOpenAI

from ..config import LLM_MAX_TOKENS, LLM_TIMEOUT, PROVIDER_BASE_URLS
from ..domain.entities import AppSettings


class LLMNotConfigured(Exception):
    pass


class LLMEmptyResponse(Exception):
    pass


_clients: dict[tuple[str, str], AsyncOpenAI] = {}


def resolve_chat_config(settings: AppSettings) -> tuple[str, str, str]:
    if settings.provider == "custom":
        base_url = settings.base_url.strip()
    else:
        base_url = PROVIDER_BASE_URLS.get(settings.provider, "")
    api_key = settings.api_key.strip()
    model = settings.chat_model.strip()
    if not base_url or not api_key or not model:
        raise LLMNotConfigured(
            "Falta configurar el proveedor LLM (base URL, API key o modelo) en Configuración."
        )
    return base_url, api_key, model


def resolve_ocr_config(settings: AppSettings) -> tuple[str, str, str]:
    base_url = settings.ocr_base_url.strip()
    api_key = settings.ocr_api_key.strip() or settings.api_key.strip()
    model = settings.ocr_model.strip()
    if not base_url or not api_key or not model:
        raise LLMNotConfigured(
            "Falta configurar el OCR (base URL, API key o modelo) en Configuración."
        )
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


async def chat_completion(
    settings: AppSettings,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = LLM_MAX_TOKENS,
) -> str:
    base_url, api_key, model = resolve_chat_config(settings)
    client = make_client(base_url, api_key)
    last_error = "respuesta vacía"
    for attempt in range(2):
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **_openrouter_extras(settings),
        )
        choices = getattr(resp, "choices", None) or []
        if choices:
            text = _message_text(choices[0].message)
            if text.strip():
                return text
        err = getattr(resp, "error", None)
        last_error = str(err) if err else "choices vacío"
        await asyncio.sleep(0.6 * (attempt + 1))
    raise LLMEmptyResponse(
        "El modelo no devolvió contenido "
        f"({last_error}). En el cupo gratuito suele pasar con modelos enormes; "
        "prueba Gemma 4 26B :free (más rápido) o reintenta."
    )


async def ocr_image(settings: AppSettings, image_data_url: str, prompt: str) -> str:
    base_url, api_key, model = resolve_ocr_config(settings)
    client = make_client(base_url, api_key)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ],
        temperature=0,
        max_tokens=LLM_MAX_TOKENS,
        **_openrouter_extras(settings),
    )
    choices = getattr(resp, "choices", None) or []
    if not choices:
        raise LLMEmptyResponse("El modelo OCR no devolvió contenido.")
    return _message_text(choices[0].message) or ""


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
        raise ValueError(f"El modelo no devolvió JSON: {text[:300]}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                return json.loads(candidate)
    raise ValueError(f"JSON incompleto en la respuesta del modelo: {text[:300]}")
