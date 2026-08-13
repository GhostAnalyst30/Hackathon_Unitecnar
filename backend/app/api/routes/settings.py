from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...application import dtos
from ...application.use_cases import settings as settings_uc
from ...infrastructure.db import get_session

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=dtos.SettingsDTO)
def read_settings(session: Session = Depends(get_session)):
    return settings_uc.get_settings(session)


@router.put("", response_model=dtos.SettingsDTO)
def update_settings(
    payload: dtos.SettingsUpdateDTO, session: Session = Depends(get_session)
):
    return settings_uc.update_settings(session, payload)


@router.post("/test", response_model=dtos.TestConnectionResponseDTO)
async def test_connection(
    payload: dtos.TestConnectionRequestDTO, session: Session = Depends(get_session)
):
    return await settings_uc.test_connection(session, payload.target)
