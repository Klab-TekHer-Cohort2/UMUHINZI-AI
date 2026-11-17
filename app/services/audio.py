"""Best-effort audio preparation before sending to Sunbird.

Phone recordings from Africa's Talking are usually WAV or MP3, which Sunbird
accepts directly. Other formats (for example AMR from some phones) are converted
to mono 16 kHz WAV with **ffmpeg** when it is installed.

ffmpeg is optional for the demo: if it is missing, the original bytes are sent
unchanged and a warning is logged. See the README for the free ffmpeg install.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Formats Sunbird documents as supported.
SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".ogg", ".m4a", ".aac", ".flac", ".webm"}

CONTENT_TYPE_BY_EXTENSION = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
    ".amr": "audio/amr",
}

EXTENSION_BY_CONTENT_TYPE = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/webm": ".webm",
    "audio/amr": ".amr",
}


@dataclass(frozen=True)
class PreparedAudio:
    """Audio bytes plus the filename/content-type to send to Sunbird."""

    data: bytes
    filename: str
    content_type: str
    converted: bool = False


def _guess_extension(filename: str | None, content_type: str | None) -> str:
    """Work out a file extension from the upload metadata."""
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix:
            return suffix

    if content_type:
        # Ignore parameters such as "; codecs=..." if a client sends them.
        base_type = content_type.split(";", 1)[0].strip().lower()
        if base_type in EXTENSION_BY_CONTENT_TYPE:
            return EXTENSION_BY_CONTENT_TYPE[base_type]

    # Africa's Talking usually sends WAV; this is only a last resort.
    return ".wav"


def _convert_to_wav(data: bytes, source_extension: str) -> bytes | None:
    """Convert arbitrary audio to mono 16 kHz WAV using ffmpeg, if available."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning(
            "ffmpeg is not installed; cannot convert %s audio. "
            "Sending the original file to Sunbird.",
            source_extension,
        )
        return None

    with tempfile.TemporaryDirectory() as tmp_dir:
        source = Path(tmp_dir) / f"input{source_extension}"
        target = Path(tmp_dir) / "output.wav"
        source.write_bytes(data)

        command = [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(target),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=60)
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("ffmpeg could not convert the audio: %s", exc)
            return None

        if not target.exists():
            logger.warning("ffmpeg did not produce an output file.")
            return None

        return target.read_bytes()


def prepare_audio(
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> PreparedAudio:
    """Return audio that Sunbird can accept, converting only when necessary."""
    extension = _guess_extension(filename, content_type)

    if extension in SUPPORTED_EXTENSIONS:
        return PreparedAudio(
            data=data,
            filename=f"audio{extension}",
            content_type=CONTENT_TYPE_BY_EXTENSION.get(
                extension, content_type or "application/octet-stream"
            ),
        )

    logger.info("Audio format %s is not directly supported; trying ffmpeg.", extension)
    converted = _convert_to_wav(data, extension)
    if converted is not None:
        return PreparedAudio(
            data=converted,
            filename="audio.wav",
            content_type="audio/wav",
            converted=True,
        )

    # Last resort: send the original file and let Sunbird validate it. If it
    # fails, the ASR layer falls back to mock / asks the farmer to repeat.
    return PreparedAudio(
        data=data,
        filename=f"audio{extension}",
        content_type=content_type or "application/octet-stream",
    )
