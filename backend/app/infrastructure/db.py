from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from ..config import DATABASE_URL, DB_PATH, DEFAULT_CHAT_FALLBACKS, DEFAULT_OCR_FALLBACKS
from ..domain.entities import Base


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


if DATABASE_URL:
    engine = create_engine(
        _sqlalchemy_url(DATABASE_URL),
        pool_pre_ping=True,
        poolclass=NullPool,
    )
else:
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
    tables = inspector.get_table_names()
    if "app_settings" in tables:
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
    if "findings" in tables:
        existing = {col["name"] for col in inspector.get_columns("findings")}
        if "rects_json" not in existing:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE findings ADD COLUMN rects_json TEXT DEFAULT '[]'")
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
