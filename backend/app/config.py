import os
from pathlib import Path

IS_VERCEL = os.environ.get("VERCEL") == "1"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path("/tmp/clumi") if IS_VERCEL else (BASE_DIR / "data")
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "app.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

OCR_BOXES_DIR = DATA_DIR / "ocr_boxes"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
OCR_BOXES_DIR.mkdir(parents=True, exist_ok=True)

FRONTEND_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://hackathon-unitecnar.vercel.app",
]
_frontend_url = os.environ.get("FRONTEND_URL", "").strip().rstrip("/")
if _frontend_url:
    FRONTEND_ORIGINS.append(_frontend_url)

# Límite de documentos analizándose en paralelo
MAX_CONCURRENT_ANALYSES = 4

# Documento enviado a los agentes: cabeza + fragmento central + cola
MAX_DOC_HEAD_CHARS = 7000
MAX_DOC_MID_CHARS = 4000
MAX_DOC_TAIL_CHARS = 5000

LLM_TIMEOUT = 90
LLM_MAX_TOKENS = 1100
# Reintentos por modelo (429/vacío/timeout) y pasadas sobre la cadena del usuario.
LLM_ATTEMPTS_PER_MODEL = 3
LLM_CHAIN_ROUNDS = 2
LLM_RETRY_BASE_DELAY = 1.5
# Los 3 agentes corren en paralelo; este tope evita 429 en el cupo :free.
LLM_MAX_CONCURRENT = 2

PROVIDER_BASE_URLS = {
    "qianfan": "https://qianfan.baidubce.com/v2",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}

# OpenRouter de pago barato por defecto (visión). Los :free tienen tope diario.
DEFAULT_PROVIDER = "openrouter"
DEFAULT_CHAT_MODEL = "google/gemini-2.5-flash-lite"
DEFAULT_OCR_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OCR_MODEL = "google/gemini-2.5-flash-lite"
DEFAULT_CHAT_FALLBACKS = "google/gemini-2.5-flash,openai/gpt-4o-mini"
DEFAULT_OCR_FALLBACKS = "google/gemini-2.5-flash,openai/gpt-4o-mini"

# Contacto para el "polite pool" de la Crossref REST API (sin API key)
CROSSREF_MAILTO = "clumi@localhost.dev"
