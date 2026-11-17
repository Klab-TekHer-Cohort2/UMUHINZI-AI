"""FastAPI application entry point for Umuhinzi AI.

Current endpoints:
- `GET  /health`   service + backend status
- `GET  /pests`    the pest knowledge base (summary)
- `POST /diagnose` text symptom description -> pest + Kinyarwanda reply
- `POST /asr`      audio upload -> Sunbird/mock transcription -> diagnosis
- `POST /register` register a farmer or cooperative (phone is hashed)
- `GET  /alerts`   outbreak alerts (active by default)
- `GET  /reports`  recent (hashed) diagnoses for the dashboard

`/voice` and `/ussd` (Africa's Talking webhooks) are added in the next stages.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import __version__, config
from app.db import storage
from app.i18n import rw
from app.ml.diagnosis import build_reply, diagnose, diagnose_and_reply, list_pests
from app.services import alerts as alert_service
from app.services import asr

logger = logging.getLogger(__name__)

# Keep uploads small; a symptom description should be a few seconds of audio.
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB

# The `title` and `description` show up in the auto-generated docs at /docs.
app = FastAPI(
    title="Umuhinzi AI",
    description="Voice-first agricultural assistant for smallholder farmers in Rwanda.",
    version=__version__,
)


class DiagnoseRequest(BaseModel):
    """Body for `POST /diagnose`."""

    text: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="Farmer's symptom description in Kinyarwanda or English.",
        examples=["amababi y'ibigori arashye kandi afite uduhumbi"],
    )
    sector: str | None = Field(
        None,
        max_length=100,
        description="Sector where the farmer's field is located (for outbreak tracking).",
        examples=["Kacyiru"],
    )
    district: str | None = Field(
        None,
        max_length=100,
        description="District where the farmer's field is located.",
        examples=["Gasabo"],
    )
    phone: str | None = Field(
        None,
        max_length=32,
        description="Optional phone number. It is hashed and never stored raw.",
    )
    session_id: str | None = Field(
        None,
        max_length=128,
        description="Optional session id. It is hashed and never stored raw.",
    )


class RegisterRequest(BaseModel):
    """Body for `POST /register` (farmers and cooperatives)."""

    role: Literal["farmer", "cooperative"]
    name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(
        ...,
        min_length=5,
        max_length=32,
        description="Contact phone. It is hashed and never stored raw.",
    )
    sector: str = Field(..., min_length=2, max_length=100)
    district: str = Field(..., min_length=2, max_length=100)


@app.get("/")
def root() -> dict:
    """Tiny landing payload so a browser check shows the service is alive."""
    return {
        "service": "Umuhinzi AI",
        "version": __version__,
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict:
    """Health check used by the demo and by tunnels (ngrok/cloudflared)."""
    return {
        "status": "ok",
        "africastalking_configured": config.africastalking_is_configured(),
        "asr_backend": config.ASR_BACKEND,
        # Boolean only - the Sunbird token itself is never returned.
        "sunbird_configured": config.sunbird_is_configured(),
    }


@app.get("/pests")
def pests() -> dict:
    """Return the pests the system knows about (for the dashboard/debugging)."""
    return {"count": len(list_pests()), "pests": list_pests()}


@app.post("/diagnose")
def diagnose_text(request: DiagnoseRequest) -> dict:
    """Diagnose a text description of crop symptoms.

    Every result is stored with a hashed phone/session id (never the raw
    number). When a pest crosses the outbreak threshold in a sector, a
    Kinyarwanda alert is stored and logged in dry-run mode.
    """
    result = diagnose(request.text)
    reporter_hash = storage.hash_identifier(request.phone or request.session_id)

    storage.save_diagnosis(
        reporter_hash=reporter_hash,
        pest_id=result.pest_id,
        sector=request.sector,
        district=request.district,
    )

    outbreak_alert = alert_service.check_outbreak(
        result.pest_id,
        request.sector,
        request.district,
        pest_name_rw=result.name_rw,
    )

    return {
        "input": request.text,
        "diagnosis": result.to_dict(),
        "reply_rw": build_reply(result),
        "saved": True,
        "outbreak_alert": outbreak_alert,
    }


@app.post("/register", status_code=201)
def register(request: RegisterRequest) -> dict:
    """Register a farmer or cooperative without storing the raw phone number."""
    phone_hash = storage.hash_identifier(request.phone)
    registration_id = storage.save_registration(
        role=request.role,
        name=request.name,
        phone_hash=phone_hash,
        sector=request.sector,
        district=request.district,
    )
    return {
        "id": registration_id,
        "role": request.role,
        "name": request.name,
        "sector": request.sector,
        "district": request.district,
        "registered": True,
    }


@app.get("/alerts")
def get_alerts(active_only: bool = True, limit: int = 50) -> dict:
    """Return outbreak alerts, active ones by default (dry-run, no SMS sent)."""
    items = storage.list_alerts(active_only=active_only, limit=limit)
    return {"count": len(items), "alerts": items}


@app.get("/reports")
def recent_reports(limit: int = 20) -> dict:
    """Return recent diagnoses for the dashboard (hashed reporter ids only)."""
    reports = storage.list_recent_diagnoses(limit=limit)
    return {"count": len(reports), "reports": reports}


@app.post("/asr")
def transcribe_audio(audio: UploadFile = File(...)) -> dict:
    """Transcribe an uploaded recording and diagnose the result.

    This is the bridge used by the dashboard and by the future `/voice`
    callback. If speech recognition returns nothing, we return a polite
    Kinyarwanda prompt asking the farmer to repeat.

    A regular `def` endpoint (not `async def`) lets FastAPI run the blocking
    Sunbird/ffmpeg work in a worker thread so other calls are not blocked.
    """
    raw_audio = audio.file.read()

    if not raw_audio:
        raise HTTPException(status_code=400, detail="Empty audio upload")

    if len(raw_audio) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio file too large (maximum {MAX_AUDIO_BYTES // (1024 * 1024)} MB)",
        )

    try:
        text = asr.transcribe(
            raw_audio,
            filename=audio.filename,
            content_type=audio.content_type,
        )
    except Exception as exc:  # keep a live call alive even on unexpected errors
        logger.warning("Unexpected ASR failure: %s", exc)
        text = ""

    if not text:
        return {
            "transcription": "",
            "diagnosis": None,
            "reply_rw": rw.ASR_REPEAT_REPLY,
        }

    return {"transcription": text, **diagnose_and_reply(text)}
