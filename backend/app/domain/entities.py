"""Entidades del dominio (persistidas con SQLAlchemy).

La capa de dominio no depende de application ni de infrastructure:
define las entidades y el `Base` declarativo que infrastructure enlaza al motor.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512))
    file_path: Mapped[str] = mapped_column(String(1024))
    file_format: Mapped[str] = mapped_column(String(16))  # pdf | docx | image
    # queued | extracting | analyzing | awaiting_review | validated | discarded | error
    status: Mapped[str] = mapped_column(String(32), default="queued")
    content_html: Mapped[str] = mapped_column(Text, default="")
    content_text: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    findings: Mapped[list["Finding"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    agent_outputs: Mapped[list["AgentOutput"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    chat_messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    process_logs: Mapped[list["ProcessLog"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ProcessLog.created_at",
    )


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    agent: Mapped[str] = mapped_column(String(32))  # reader | contradictions | references
    # importante | alerta | contradiccion | inconsistencia | referencia
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16), default="media")  # baja | media | alta
    quote: Mapped[str] = mapped_column(Text, default="")
    quote_secondary: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    anchored: Mapped[bool] = mapped_column(Boolean, default=False)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    document: Mapped[Document] = relationship(back_populates="findings")


class AgentOutput(Base):
    __tablename__ = "agent_outputs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    agent: Mapped[str] = mapped_column(String(32))
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    document: Mapped[Document] = relationship(back_populates="agent_outputs")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    suggestions_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    document: Mapped[Document] = relationship(back_populates="chat_messages")


class ProcessLog(Base):
    """Comentario de proceso de un agente, para visualizar el pipeline en vivo."""

    __tablename__ = "process_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    agent: Mapped[str] = mapped_column(String(32))  # ingest | reader | contradictions | references | classifier
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    document: Mapped[Document] = relationship(back_populates="process_logs")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # qianfan | openai | openrouter | custom
    provider: Mapped[str] = mapped_column(String(32), default="openrouter")
    api_key: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(String(512), default="")  # solo para provider=custom
    chat_model: Mapped[str] = mapped_column(String(128), default="google/gemma-4-26b-a4b-it:free")
    chat_fallback_models: Mapped[str] = mapped_column(
        Text, default="google/gemma-4-31b-it:free,openrouter/free"
    )

    ocr_api_key: Mapped[str] = mapped_column(Text, default="")  # si vacío, usa api_key
    ocr_base_url: Mapped[str] = mapped_column(
        String(512), default="https://openrouter.ai/api/v1"
    )
    ocr_model: Mapped[str] = mapped_column(String(128), default="google/gemma-4-26b-a4b-it:free")
    ocr_fallback_models: Mapped[str] = mapped_column(
        Text, default="google/gemma-4-31b-it:free,openrouter/free"
    )

    reader_instructions: Mapped[str] = mapped_column(Text, default="")
    contradictions_instructions: Mapped[str] = mapped_column(Text, default="")
    references_instructions: Mapped[str] = mapped_column(Text, default="")
    classifier_instructions: Mapped[str] = mapped_column(Text, default="")
    chat_instructions: Mapped[str] = mapped_column(Text, default="")
