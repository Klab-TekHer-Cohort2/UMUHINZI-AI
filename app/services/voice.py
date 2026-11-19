"""Africa's Talking voice webhook handler.

The endpoint returns voice XML for each callback. A call flows through:
greeting + GetDigits menu -> district -> sector -> chosen action. For symptom
descriptions we use Record; Africa's Talking posts the recording URL back here,
we download it, run the existing `asr.transcribe()` step and diagnose the text.
No phone number or audio is logged, and no API key is needed in dry-run mode.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from xml.etree import ElementTree as ET

import requests

from app.i18n import rw
from app.services import asr, tts, webhooks

logger = logging.getLogger(__name__)

MAX_RECORDING_BYTES = 10 * 1024 * 1024
RECORDING_TIMEOUT_SECONDS = 15


def _say(text: str) -> ET.Element:
    element = ET.Element("Say")
    element.text = text
    return element


def _get_digits(prompt: str, action: str) -> ET.Element:
    element = ET.Element(
        "GetDigits",
        {
            "action": action,
            "method": "POST",
            "timeout": "10",
            "finishOnKey": "#",
            "numDigits": "1",
        },
    )
    element.append(_say(prompt))
    return element


def _record(action: str) -> ET.Element:
    return ET.Element(
        "Record",
        {
            "action": action,
            "method": "POST",
            "maxLength": "30",
            "finishOnKey": "#",
        },
    )


def _hangup() -> ET.Element:
    return ET.Element("Hangup")


def _base_url(callback_url: str) -> str:
    parts = urlparse(callback_url)
    return urlunparse((parts.scheme, parts.netloc, "", "", "", ""))


def _speak(text: str, callback_url: str) -> list[ET.Element]:
    """Return `<Play>` with generated audio, or `<Say>` when audio is unavailable."""
    try:
        audio = tts.synthesize(text)
        if audio.data:
            key = tts.cache_audio(text, audio)
            url = f"{_base_url(callback_url)}/tts/audio/{key}"
            return [ET.Element("Play", {"url": url})]
    except Exception as exc:
        logger.warning("TTS unavailable (%s); falling back to Say", type(exc).__name__)
    return [_say(text)]


def _response(children: list[ET.Element]) -> str:
    root = ET.Element("Response")
    root.extend(children)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )


def download_recording(url: str) -> tuple[bytes, str, str]:
    """Fetch a recording and return (audio, filename, content_type)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Invalid recording URL")

    response = requests.get(url, timeout=RECORDING_TIMEOUT_SECONDS)
    response.raise_for_status()
    audio = response.content
    if not audio:
        raise ValueError("Empty recording")
    if len(audio) > MAX_RECORDING_BYTES:
        raise ValueError("Recording too large")

    suffix = Path(parsed.path).suffix or ".wav"
    content_type = (
        response.headers.get("Content-Type", "").split(";")[0].strip() or "audio/wav"
    )
    return audio, f"recording{suffix}", content_type


def _finish(
    *,
    text: str | None,
    pest_id: str | None,
    state: webhooks.SessionState,
    session_key: str,
    caller_number: str | None,
    callback_url: str,
) -> str:
    result, alert = webhooks.process_report(
        text=text,
        sector=state.sector,
        district=state.district,
        reporter_hash=webhooks.reporter_hash(caller_number, session_key),
        pest_id=pest_id,
    )
    webhooks.clear_session(session_key)
    reply = f"{webhooks.advice_text(result, alert)} {rw.VOICE_GOODBYE}"
    return _response([*_speak(reply, callback_url), _hangup()])


def _handle_recording(
    recording_url: str,
    *,
    state: webhooks.SessionState,
    session_key: str,
    caller_number: str | None,
    callback_url: str,
) -> str:
    try:
        audio, filename, content_type = download_recording(recording_url)
    except Exception as exc:
        logger.warning("Could not fetch recording (%s)", type(exc).__name__)
        return _response([*_speak(rw.VOICE_REPEAT, callback_url), _record(callback_url)])

    try:
        text = asr.transcribe(audio, filename=filename, content_type=content_type)
    except Exception as exc:
        logger.warning("Unexpected ASR failure (%s)", type(exc).__name__)
        text = ""

    if not text:
        return _response([*_speak(rw.VOICE_REPEAT, callback_url), _record(callback_url)])

    return _finish(
        text=text,
        pest_id=None,
        state=state,
        session_key=session_key,
        caller_number=caller_number,
        callback_url=callback_url,
    )


