"""Casos de uso de configuración: leer, actualizar y probar conexión."""

from sqlalchemy.orm import Session

from ...config import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_OCR_BASE_URL,
    DEFAULT_OCR_MODEL,
    DEFAULT_PROVIDER,
)
from ...domain.entities import AppSettings
from ...infrastructure.llm import (
    LLMNotConfigured,
    chat_completion,
    ocr_image,
    resolve_chat_config,
    resolve_ocr_config,
)
from ..dtos import SettingsUpdateDTO, TestConnectionResponseDTO

# Imagen PNG 1x1 blanca para probar la conexión OCR
_TEST_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def get_settings(session: Session) -> AppSettings:
    settings = session.get(AppSettings, 1)
    if settings is None:
        settings = AppSettings(id=1)
        session.add(settings)
        session.commit()
        return settings

    # Si nunca se configuró una key y sigue el default anterior (Qianfan de pago),
    # migra a OpenRouter con modelos :free para no gastar tokens.
    if not settings.api_key.strip() and settings.provider == "qianfan":
        settings.provider = DEFAULT_PROVIDER
        settings.chat_model = DEFAULT_CHAT_MODEL
        settings.ocr_base_url = DEFAULT_OCR_BASE_URL
        settings.ocr_model = DEFAULT_OCR_MODEL
        session.commit()
    return settings


def update_settings(session: Session, payload: SettingsUpdateDTO) -> AppSettings:
    settings = get_settings(session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(settings, field, value)
    session.commit()
    return settings


async def test_connection(session: Session, target: str) -> TestConnectionResponseDTO:
    settings = get_settings(session)
    try:
        if target == "ocr":
            resolve_ocr_config(settings)
            await ocr_image(settings, _TEST_IMAGE, "Describe la imagen en una palabra.")
            return TestConnectionResponseDTO(ok=True, detail="Conexión OCR exitosa")
        resolve_chat_config(settings)
        reply = await chat_completion(
            settings,
            [{"role": "user", "content": "Responde únicamente: OK"}],
        )
        return TestConnectionResponseDTO(ok=True, detail="Conexión exitosa", data=reply[:100])
    except LLMNotConfigured as exc:
        return TestConnectionResponseDTO(ok=False, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        return TestConnectionResponseDTO(ok=False, detail=f"Error de conexión: {exc}")
