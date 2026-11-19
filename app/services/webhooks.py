"""Shared helpers for the Africa's Talking USSD and voice webhooks.

Both channels are stateless HTTP callbacks: the farmer's progress is kept in a
small in-memory session map keyed by a *hashed* session id (never a raw phone
number). Reports, alerts and replies all go through the same diagnosis and
outbreak services used by the JSON API and the dashboard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.db import storage
from app.i18n import rw
from app.ml import diagnosis
from app.services import alerts as alert_service

logger = logging.getLogger(__name__)

# Demo location lists. "4" lets a farmer type a district/sector name instead.
DISTRICTS = {"1": "Gasabo", "2": "Kicukiro", "3": "Nyarugenge"}
SECTORS = {"1": "Kacyiru", "2": "Remera", "3": "Kimihurura"}

# value -> (text sent to the existing diagnosis, short menu label)
SYMPTOMS = {
    "1": ("amababi y'ibigori arashye kandi afite uduhumbi", "Amababi arashye"),
    "2": ("inyo mu giti cy'ibigori", "Inyo mu giti"),
    "3": ("imyumbati ifite amababi y'umuhondo n'agoretse", "Imyumbati"),
    "4": ("isazi y'ibishyimbo, amababi y'umuhondo", "Isazi y'ibishyimbo"),
    "5": ("ibitoke biraba kandi bifite umutobe wera", "Ibitoke biraba"),
    "6": ("ibirayi bifite ibibara byirabura ku mababi", "Ibirayi"),
}

# Short Kinyarwanda labels for the six pests; order matches PESTS below.
PEST_LABELS = {
    "fall_armyworm": "Inyo y'ibigori",
    "maize_stalk_borer": "Inyo y'umushyitsi",
    "cassava_mosaic": "Mosaic y'imyumbati",
    "bean_fly": "Isazi y'ibishyimbo",
    "banana_bacterial_wilt": "Indwara y'igitoke",
    "potato_late_blight": "Indwara y'ibirayi",
}

# Menu digit -> pest id, derived from the knowledge base so it stays in sync.
PESTS = {
    str(index): pest["id"]
    for index, pest in enumerate(diagnosis.list_pests(), start=1)
}


@dataclass
class SessionState:
    """State carried across USSD/voice callbacks for one hashed session."""

    stage: str = "start"
    depth: int = 0
    language: str = "rw"
    district: str | None = None
    sector: str | None = None
    pending: str | None = None


_sessions: dict[str, SessionState] = {}


def hashed_key(session_id: str | None, phone_number: str | None) -> str:
    """Return a non-reversible session key; never expose raw identifiers."""
    return (
        storage.hash_identifier(session_id)
        or storage.hash_identifier(phone_number)
        or "anonymous"
    )


def reporter_hash(phone_number: str | None, session_key: str) -> str:
    """Hash the caller's phone number for a report; fall back to session hash."""
    return storage.hash_identifier(phone_number) or session_key


def get_session(key: str) -> SessionState:
    return _sessions.setdefault(key, SessionState())


def reset_session(key: str) -> SessionState:
    _sessions[key] = SessionState()
    return _sessions[key]


def clear_session(key: str) -> None:
    _sessions.pop(key, None)


def clear_all_sessions() -> None:
    """Mainly useful for tests and for a clean demo restart."""
    _sessions.clear()


def fit(prefix: str, body: str, limit: int = 182) -> str:
    """Keep a USSD reply within Africa's Talking's 182-character limit."""
    available = max(0, limit - len(prefix))
    text = " ".join(body.split())
    if len(text) <= available:
        return prefix + text
    if available < 4:
        return prefix + text[:available]

    cut = text[: available - 3].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return prefix + cut + "..."


def process_report(
    *,
    text: str | None,
    sector: str | None,
    district: str | None,
    reporter_hash: str | None,
    pest_id: str | None = None,
) -> tuple[diagnosis.DiagnosisResult, dict | None]:
    """Run diagnosis, persist it with a hashed reporter, and check for an outbreak."""
    result = (
        diagnosis.result_for_pest(pest_id) if pest_id else diagnosis.diagnose(text or "")
    )

    storage.save_diagnosis(
        reporter_hash=reporter_hash,
        pest_id=result.pest_id,
        sector=sector,
        district=district,
    )
    alert = alert_service.check_outbreak(
        result.pest_id,
        sector,
        district,
        pest_name_rw=result.name_rw,
    )
    logger.debug("Report saved: pest=%s sector=%s", result.pest_id, sector)
    return result, alert


def advice_text(
    result: diagnosis.DiagnosisResult, alert: dict | None = None
) -> str:
    """Short Kinyarwanda advice used by both webhooks."""
    text = diagnosis.build_short_reply(result)
    if alert is not None and alert.get("created"):
        text += rw.OUTBREAK_NOTICE
    return text


def alerts_for_sector(sector: str | None) -> list[dict]:
    cleaned = (sector or "").strip()
    if not cleaned:
        return []
    return [
        alert
        for alert in storage.list_alerts(active_only=True)
        if (alert.get("sector") or "").casefold() == cleaned.casefold()
    ]


def alert_summary(sector: str | None) -> str:
    alerts = alerts_for_sector(sector)
    if not alerts:
        return rw.USSD_ALERT_NONE
    return rw.USSD_ALERT.format(
        sector=sector or "",
        message=alerts[0].get("message_rw") or "",
    )
