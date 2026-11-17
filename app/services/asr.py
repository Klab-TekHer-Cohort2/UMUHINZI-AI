"""Speech recognition behind a small `transcribe(audio)` abstraction.

Backends are selected with `ASR_BACKEND` in `.env`:

- `mock` (default) - no network calls. If `audio` is a string it is returned
  as-is (handy for tests/demos). For real audio bytes it returns
  `MOCK_ASR_TEXT` if set, otherwise an empty string so the voice layer asks the
  farmer to repeat.
- `sunbird` - calls Sunbird AI's free speech-to-text API with Kinyarwanda
  (`language=kin`). On any error (missing/expired token, timeout, bad response)
  we log a clear warning and fall back to mock, i.e. typically an empty
  transcription and a polite "please repeat" prompt.

TODO (future): add a fully local, open-source Kinyarwanda ASR backend (for
example a fine-tuned Whisper model) and register it here. Keep the same
`transcribe(audio)` interface so callers do not change.
"""

from __future__ import annotations

import logging
import os

import requests

from app import config
from app.services.audio import prepare_audio

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "kin"  # ISO 639-3 code for Kinyarwanda


class ASRError(RuntimeError):
    """Raised when a real ASR backend cannot produce a transcription."""


class BaseASR:
    """Interface every speech-recognition backend must implement."""

    def transcribe(
        self,
        audio: bytes | str,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> str:
        raise NotImplementedError


class MockASR(BaseASR):
    """MOCK backend: intentionally does not understand real audio.

    It accepts plain text so the whole pipeline (diagnosis, dashboard, tests)
    can run without any audio or paid service.
    """

    def transcribe(
        self,
        audio: bytes | str,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> str:
        if isinstance(audio, str):
            return audio.strip()

        # Optional demo hook: set MOCK_ASR_TEXT to pretend the upload said
        # something. Empty means "please repeat".
        return os.getenv("MOCK_ASR_TEXT", "").strip()


def _extract_transcription(payload: object) -> str | None:
    """Read the transcription from Sunbird's JSON, tolerating small changes."""
    if isinstance(payload, str):
        return payload

    if not isinstance(payload, dict):
        return None

    # Current Sunbird response field.
    value = payload.get("audio_transcription")
    if isinstance(value, str):
        return value

    # Compatibility with other/older OpenAI-style response shapes.
    for key in ("text", "transcription", "output", "result"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for nested_key in ("audio_transcription", "text", "transcription"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, str):
                    return nested_value

    return None


class SunbirdASR(BaseASR):
    """Real Kinyarwanda speech recognition via the Sunbird AI API."""

    def __init__(
        self,
        token: str | None = None,
        url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        # Read secrets at call time, never hardcode them, and never log them.
        self.token = (token if token is not None else config.SUNBIRD_API_TOKEN).strip()
        self.url = url or config.SUNBIRD_STT_URL
        self.timeout = timeout or config.SUNBIRD_TIMEOUT_SECONDS

    def transcribe(
        self,
        audio: bytes | str,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> str:
        # Already text (mock/demo or an upstream transcription): no API needed.
        if isinstance(audio, str):
            return audio.strip()

        if not audio:
            return ""

        if not self.token:
            raise ASRError(
                "SUNBIRD_API_TOKEN is not set; add it to .env or use ASR_BACKEND=mock"
            )

        prepared = prepare_audio(audio, filename=filename, content_type=content_type)

        headers = {"Authorization": f"Bearer {self.token}"}
        files = {
            "audio": (prepared.filename, prepared.data, prepared.content_type),
        }
        form = {"language": language}

        try:
            response = requests.post(
                self.url,
                headers=headers,
                files=files,
                data=form,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise ASRError("Sunbird ASR request timed out") from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (401, 403):
                raise ASRError(
                    "Sunbird token is invalid or expired (HTTP "
                    f"{status}); create a fresh token at https://api.sunbird.ai/keys"
                ) from exc
            raise ASRError(f"Sunbird ASR returned HTTP {status}") from exc
        except requests.RequestException as exc:
            raise ASRError("Could not reach the Sunbird ASR API") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ASRError("Sunbird ASR returned invalid JSON") from exc

        text = _extract_transcription(payload)
        if text is None:
            raise ASRError("Sunbird ASR response did not include a transcription")

        return text.strip()


def _selected_backend() -> str:
    return (config.ASR_BACKEND or "mock").strip().lower()


def transcribe(
    audio: bytes | str,
    *,
    filename: str | None = None,
    content_type: str | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> str:
    """Transcribe audio using the configured backend, with safe fallback.

    Returns an empty string when nothing could be transcribed. The voice layer
    should then play/read the polite "please repeat" Kinyarwanda prompt.
    """
    backend = _selected_backend()

    if backend != "sunbird":
        return MockASR().transcribe(
            audio,
            filename=filename,
            content_type=content_type,
            language=language,
        )

    try:
        return SunbirdASR().transcribe(
            audio,
            filename=filename,
            content_type=content_type,
            language=language,
        )
    except ASRError as exc:
        # Clear log for the demo/developers. Never includes the token.
        logger.warning("Sunbird ASR failed: %s. Falling back to mock ASR.", exc)
        return MockASR().transcribe(
            audio,
            filename=filename,
            content_type=content_type,
            language=language,
        )
