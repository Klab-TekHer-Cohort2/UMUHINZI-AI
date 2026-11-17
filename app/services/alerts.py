"""Outbreak early warning (dry-run only).

Rule: the same pest reported at least `OUTBREAK_THRESHOLD` times in the same
sector within `OUTBREAK_WINDOW_DAYS` is marked as an outbreak. The Kinyarwanda
alert is logged and stored in SQLite; no real SMS is sent in this stage.
"""

from __future__ import annotations

import logging

from app import config
from app.db import storage
from app.i18n import rw

logger = logging.getLogger(__name__)


def _pest_name_rw(pest_id: str) -> str:
    from app.ml.diagnosis import get_pest

    try:
        return str(get_pest(pest_id)["name_rw"])
    except KeyError:
        return pest_id


def check_outbreak(
    pest_id: str | None,
    sector: str | None,
    district: str | None = None,
    pest_name_rw: str | None = None,
) -> dict | None:
    """Return an existing/new alert, or None when the threshold is not met."""
    sector = (sector or "").strip()
    if not pest_id or not sector:
        return None

    report_count = storage.count_recent_reports(
        pest_id, sector, config.OUTBREAK_WINDOW_DAYS
    )
    if report_count < config.OUTBREAK_THRESHOLD:
        return None

    existing = storage.find_active_alert(
        pest_id, sector, config.OUTBREAK_WINDOW_DAYS
    )
    if existing is not None:
        return {**existing, "created": False}

    message_rw = rw.OUTBREAK_ALERT.format(
        pest=pest_name_rw or _pest_name_rw(pest_id),
        sector=sector,
        count=report_count,
        days=config.OUTBREAK_WINDOW_DAYS,
    )

    alert_id = storage.save_alert(
        pest_id=pest_id,
        sector=sector,
        district=district,
        report_count=report_count,
        threshold=config.OUTBREAK_THRESHOLD,
        window_days=config.OUTBREAK_WINDOW_DAYS,
        message_rw=message_rw,
    )

    logger.warning(
        "DRY-RUN outbreak alert id=%s pest=%s sector=%s reports=%s "
        "(stored, no SMS sent): %s",
        alert_id,
        pest_id,
        sector,
        report_count,
        message_rw,
    )

    return {
        "id": alert_id,
        "pest_id": pest_id,
        "sector": sector,
        "district": district,
        "report_count": report_count,
        "threshold": config.OUTBREAK_THRESHOLD,
        "window_days": config.OUTBREAK_WINDOW_DAYS,
        "message_rw": message_rw,
        "status": "active",
        "created": True,
    }
