from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "app.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Límite de documentos analizándose en paralelo
MAX_CONCURRENT_ANALYSES = 4

# Documento enviado a los agentes: cabeza + fragmento central + cola
MAX_DOC_HEAD_CHARS = 7000
MAX_DOC_MID_CHARS = 4000
MAX_DOC_TAIL_CHARS = 5000

LLM_TIMEOUT = 90
LLM_MAX_TOKENS = 1100

PROVIDER_BASE_URLS = {
    "qianfan": "https://qianfan.baidubce.com/v2",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# OpenRouter :free por defecto (agentes y OCR). Gemma 4 31B es multimodal
# y entiende documentos; el sufijo :free no cobra tokens.
DEFAULT_PROVIDER = "openrouter"
DEFAULT_CHAT_MODEL = "google/gemma-4-26b-a4b-it:free"
DEFAULT_OCR_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OCR_MODEL = "google/gemma-4-26b-a4b-it:free"

# Contacto para el "polite pool" de la Crossref REST API (sin API key)
CROSSREF_MAILTO = "ghostanalyst@localhost.dev"
