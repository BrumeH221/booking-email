# config.py
#
# Central config. Loads env from .env.gemini / .env.groq / .env via ENV_FILE.

import os
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Env loader (supports ENV_FILE override)
# ---------------------------------------------------------------------------

def _file_has_real_key(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    for line in text.splitlines():
        m = re.match(r"^\s*(GEMINI_API_KEY|GROQ_API_KEY)\s*=\s*(\S+)", line)
        if m and "PASTE_YOUR_" not in m.group(2):
            return True
    return False


def _apply_env_file(env_path: Path) -> None:
    print(f"[config] Loaded env from: {env_path.name}")
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
        return
    except ImportError:
        pass
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _load_env_file():
    base = Path(__file__).parent
    chosen = os.environ.get("ENV_FILE")
    if chosen:
        p = base / chosen
        if p.exists():
            _apply_env_file(p)
            return
    for name in (".env", ".env.gemini", ".env.groq"):
        p = base / name
        if p.exists() and _file_has_real_key(p):
            _apply_env_file(p)
            return


_load_env_file()


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------

RUN_MODE = os.environ.get("RUN_MODE", "local").lower()


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------

USE_LOCAL_MODELS = os.environ.get("USE_LOCAL_MODELS", "false").lower() == "true"
USE_LLM_API = os.environ.get("USE_LLM_API", "true").lower() == "true"

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta",
)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_EMBED_MODEL = os.environ.get("GEMINI_EMBED_MODEL", "text-embedding-004")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

INTENT_MODEL_NAME = os.environ.get(
    "INTENT_MODEL_NAME", "facebook/bart-large-mnli",
)
SENTIMENT_MODEL_NAME = os.environ.get(
    "SENTIMENT_MODEL_NAME", "cardiffnlp/twitter-roberta-base-sentiment-latest",
)
EMBEDDING_MODEL_NAME = os.environ.get(
    "EMBEDDING_MODEL_NAME", "BAAI/bge-m3",
)
SUMMARY_MODEL_NAME = os.environ.get("SUMMARY_MODEL_NAME", "")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_BACKEND = os.environ.get(
    "DB_BACKEND",
    "sqlite" if RUN_MODE == "local" else "supabase",
).lower()

SQLITE_PATH = os.environ.get("SQLITE_PATH", "data/bookings.db")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_BOOKINGS_TABLE = os.environ.get("SUPABASE_BOOKINGS_TABLE", "bookings")
SUPABASE_PROCESSED_TABLE = os.environ.get("SUPABASE_PROCESSED_TABLE", "processed_emails")


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------

SHEETS_ENABLED = os.environ.get("SHEETS_ENABLED", "false").lower() == "true"
SHEETS_SPREADSHEET_ID = os.environ.get("SHEETS_SPREADSHEET_ID", "")
SHEETS_WORKSHEET_NAME = os.environ.get("SHEETS_WORKSHEET_NAME", "Bookings")


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

GMAIL_CREDENTIALS_PATH = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
GMAIL_TOKEN_PATH = os.environ.get("GMAIL_TOKEN_PATH", "token.json")
GMAIL_TOKEN_JSON_ENV = os.environ.get("GMAIL_TOKEN_JSON", "")
GMAIL_CREDENTIALS_JSON_ENV = os.environ.get("GMAIL_CREDENTIALS_JSON", "")

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

GMAIL_SEARCH_QUERY = os.environ.get(
    "GMAIL_SEARCH_QUERY",
    "is:unread -category:promotions -category:social -category:updates",
)


# ---------------------------------------------------------------------------
# Business
# ---------------------------------------------------------------------------

BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Booking Team")
MANAGER_NOTIFY_EMAIL = os.environ.get("MANAGER_NOTIFY_EMAIL", "")
MAX_EMAILS_PER_RUN = int(os.environ.get("MAX_EMAILS_PER_RUN", "20"))