def _after_location(
    state: webhooks.SessionState, *, session_key: str, caller_number: str | None,
    callback_url: str,
) -> str:
    if state.pending == "1":
        state.stage = "record"
        return _response([*_speak(rw.VOICE_RECORD, callback_url), _record(callback_url)])

    if state.pending == "2":
        state.stage = "pest"
        return _response(
            [_say(rw.VOICE_PESTS), _get_digits(rw.VOICE_PESTS, callback_url)]
        )

    if state.pending == "3":
        reply = f"{webhooks.alert_summary(state.sector)} {rw.VOICE_GOODBYE}"
        webhooks.clear_session(session_key)
        return _response([*_speak(reply, callback_url), _hangup()])

    state.stage = "menu"
    return _response([_say(rw.VOICE_MENU), _get_digits(rw.VOICE_MENU, callback_url)])


def handle(
    *,
    session_id: str | None,
    caller_number: str | None,
    is_active: str | None,
    dtmf_digits: str | None,
    recording_url: str | None,
    callback_url: str,
) -> str:
    """Return voice XML for one Africa's Talking callback."""
    session_key = webhooks.hashed_key(session_id, caller_number)
    state = webhooks.get_session(session_key)
    dtmf = (dtmf_digits or "").strip()
    recording = (recording_url or "").strip()

    if (is_active or "").strip().lower() in {"0", "false", "no"}:
        webhooks.clear_session(session_key)
        return _response([])

    if recording:
        return _handle_recording(
            recording,
            state=state,
            session_key=session_key,
            caller_number=caller_number,
            callback_url=callback_url,
        )

    if state.stage == "start":
        state = webhooks.reset_session(session_key)
        state.stage = "menu"
        return _response(
            [
                *_speak(rw.VOICE_WELCOME, callback_url),
                _say(rw.VOICE_MENU),
                _get_digits(rw.VOICE_MENU, callback_url),
            ]
        )

    if state.stage == "menu":
        if dtmf in {"1", "2", "3"}:
            state.pending = dtmf
            state.stage = "district"
            return _response(
                [_say(rw.VOICE_DISTRICT), _get_digits(rw.VOICE_DISTRICT, callback_url)]
            )
        return _response([_say(rw.VOICE_MENU), _get_digits(rw.VOICE_MENU, callback_url)])

    if state.stage == "district":
        if dtmf in webhooks.DISTRICTS:
            state.district = webhooks.DISTRICTS[dtmf]
            state.stage = "sector"
            return _response(
                [_say(rw.VOICE_SECTOR), _get_digits(rw.VOICE_SECTOR, callback_url)]
            )
        return _response(
            [_say(rw.VOICE_DISTRICT), _get_digits(rw.VOICE_DISTRICT, callback_url)]
        )

    if state.stage == "sector":
        if dtmf in webhooks.SECTORS:
            state.sector = webhooks.SECTORS[dtmf]
            return _after_location(
                state,
                session_key=session_key,
                caller_number=caller_number,
                callback_url=callback_url,
            )
        return _response(
            [_say(rw.VOICE_SECTOR), _get_digits(rw.VOICE_SECTOR, callback_url)]
        )

    if state.stage == "pest":
        pest_id = webhooks.PESTS.get(dtmf)
        if pest_id:
            return _finish(
                text=None,
                pest_id=pest_id,
                state=state,
                session_key=session_key,
                caller_number=caller_number,
                callback_url=callback_url,
            )
        return _response(
            [_say(rw.VOICE_PESTS), _get_digits(rw.VOICE_PESTS, callback_url)]
        )

    # stage == "record": waiting for the recording callback.
    return _response([*_speak(rw.VOICE_RECORD, callback_url), _record(callback_url)])
