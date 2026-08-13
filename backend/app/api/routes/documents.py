"""Router de documentos: capa delgada que delega en los casos de uso
y traduce entidades/errores del dominio a DTOs/códigos HTTP."""

import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...application import dtos
from ...application.use_cases import chat as chat_uc
from ...application.use_cases import documents as documents_uc
from ...application.use_cases.documents import DocumentNotFound, InvalidOperation
from ...infrastructure.db import get_session
from ...infrastructure.llm import LLMNotConfigured, public_error_message

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, DocumentNotFound):
        return HTTPException(404, str(exc))
    if isinstance(exc, (InvalidOperation, ValueError)):
        return HTTPException(400, str(exc))
    if isinstance(exc, LLMNotConfigured):
        return HTTPException(400, public_error_message(exc))
    return HTTPException(500, public_error_message(exc))


@router.post("", response_model=list[dtos.DocumentSummaryDTO])
async def upload_documents(
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
):
    payload = [(f.filename or "documento", await f.read()) for f in files]
    try:
        return documents_uc.create_documents(session, payload)
    except (LLMNotConfigured, ValueError) as exc:
        raise _handle(exc) from exc


@router.get("", response_model=list[dtos.DocumentSummaryDTO])
def list_documents(session: Session = Depends(get_session)):
    return documents_uc.list_documents(session)


@router.get("/{document_id}", response_model=dtos.DocumentDetailDTO)
def get_document(document_id: str, session: Session = Depends(get_session)):
    try:
        return documents_uc.get_document(session, document_id)
    except DocumentNotFound as exc:
        raise _handle(exc) from exc


@router.delete("/{document_id}")
def delete_document(document_id: str, session: Session = Depends(get_session)):
    try:
        documents_uc.delete_document(session, document_id)
    except DocumentNotFound as exc:
        raise _handle(exc) from exc
    return {"ok": True}


@router.put("/{document_id}/content", response_model=list[dtos.FindingDTO])
def update_content(
    document_id: str,
    payload: dtos.ContentUpdateDTO,
    session: Session = Depends(get_session),
):
    try:
        return documents_uc.update_content(session, document_id, payload.content_html)
    except DocumentNotFound as exc:
        raise _handle(exc) from exc


@router.post("/{document_id}/reanalyze", response_model=dtos.DocumentSummaryDTO)
async def reanalyze(document_id: str, session: Session = Depends(get_session)):
    # async: enqueue_analysis necesita el event loop para crear la tarea del pipeline
    try:
        return documents_uc.reanalyze_document(session, document_id)
    except InvalidOperation as exc:
        raise HTTPException(409, str(exc)) from exc
    except (DocumentNotFound, LLMNotConfigured) as exc:
        raise _handle(exc) from exc


@router.post("/{document_id}/decision", response_model=dtos.DocumentSummaryDTO)
def decide(
    document_id: str,
    payload: dtos.DecisionDTO,
    session: Session = Depends(get_session),
):
    try:
        return documents_uc.decide_document(
            session, document_id, payload.decision, payload.comment
        )
    except (DocumentNotFound, InvalidOperation) as exc:
        raise _handle(exc) from exc


@router.post("/{document_id}/chat", response_model=dtos.ChatResponseDTO)
async def chat(
    document_id: str,
    payload: dtos.ChatRequestDTO,
    session: Session = Depends(get_session),
):
    try:
        return await chat_uc.send_chat_message(session, document_id, payload.message)
    except (DocumentNotFound, LLMNotConfigured) as exc:
        raise _handle(exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, public_error_message(exc)) from exc


@router.get("/{document_id}/export")
def export_document(
    document_id: str,
    format: str = "md",
    session: Session = Depends(get_session),
):
    try:
        data, media_type, filename = documents_uc.export_document(
            session, document_id, format
        )
    except (DocumentNotFound, InvalidOperation) as exc:
        raise _handle(exc) from exc
    return StreamingResponse(
        io.BytesIO(data),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
