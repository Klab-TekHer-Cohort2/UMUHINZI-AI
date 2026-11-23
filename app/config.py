"""Central configuration, loaded from environment variables / `.env`.

Keeping all settings in one place makes it easy to explain during the demo.
Copy `.env.example` to `.env` before running the server.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = folder that contains `app/`.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load `.env` if it exists (it is git-ignored and only used locally).
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to a default."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# --- Africa's Talking (telephony / SMS) ---
AT_USERNAME = os.getenv("AT_USERNAME", "sandbox")
AT_API_KEY = os.getenv("AT_API_KEY", "").strip()
AT_SENDER_ID = os.getenv("AT_SENDER_ID", "UMUHINZI")
AT_USSD_CODE = os.getenv("AT_USSD_CODE", "*123#")

# --- Outbreak early warning ---
OUTBREAK_THRESHOLD = _int("OUTBREAK_THRESHOLD", 3)
OUTBREAK_WINDOW_DAYS = _int("OUTBREAK_WINDOW_DAYS", 7)

# --- Storage ---
DATABASE_PATH = os.getenv("DATABASE_PATH", "umuhinzi.db")
# Make a relative DB path relative to the project root, not the CWD.
DB_FILE = Path(DATABASE_PATH)
if not DB_FILE.is_absolute():
    DB_FILE = BASE_DIR / DB_FILE

# --- ASR / TTS backends ---
# `mock` is the safe default for both. Set ASR_BACKEND=sunbird/nvidia and/or
# TTS_BACKEND=sunbird in `.env` to use real Kinyarwanda speech services.
ASR_BACKEND = os.getenv("ASR_BACKEND", "mock").strip().lower()
ASR_FALLBACK = os.getenv("ASR_FALLBACK", "sunbird").strip().lower()
TTS_BACKEND = os.getenv("TTS_BACKEND", "mock").strip().lower()

DEFAULT_NVIDIA_ASR_MODEL = "nvidia/stt_rw_conformer_transducer_large"
NVIDIA_ASR_MODEL = os.getenv("NVIDIA_ASR_MODEL", DEFAULT_NVIDIA_ASR_MODEL).strip()

# --- Sunbird AI speech services (free developer tier) ---
# One token is shared by STT and TTS. Never commit or log this value.
SUNBIRD_API_TOKEN = os.getenv("SUNBIRD_API_TOKEN", "").strip()
SUNBIRD_STT_URL = os.getenv(
    "SUNBIRD_STT_URL", "https://api.sunbird.ai/tasks/audio/transcriptions"
).strip()
SUNBIRD_TTS_URL = os.getenv(
    "SUNBIRD_TTS_URL", "https://api.sunbird.ai/tasks/audio/speech"
).strip()
# Optional speaker name/tag; when empty Sunbird picks a voice for the language.
SUNBIRD_TTS_VOICE = os.getenv("SUNBIRD_TTS_VOICE", "").strip()
SUNBIRD_TIMEOUT_SECONDS = _int("SUNBIRD_TIMEOUT_SECONDS", 45)


def africastalking_is_configured() -> bool:
    """True when real API keys are present; otherwise SMS/voice runs in dry-run mode."""
    return bool(AT_API_KEY) and AT_API_KEY != "your_africastalking_api_key_here"


def sunbird_is_configured() -> bool:
    """True when a Sunbird token is available. Used only for status displays."""
    return bool(SUNBIRD_API_TOKEN)
