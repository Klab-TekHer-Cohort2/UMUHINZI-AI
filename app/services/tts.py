"""Text-to-speech behind a small `synthesize(text)` abstraction.

Backends are selected with `TTS_BACKEND` in `.env`:

- `mock` (default) - no network and no audio. It returns empty bytes so the
  dashboard hides the player and `/voice` falls back to `<Say>`. This keeps the
  whole demo usable without API keys.
- `sunbird` - calls Sunbird AI's Kinyarwanda TTS endpoint
  (`POST /tasks/audio/speech`, `language=kin`, `response_mode=stream`) using the
  existing `SUNBIRD_API_TOKEN`. If Sunbird returns a signed `audio_url` instead
  of raw bytes, we download it. On any error we log a clear warning (never the
  token or the signed URL) and fall back to mock, i.e. no audio.

Synthesized audio is cached briefly in memory so `/voice` can expose a stable
`<Play url="...">` URL to Africa's Talking.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

import requests

from app import config

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "kin"  # ISO 639-3 code for Kinyarwanda
MAX_TTS_BYTES = 10 * 1024 * 1024
CACHE_TTL_SECONDS = 3600
CACHE_MAX_ITEMS = 128


class TTSError(RuntimeError):
    """Raised when the real TTS backend cannot produce audio."""


@dataclass(frozen=True)
class SynthesizedAudio:
    """Audio bytes and their MIME type (empty data = no audio available)."""

    data: bytes = b""
    content_type: str = "audio/wav"


class BaseTTS:
    """Interface every text-to-speech backend must implement."""

    def synthesize(
        self, text: str, *, language: str = DEFAULT_LANGUAGE
    ) -> SynthesizedAudio:
        raise NotImplementedError


class MockTTS(BaseTTS):
    """Safe fallback: never calls the network and never returns fake audio."""

    def synthesize(
        self, text: str, *, language: str = DEFAULT_LANGUAGE
    ) -> SynthesizedAudio:
        return SynthesizedAudio()


def _extract_audio_url(payload: object) -> str | None:
    """Read a signed audio URL from the different Sunbird response shapes."""
    if not isinstance(payload, dict):
        return None

    candidates = [
        payload.get("audio_url"),
        payload.get("url"),
        payload.get("output"),
        payload.get("data"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, dict):
            for key in ("audio_url", "url", "output"):
                nested = candidate.get(key)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return None


def _absolute_url(url: str) -> str:
    """Sunbird sometimes returns a host without the scheme."""
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


class SunbirdTTS(BaseTTS):
    """Real Kinyarwanda speech synthesis via the Sunbird AI API."""

    def __init__(
        self,
        token: str | None = None,
        url: str | None = None,
        timeout: int | None = None,
        voice: str | None = None,
    ) -> None:
        # Read secrets at call time; never hardcode or log them.
        self.token = (token if token is not None else config.SUNBIRD_API_TOKEN).strip()
        self.url = url or config.SUNBIRD_TTS_URL
        self.timeout = timeout or config.SUNBIRD_TIMEOUT_SECONDS
        self.voice = (voice if voice is not None else config.SUNBIRD_TTS_VOICE).strip()

    def synthesize(
        self, text: str, *, language: str = DEFAULT_LANGUAGE
    ) -> SynthesizedAudio:
        if not text.strip():
            return SynthesizedAudio()
        if not self.token:
            raise TTSError(
                "SUNBIRD_API_TOKEN is not set; add it to .env or use TTS_BACKEND=mock"
            )

        payload: dict[str, str] = {
            "text": text,
            "language": language,
            "response_mode": "stream",
        }
        if self.voice:
            payload["voice"] = self.voice

        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.post(
                self.url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise TTSError("Sunbird TTS request timed out") from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (401, 403):
                raise TTSError(
                    "Sunbird token is invalid or expired (HTTP "
                    f"{status}); create a fresh token at https://api.sunbird.ai/keys"
                ) from exc
            raise TTSError(f"Sunbird TTS returned HTTP {status}") from exc
        except requests.RequestException as exc:
            raise TTSError("Could not reach the Sunbird TTS API") from exc

        content_type = (
            response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        )
        looks_like_json = "json" in content_type or response.content.lstrip()[:1] in (
            b"{",
            b"[",
        )

        if looks_like_json:
            try:
                body = response.json()
            except ValueError as exc:
                raise TTSError("Sunbird TTS returned invalid JSON") from exc

            audio_url = _extract_audio_url(body)
            if not audio_url:
                raise TTSError("Sunbird TTS response did not include audio")
            try:
                download = requests.get(
                    _absolute_url(audio_url), timeout=self.timeout
                )
                download.raise_for_status()
            except requests.RequestException as exc:
                raise TTSError("Could not download Sunbird TTS audio") from exc
            data = download.content
            content_type = (
                download.headers.get("Content-Type", "").split(";")[0].strip()
                or "audio/wav"
            )
        else:
            data = response.content

        if not data:
            raise TTSError("Sunbird TTS returned empty audio")
        if len(data) > MAX_TTS_BYTES:
            raise TTSError("Sunbird TTS audio is too large")
        return SynthesizedAudio(data=data, content_type=content_type or "audio/wav")


def synthesize(
    text: str, *, language: str = DEFAULT_LANGUAGE
) -> SynthesizedAudio:
    """Synthesize speech with the configured backend and a safe mock fallback."""
    backend = (config.TTS_BACKEND or "mock").strip().lower()

    if backend != "sunbird":
        return MockTTS().synthesize(text, language=language)

    try:
        return SunbirdTTS().synthesize(text, language=language)
    except TTSError as exc:
        logger.warning("Sunbird TTS failed: %s. Falling back to mock (no audio).", exc)
        return MockTTS().synthesize(text, language=language)


@dataclass(frozen=True)
class CachedAudio:
    data: bytes
    content_type: str
    expires_at: float


_audio_cache: dict[str, CachedAudio] = {}


def cache_audio(text: str, audio: SynthesizedAudio) -> str:
    """Cache audio under a hash of the text and return its public key."""
    if not audio.data:
        return ""

    now = time.time()
    for key, item in list(_audio_cache.items()):
        if item.expires_at <= now:
            _audio_cache.pop(key, None)

    key = hashlib.sha256(f"{audio.content_type}:{text}".encode("utf-8")).hexdigest()
    _audio_cache[key] = CachedAudio(
        data=audio.data,
        content_type=audio.content_type,
        expires_at=now + CACHE_TTL_SECONDS,
    )
    while len(_audio_cache) > CACHE_MAX_ITEMS:
        _audio_cache.pop(next(iter(_audio_cache)))
    return key


def get_cached_audio(key: str) -> CachedAudio | None:
    item = _audio_cache.get(key)
    if item is None:
        return None
    if item.expires_at <= time.time():
        _audio_cache.pop(key, None)
        return None
    return item


def clear_cache() -> None:
    """Useful for tests and a clean demo restart."""
    _audio_cache.clear()
