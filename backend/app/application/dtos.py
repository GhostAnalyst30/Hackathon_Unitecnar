"""DTOs (Data Transfer Objects) de la capa de aplicación.

Definen los contratos de entrada y salida de la API; las entidades del dominio
nunca se exponen directamente.
"""

from datetime import datetime
from typing import Any

import json

from pydantic import BaseModel, ConfigDict, Field, computed_field


class HighlightRectDTO(BaseModel):
    page: int
    x: float
    y: float
    w: float
    h: float


class FindingDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent: str
    kind: str
    severity: str
    quote: str
    quote_secondary: str | None
    explanation: str
    anchored: bool
    start_offset: int | None
    end_offset: int | None
    rects_json: str | None = Field(default="[]", exclude=True)

    @computed_field
    @property
    def rects(self) -> list[HighlightRectDTO]:
        try:
            raw = json.loads(self.rects_json or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, list):
            return []
        out: list[HighlightRectDTO] = []
        for item in raw:
            try:
                out.append(HighlightRectDTO.model_validate(item))
            except Exception:  # noqa: BLE001
                continue
        return out


class AgentOutputDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent: str
    output_json: str
    created_at: datetime


class ChatMessageDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    suggestions_json: str
    created_at: datetime


class ProcessLogDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent: str
    message: str
    created_at: datetime


class DocumentSummaryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_format: str
    status: str
    score: int | None
    classification: str | None
    error: str | None
    ocr_used: bool
    created_at: datetime
    updated_at: datetime


class DocumentDetailDTO(DocumentSummaryDTO):
    content_html: str
    decision_comment: str | None
    findings: list[FindingDTO] = []
    agent_outputs: list[AgentOutputDTO] = []
    chat_messages: list[ChatMessageDTO] = []
    process_logs: list[ProcessLogDTO] = []


class ContentUpdateDTO(BaseModel):
    content_html: str


class DecisionDTO(BaseModel):
    decision: str  # validated | discarded
    comment: str | None = None


class ChatRequestDTO(BaseModel):
    message: str


class SuggestionDTO(BaseModel):
    original: str
    suggested: str
    reason: str


class ChatResponseDTO(BaseModel):
    reply: str
    suggestions: list[SuggestionDTO] = []
    message_id: str


class SettingsDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    api_key: str
    base_url: str
    chat_model: str
    chat_fallback_models: str
    ocr_api_key: str
    ocr_base_url: str
    ocr_model: str
    ocr_fallback_models: str
    reader_instructions: str
    contradictions_instructions: str
    references_instructions: str
    classifier_instructions: str
    chat_instructions: str


class SettingsUpdateDTO(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    chat_model: str | None = None
    chat_fallback_models: str | None = None
    ocr_api_key: str | None = None
    ocr_base_url: str | None = None
    ocr_model: str | None = None
    ocr_fallback_models: str | None = None
    reader_instructions: str | None = None
    contradictions_instructions: str | None = None
    references_instructions: str | None = None
    classifier_instructions: str | None = None
    chat_instructions: str | None = None


class TestConnectionRequestDTO(BaseModel):
    target: str = "chat"  # chat | ocr


class TestConnectionResponseDTO(BaseModel):
    ok: bool
    detail: str
    data: Any | None = None
