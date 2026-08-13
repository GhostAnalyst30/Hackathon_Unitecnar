"""Adaptador LLM: clientes OpenAI-compatibles intercambiables
(Qianfan, OpenAI, OpenRouter o endpoint custom).

Toda la configuración (proveedor, modelo, API key) vive en AppSettings y se
edita desde la UI. Nada está hardcodeado.
"""

import json
import re

from openai import AsyncOpenAI

from ..config import PROVIDER_BASE_URLS
from ..domain.entities import AppSettings


class LLMNotConfigured(Exception):
    pass


def resolve_chat_config(settings: AppSettings) -> tuple[str, str, str]:
    """Devuelve (base_url, api_key, model) para el LLM de los agentes."""
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
    """Devuelve (base_url, api_key, model) para el OCR (Qianfan-OCR o un modelo de visión)."""
    base_url = settings.ocr_base_url.strip()
    api_key = settings.ocr_api_key.strip() or settings.api_key.strip()
    model = settings.ocr_model.strip()
    if not base_url or not api_key or not model:
        raise LLMNotConfigured(
            "Falta configurar el OCR (base URL, API key o modelo) en Configuración."
        )
    return base_url, api_key, model


def make_client(base_url: str, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=300, max_retries=2)


async def chat_completion(
    settings: AppSettings,
    messages: list[dict],
    temperature: float = 0.2,
) -> str:
    base_url, api_key, model = resolve_chat_config(settings)
    client = make_client(base_url, api_key)
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


async def ocr_image(settings: AppSettings, image_data_url: str, prompt: str) -> str:
    """Transcribe una imagen usando el modelo OCR configurado (chat multimodal)."""
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
    )
    return resp.choices[0].message.content or ""


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
