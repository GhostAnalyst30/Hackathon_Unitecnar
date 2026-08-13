"""Caso de uso del chatbot: conversa con contexto del documento y devuelve
sugerencias de edición estructuradas (el humano decide si aplicarlas)."""

import json

from sqlalchemy.orm import Session

from ...domain.entities import ChatMessage
from ..agents.chat import run_chat
from ..dtos import ChatResponseDTO, SuggestionDTO
from .documents import get_document, require_llm_configured
from .settings import get_settings


async def send_chat_message(
    session: Session, document_id: str, message: str
) -> ChatResponseDTO:
    require_llm_configured(session)
    doc = get_document(session, document_id)
    settings = get_settings(session)
    history = list(doc.chat_messages)

    user_msg = ChatMessage(document_id=document_id, role="user", content=message)
    session.add(user_msg)
    session.commit()

    reply, suggestions = await run_chat(settings, doc, history, message)

    assistant_msg = ChatMessage(
        document_id=document_id,
        role="assistant",
        content=reply,
        suggestions_json=json.dumps(suggestions, ensure_ascii=False),
    )
    session.add(assistant_msg)
    session.commit()

    return ChatResponseDTO(
        reply=reply,
        suggestions=[SuggestionDTO(**s) for s in suggestions],
        message_id=assistant_msg.id,
    )
