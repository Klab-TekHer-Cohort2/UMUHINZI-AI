"""Speech recognition behind a small `transcribe(audio)` abstraction.

Backends are selected with `ASR_BACKEND` in `.env`:

- `mock` (default) - no network calls. If `audio` is a string it is returned
  as-is (handy for tests/demos). For real audio bytes it returns
  `MOCK_ASR_TEXT` if set, otherwise an empty string so the voice layer asks the
  farmer to repeat.
- `sunbird` - calls Sunbird AI's free speech-to-text API with Kinyarwanda
  (`language=kin`). On any error it logs a warning and falls back to mock.
- `nvidia` - runs NVIDIA's Kinyarwanda Conformer RNN-T model with NeMo. Audio is
  converted to mono 16 kHz WAV first; NeMo is imported lazily and the model is
  cached after the first load. On any error it falls back to `ASR_FALLBACK`
  (`sunbird` by default), then to mock if that also fails.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import tempfile
import threading
from pathlib import Path

import requests

from app import config
from app.services.audio import prepare_audio, prepare_wav_16k_mono

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "kin"  # ISO 639-3 code for Kinyarwanda
DEFAULT_NVIDIA_ASR_MODEL = config.DEFAULT_NVIDIA_ASR_MODEL

_NEMO_MODEL: object | None = None
_NEMO_MODEL_NAME: str | None = None
_NEMO_MODEL_LOCK = threading.Lock()


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


def nemo_is_available() -> bool:
    """Check for NeMo without importing it or loading any model."""
    try:
        return importlib.util.find_spec("nemo") is not None
    except (ImportError, ValueError):
        return False


def _load_nemo_model(model_name: str | None = None) -> object:
    global _NEMO_MODEL, _NEMO_MODEL_NAME

    name = (model_name or config.NVIDIA_ASR_MODEL or DEFAULT_NVIDIA_ASR_MODEL).strip()
    with _NEMO_MODEL_LOCK:
        if _NEMO_MODEL is not None and _NEMO_MODEL_NAME == name:
            return _NEMO_MODEL

        if not nemo_is_available():
            raise ASRError("NeMo is not installed; install -r requirements-nvidia.txt")

        try:
            from nemo.collections.asr.models import EncDecRNNTBPEModel
        except ImportError as exc:
            raise ASRError(
                "NeMo is not installed; install -r requirements-nvidia.txt"
            ) from exc

        try:
            model = EncDecRNNTBPEModel.from_pretrained(name)
        except Exception as exc:
            raise ASRError(f"Could not load NeMo model {name}") from exc

        _NEMO_MODEL = model
        _NEMO_MODEL_NAME = name
        return model


def _extract_nemo_transcription(payload: object) -> str | None:
    if isinstance(payload, (list, tuple)):
        for item in payload:
            text = _extract_transcription(item)
            if text is not None and text.strip():
                return text
        return None

    text = _extract_transcription(payload)
    return text if text is not None and text.strip() else None


class NvidiaASR(BaseASR):
    """Local Kinyarwanda speech recognition with NVIDIA NeMo."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = (
            model_name or config.NVIDIA_ASR_MODEL or DEFAULT_NVIDIA_ASR_MODEL
        ).strip()

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

        if not audio:
            return ""

        try:
            prepared = prepare_wav_16k_mono(
                audio, filename=filename, content_type=content_type
            )
        except Exception as exc:
            raise ASRError(f"Could not prepare audio for NeMo: {exc}") from exc

        model = _load_nemo_model(self.model_name)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
            temp_audio.write(prepared.data)
            audio_path = temp_audio.name

        try:
            transcribe = getattr(model, "transcribe")
            result = transcribe(paths2audio_files=[audio_path])
        except Exception as exc:
            raise ASRError(f"NeMo ASR failed: {exc}") from exc
        finally:
            Path(audio_path).unlink(missing_ok=True)

        text = _extract_nemo_transcription(result)
        if text is None:
            raise ASRError("NeMo ASR response did not include a transcription")

        return text.strip()


def _fallback_backend_name() -> str:
    name = (config.ASR_FALLBACK or "sunbird").strip().lower()
    return name if name in {"mock", "sunbird"} else "mock"


def _fallback_asr(name: str) -> BaseASR:
    return SunbirdASR() if name == "sunbird" else MockASR()


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

    if backend == "nvidia":
        fallback_name = _fallback_backend_name()
        try:
            return NvidiaASR().transcribe(
                audio,
                filename=filename,
                content_type=content_type,
                language=language,
            )
        except Exception as exc:
            logger.warning(
                "NVIDIA ASR failed: %s. Falling back to %s ASR.",
                exc,
                fallback_name,
            )
            try:
                return _fallback_asr(fallback_name).transcribe(
                    audio,
                    filename=filename,
                    content_type=content_type,
                    language=language,
                )
            except Exception as fallback_exc:
                logger.warning(
                    "%s ASR fallback failed: %s. Falling back to mock ASR.",
                    fallback_name.capitalize(),
                    fallback_exc,
                )
                return MockASR().transcribe(
                    audio,
                    filename=filename,
                    content_type=content_type,
                    language=language,
                )

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