# SOFT threshold — find_similar_bookings uses this to surface possibly-related
# prior emails for the manager.
DUPLICATE_SIMILARITY_THRESHOLD = float(
    os.environ.get("DUPLICATE_SIMILARITY_THRESHOLD", "0.85")
)

# HARD threshold — main.py uses this to BLOCK saving a near-duplicate from the
# same sender (no DB row, no reply, only Gmail mark-as-read).
DUPLICATE_BLOCK_THRESHOLD = float(
    os.environ.get("DUPLICATE_BLOCK_THRESHOLD", "0.92")
)

WORKER_SHARED_SECRET = os.environ.get("WORKER_SHARED_SECRET", "")


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_PENDING = "Pending"
STATUS_NEED_MORE_INFO = "Need More Info"
STATUS_NOT_RELEVANT = "Not Relevant"
STATUS_CONFIRMED = "Confirmed"
STATUS_CANCELLED = "Cancelled"
STATUS_UNAVAILABLE = "Unavailable"
STATUS_COMPLETED = "Completed"

ALL_STATUSES = [
    STATUS_PENDING,
    STATUS_NEED_MORE_INFO,
    STATUS_NOT_RELEVANT,
    STATUS_CONFIRMED,
    STATUS_CANCELLED,
    STATUS_UNAVAILABLE,
    STATUS_COMPLETED,
]


# ---------------------------------------------------------------------------
# Intent constants
# ---------------------------------------------------------------------------

INTENT_NEW_BOOKING = "new_booking"
INTENT_RESCHEDULE = "reschedule_booking"
INTENT_CANCEL = "cancel_booking"
INTENT_PRICE_ENQUIRY = "price_enquiry"
INTENT_COMPLAINT = "complaint"
INTENT_GENERAL_QUESTION = "general_question"
INTENT_NOT_RELEVANT = "not_relevant"

ALL_INTENTS = [
    INTENT_NEW_BOOKING,
    INTENT_RESCHEDULE,
    INTENT_CANCEL,
    INTENT_PRICE_ENQUIRY,
    INTENT_COMPLAINT,
    INTENT_GENERAL_QUESTION,
    INTENT_NOT_RELEVANT,
]

BOOKING_INTENTS = {INTENT_NEW_BOOKING, INTENT_RESCHEDULE, INTENT_CANCEL}


# ---------------------------------------------------------------------------
# Sentiment constants
# ---------------------------------------------------------------------------

SENTIMENT_POSITIVE = "positive"
SENTIMENT_NEUTRAL = "neutral"
SENTIMENT_NEGATIVE = "negative"
SENTIMENT_ANGRY = "angry"
SENTIMENT_URGENT = "urgent"

ALL_SENTIMENTS = [
    SENTIMENT_POSITIVE,
    SENTIMENT_NEUTRAL,
    SENTIMENT_NEGATIVE,
    SENTIMENT_ANGRY,
    SENTIMENT_URGENT,
]


# ---------------------------------------------------------------------------
# Required booking fields (only date + time per business rules)
# ---------------------------------------------------------------------------

REQUIRED_BOOKING_FIELDS = ["preferred_date", "preferred_time"]


def validate_config_for_runtime():
    errors = []
    if USE_LLM_API:
        if LLM_PROVIDER == "gemini" and not GEMINI_API_KEY:
            errors.append("GEMINI_API_KEY required when LLM_PROVIDER=gemini.")
        if LLM_PROVIDER == "groq" and not GROQ_API_KEY:
            errors.append("GROQ_API_KEY required when LLM_PROVIDER=groq.")
    if DB_BACKEND == "supabase":
        if not SUPABASE_URL:
            errors.append("SUPABASE_URL required.")
        if not SUPABASE_KEY:
            errors.append("SUPABASE_KEY required.")
    if errors:
        raise RuntimeError("Config errors:\n  - " + "\n  - ".join(errors))
