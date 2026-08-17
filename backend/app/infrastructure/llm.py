"""Adaptador LLM: clientes OpenAI-compatibles con pool, fallbacks y errores opacos.

Si el modelo principal no responde, se recorre la cadena que configuró el
usuario (principal + respaldos), varias veces, con espera entre intentos.
Los fallos técnicos no se exponen al usuario hasta agotar esa cadena.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timezone

from openai import AsyncOpenAI

from ..config import (
    LLM_ATTEMPTS_PER_MODEL,
    LLM_CHAIN_ROUNDS,
    LLM_MAX_CONCURRENT,
    LLM_MAX_TOKENS,
    LLM_RETRY_BASE_DELAY,
    LLM_TIMEOUT,
    PROVIDER_BASE_URLS,
)
from ..domain.entities import AppSettings

logger = logging.getLogger("llm")

PUBLIC_READ_ERROR = (
    "El servidor no pudo leer los datos. Inténtalo de nuevo en un momento."
)
PUBLIC_CONFIG_ERROR = "Falta configurar el modelo o la API key en Configuración."
PUBLIC_QUOTA_ERROR = (
    "Se agotó el cupo diario de modelos gratis de OpenRouter (50 peticiones/día). "
    "Todos los `:free` comparten ese tope. Se reinicia a medianoche UTC "
    "(7:00 p. m. en Colombia). Para seguir ahora, añade créditos en "
    "openrouter.ai/credits o usa un modelo de pago en Configuración."
)

# (modelo_fallido, siguiente_modelo, motivo_corto)
RetryHook = Callable[[str, str, str], None]
retry_hook: ContextVar[RetryHook | None] = ContextVar("llm_retry_hook", default=None)

_llm_gate = asyncio.Semaphore(LLM_MAX_CONCURRENT)


class LLMNotConfigured(Exception):
    pass


class LLMEmptyResponse(Exception):
    pass


class LLMQuotaExceeded(Exception):
    pass


def public_error_message(exc: BaseException) -> str:
    if isinstance(exc, LLMNotConfigured):
        return PUBLIC_CONFIG_ERROR
    if isinstance(exc, LLMQuotaExceeded):
        return str(exc) or PUBLIC_QUOTA_ERROR
    return PUBLIC_READ_ERROR


def is_free_model(slug: str) -> bool:
    key = (slug or "").strip().lower()
    return key.endswith(":free") or key == "openrouter/free"


def describe_llm_error(exc: BaseException) -> str:
    if isinstance(exc, LLMQuotaExceeded):
        return "cupo diario de modelos gratis agotado"
    if isinstance(exc, LLMEmptyResponse):
        msg = str(exc).strip()
        if msg and msg != PUBLIC_READ_ERROR:
            return msg
        return "respuesta vacía"
    if isinstance(exc, (ValueError, json.JSONDecodeError)):
        return "JSON inválido"
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    if status == 429 or "RateLimit" in name:
        return "límite de peticiones"
    if status in (500, 502, 503, 504):
        return "servidor saturado"
    if status == 404:
        return "modelo no disponible"
    if "Timeout" in name:
        return "tiempo agotado"
    if "Connect" in name or "Connection" in name:
        return "sin conexión"
    return "sin respuesta"


def notify_model_retry(failed: str, nxt: str, reason: str) -> None:
    hook = retry_hook.get()
    if hook:
        try:
            hook(failed, nxt, reason)
        except Exception:  # noqa: BLE001
            logger.exception("El aviso de reintento falló")


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


def next_in_chain(
    chain: list[str], index: int, round_i: int, rounds: int
) -> str | None:
    if index + 1 < len(chain):
        return chain[index + 1]
    if round_i + 1 < rounds:
        return chain[0]
    return None


def retry_target_label(
    chain: list[str], index: int, round_i: int, rounds: int
) -> str | None:
    nxt = next_in_chain(chain, index, round_i, rounds)
    if not nxt:
        return None
    if nxt == chain[0] and index + 1 >= len(chain):
        return f"{nxt} (nueva pasada de la cadena configurada)"
    return nxt


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
            max_retries=0,
            default_headers={
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "Clumi",
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


def _request_extras(settings: AppSettings, base_url: str = "") -> dict:
    url = (base_url or "").lower()
    if "openrouter.ai" in url:
        return {
            "extra_body": {
                "provider": {"sort": "throughput", "allow_fallbacks": True},
            }
        }
    if "generativelanguage.googleapis.com" in url:
        return {
            "extra_body": {
                "google": {"thinking_config": {"thinking_budget": 0}},
            }
        }
    if settings.provider == "openrouter":
        return {
            "extra_body": {
                "provider": {"sort": "throughput", "allow_fallbacks": True},
            }
        }
    if settings.provider == "gemini":
        # Sin thinking: respuestas JSON más fiables y menos vacías.
        return {
            "extra_body": {
                "google": {"thinking_config": {"thinking_budget": 0}},
            }
        }
    return {}


def _status_code(exc: BaseException) -> int | None:
    return getattr(exc, "status_code", None)


def _openai_error_body(exc: BaseException) -> dict:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        return body
    response = getattr(exc, "response", None)
    if response is not None:
        parser = getattr(response, "json", None)
        if callable(parser):
            try:
                data = parser()
                if isinstance(data, dict):
                    return data
            except Exception:  # noqa: BLE001
                pass
    return {}


def quota_from_exc(exc: BaseException) -> LLMQuotaExceeded | None:
    body = _openai_error_body(exc)
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    meta = err.get("metadata") if isinstance(err.get("metadata"), dict) else {}
    message = str(err.get("message") or exc)
    source = str(meta.get("limit_source") or "")
    if source != "openrouter_free_tier_daily" and "free-models-per-day" not in message.lower():
        return None
    extra = ""
    headers = meta.get("headers") if isinstance(meta.get("headers"), dict) else {}
    raw_reset = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")
    if raw_reset:
        try:
            reset_at = datetime.fromtimestamp(int(raw_reset) / 1000, tz=timezone.utc)
            local = reset_at.astimezone()
            extra = f" Se reinicia el {local.strftime('%d/%m a las %H:%M')}."
        except (OSError, TypeError, ValueError):
            extra = ""
    return LLMQuotaExceeded(PUBLIC_QUOTA_ERROR + extra)


def _retry_same_model(exc: BaseException) -> bool:
    if quota_from_exc(exc) is not None:
        return False
    status = _status_code(exc)
    name = type(exc).__name__
    if "Authentication" in name or status == 401:
        return False
    if status in (400, 404, 422):
        return False
    return True


def _backoff_seconds(exc: BaseException, attempt: int) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    retry_after = headers.get("retry-after") or headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 20.0)
        except (TypeError, ValueError):
            pass
    status = _status_code(exc)
    base = LLM_RETRY_BASE_DELAY * (
        2.5 if status == 429 or "RateLimit" in type(exc).__name__ else 1.0
    )
    return min(base * (2**attempt), 16.0)


async def _complete_once(
    client: AsyncOpenAI,
    settings: AppSettings,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    attempts: int,
    extras: dict | None = None,
) -> str:
    last_error = "sin contenido"
    last_exc: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            async with _llm_gate:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **(extras or {}),
                )
        except Exception as exc:  # noqa: BLE001
            if _status_code(exc) == 401 or "Authentication" in type(exc).__name__:
                raise LLMNotConfigured(PUBLIC_CONFIG_ERROR) from None
            quota = quota_from_exc(exc)
            if quota is not None:
                logger.warning("Cupo diario :free agotado en %s", model)
                raise quota from exc
            last_exc = exc
            last_error = describe_llm_error(exc)
            logger.warning("Modelo %s falló (%s): %s", model, last_error, exc)
            if not _retry_same_model(exc) or attempt + 1 >= attempts:
                raise
            await asyncio.sleep(_backoff_seconds(exc, attempt))
            continue
        choices = getattr(resp, "choices", None) or []
        if choices:
            text = _message_text(choices[0].message)
            if text.strip():
                return text
        last_error = "respuesta vacía"
        last_exc = LLMEmptyResponse(last_error)
        logger.warning("Modelo %s devolvió vacío (intento %s)", model, attempt + 1)
        if attempt + 1 >= attempts:
            break
        await asyncio.sleep(_backoff_seconds(last_exc, attempt))
    raise LLMEmptyResponse(last_error) from last_exc


async def _complete_chain(
    client: AsyncOpenAI,
    settings: AppSettings,
    chain: list[str],
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    attempts_per_model: int,
    chain_rounds: int,
    extras: dict | None = None,
) -> str:
    if not chain:
        raise LLMNotConfigured(PUBLIC_CONFIG_ERROR)
    last_exc: Exception | None = None
    rounds = max(1, chain_rounds)
    skip_free = False
    for round_i in range(rounds):
        if round_i:
            if skip_free and all(is_free_model(m) for m in chain):
                break
            await asyncio.sleep(3.0)
        for index, candidate in enumerate(chain):
            if skip_free and is_free_model(candidate):
                continue
            try:
                text = await _complete_once(
                    client,
                    settings,
                    candidate,
                    messages,
                    temperature,
                    max_tokens,
                    attempts_per_model,
                    extras,
                )
                if index or round_i:
                    logger.info("Usando modelo de respaldo %s", candidate)
                return text
            except LLMNotConfigured:
                raise
            except LLMQuotaExceeded as exc:
                last_exc = exc
                skip_free = True
                paid = next((m for m in chain[index + 1 :] if not is_free_model(m)), None)
                logger.warning("Cupo diario :free agotado; no reintento otros modelos gratis.")
                if paid:
                    notify_model_retry(candidate, paid, describe_llm_error(exc))
                    continue
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                reason = describe_llm_error(exc)
                logger.warning("No se pudo usar %s (%s), paso al siguiente.", candidate, reason)
                label = retry_target_label(chain, index, round_i, rounds)
                if label:
                    notify_model_retry(candidate, label, reason)
    if isinstance(last_exc, LLMQuotaExceeded):
        raise last_exc
    raise LLMEmptyResponse(PUBLIC_READ_ERROR) from last_exc


async def chat_completion(
    settings: AppSettings,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = LLM_MAX_TOKENS,
    model: str | None = None,
    attempts_per_model: int | None = None,
    chain_rounds: int | None = None,
) -> str:
    base_url, api_key, _primary = resolve_chat_config(settings)
    client = make_client(base_url, api_key)
    chain = [model] if model else chat_model_chain(settings)
    return await _complete_chain(
        client,
        settings,
        chain,
        messages,
        temperature,
        max_tokens,
        attempts_per_model if attempts_per_model is not None else LLM_ATTEMPTS_PER_MODEL,
        chain_rounds if chain_rounds is not None else (1 if model else LLM_CHAIN_ROUNDS),
        extras=_request_extras(settings, base_url),
    )


async def ocr_image(
    settings: AppSettings,
    image_data_url: str,
    prompt: str,
    attempts_per_model: int | None = None,
    chain_rounds: int | None = None,
) -> str:
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
    return await _complete_chain(
        client,
        settings,
        ocr_model_chain(settings),
        messages,
        0,
        LLM_MAX_TOKENS,
        LLM_ATTEMPTS_PER_MODEL if attempts_per_model is None else attempts_per_model,
        LLM_CHAIN_ROUNDS if chain_rounds is None else chain_rounds,
        extras=_request_extras(settings, base_url),
    )


def _parse_json_object(text: str) -> dict | None:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    try:
        data, _ = json.JSONDecoder().raw_decode(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _repair_truncated_object(text: str) -> str:
    """Cierra strings/llaves/corchetes y recorta un value incompleto al final."""
    s = text.strip()
    if not s.startswith("{"):
        return s
    in_str = False
    escape = False
    for ch in s:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
    if in_str:
        if s.endswith("\\") and not s.endswith("\\\\"):
            s = s[:-1]
        s += '"'
    s = s.rstrip()
    while s:
        s = s.rstrip()
        if s.endswith(","):
            s = s[:-1]
            continue
        if s.endswith(":"):
            s = re.sub(r',?\s*"(?:\\.|[^"\\])*"\s*:\s*$', "", s)
            continue
        break

    in_str = False
    escape = False
    stack: list[str] = []
    for ch in s:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
    closers = {"{": "}", "[": "]"}
    return s + "".join(closers[c] for c in reversed(stack))


def extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON válido; si viene truncado, intenta cerrarlo."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    else:
        half = re.search(r"```(?:json)?\s*(.*)", text, re.DOTALL)
        if half:
            text = half.group(1).strip()
    parsed = _parse_json_object(text)
    if parsed is not None:
        return parsed
    start = text.find("{")
    if start == -1:
        raise ValueError("respuesta no estructurada")
    blob = text[start:]
    parsed = _parse_json_object(blob)
    if parsed is not None:
        return parsed
    parsed = _parse_json_object(_repair_truncated_object(blob))
    if parsed is not None:
        logger.warning("JSON truncado; se recuperó un objeto parcial")
        return parsed
    raise ValueError("respuesta incompleta")
