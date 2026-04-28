import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")


def _read_streamlit_secret(key: str) -> str:
    try:
        import streamlit as st

        value = st.secrets.get(key)
    except Exception:
        return ""
    return str(value) if value is not None else ""


def _read_config_value(key: str, default: str = "") -> str:
    return os.getenv(key) or _read_streamlit_secret(key) or default


HF_TOKEN: str = _read_config_value("HF_TOKEN")
GROQ_API_KEY: str = _read_config_value("GROQ_API_KEY")

# Groq-hosted models (free tier). Both are OpenAI-compatible chat models.
FAST_MODEL = "llama-3.1-8b-instant"
THINKING_MODEL = "llama-3.3-70b-versatile"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

MODELS = {
    "Fast": FAST_MODEL,
    "Thinking": THINKING_MODEL,
}

CHROMA_DB_PATH: str = _read_config_value("CHROMA_DB_PATH", str(BASE_DIR / "chroma_db"))
# Resolve relative path against BASE_DIR so it works regardless of CWD
if not os.path.isabs(CHROMA_DB_PATH):
    CHROMA_DB_PATH = str(BASE_DIR / CHROMA_DB_PATH)

TRAVEL_GUIDES_DIR: str = str(BASE_DIR / "data" / "travel_guides")

RAG_TOP_K: int = 8
RAG_MIN_SCORE: float = 0.35
RAG_COLLECTION_NAME: str = "travel_knowledge"

# Default origin for trip recommendations when the user doesn't name one.
USER_HOME_CITY: str = "San Jose"
USER_HOME_STATE: str = "CA"
USER_HOME: str = f"{USER_HOME_CITY}, {USER_HOME_STATE}"
