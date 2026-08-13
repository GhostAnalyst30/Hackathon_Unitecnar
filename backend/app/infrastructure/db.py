from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from ..config import DB_PATH, DEFAULT_CHAT_FALLBACKS, DEFAULT_OCR_FALLBACKS
from ..domain.entities import Base

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

_NEW_COLUMNS = {
    "chat_fallback_models": DEFAULT_CHAT_FALLBACKS,
    "ocr_fallback_models": DEFAULT_OCR_FALLBACKS,
}


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    if "app_settings" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("app_settings")}
    with engine.begin() as conn:
        for name, default in _NEW_COLUMNS.items():
            if name in existing:
                continue
            escaped = default.replace("'", "''")
            conn.execute(
                text(
                    f"ALTER TABLE app_settings ADD COLUMN {name} TEXT DEFAULT '{escaped}'"
                )
            )


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
