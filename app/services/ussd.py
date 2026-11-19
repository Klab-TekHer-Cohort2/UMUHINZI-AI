"""Africa's Talking USSD webhook handler.

Africa's Talking POSTs the whole menu path in `text` (for example
`1*1*1*1*2`), so the session store only needs to remember where in the menu we
are and which district/sector the farmer picked. Every reply starts with `CON `
(keep the session open) or `END ` (finish), and is at most 182 characters.
"""

from __future__ import annotations

from app.i18n import rw
from app.services import webhooks

MAX_USSD_CHARS = 182


def _clean(value: str | None, max_length: int = 100) -> str:
    return " ".join((value or "").split())[:max_length]


def _value(parts: list[str], depth: int) -> str:
    return parts[depth] if depth < len(parts) else ""


def _tail(parts: list[str], depth: int) -> str:
    # Free text is one USSD field; later "*" segments belong to later steps.
    return _clean(parts[depth] if depth < len(parts) else "")


def _reply(prefix: str, body: str) -> str:
    return webhooks.fit(prefix, body, MAX_USSD_CHARS)


def _reporter_hash(phone_number: str | None, session_key: str) -> str:
    # Prefer the hashed phone number; fall back to the already-hashed session id.
    return webhooks.reporter_hash(phone_number, session_key)


def _finish_report(
    *,
    state: webhooks.SessionState,
    session_key: str,
    phone_number: str | None,
    text: str | None = None,
    pest_id: str | None = None,
) -> str:
    result, alert = webhooks.process_report(
        text=text,
        sector=state.sector,
        district=state.district,
        reporter_hash=_reporter_hash(phone_number, session_key),
        pest_id=pest_id,
    )
    reply = webhooks.advice_text(result, alert)
    webhooks.clear_session(session_key)
    return _reply("END ", reply)


def handle(session_id: str | None, phone_number: str | None, text: str | None) -> str:
    """Return the next USSD screen for one Africa's Talking callback."""
    session_key = webhooks.hashed_key(session_id, phone_number)
    parts = [part.strip() for part in (text or "").split("*") if part.strip()]

    state = webhooks.get_session(session_key)
    if not parts:
        state = webhooks.reset_session(session_key)
    elif state.stage == "start":
        state.stage = "language"

    choice = _value(parts, state.depth)

    if state.stage == "language":
        if choice in {"1", "2"}:
            state.language = "rw" if choice == "1" else "en"
            state.depth += 1
            state.stage = "district"
            body = rw.USSD_DISTRICT
            if state.language == "en":
                body = f"{rw.LANGUAGE_EN_NOTICE} {body}"
            return _reply("CON ", body)
        return _reply("CON ", rw.USSD_WELCOME)

    if state.stage == "district":
        if choice in webhooks.DISTRICTS:
            state.district = webhooks.DISTRICTS[choice]
            state.depth += 1
            state.stage = "sector"
            return _reply("CON ", rw.USSD_SECTOR)
        if choice == "4":
            state.depth += 1
            state.stage = "district_other"
            return _reply("CON ", rw.USSD_DISTRICT_OTHER)
        return _reply("CON ", rw.USSD_DISTRICT)

    if state.stage == "district_other":
        district = _tail(parts, state.depth)
        if not district:
            return _reply("CON ", rw.USSD_DISTRICT_OTHER)
        state.district = district
        state.depth += 1
        state.stage = "sector"
        return _reply("CON ", rw.USSD_SECTOR)

    if state.stage == "sector":
        if choice in webhooks.SECTORS:
            state.sector = webhooks.SECTORS[choice]
            state.depth += 1
            state.stage = "menu"
            return _reply("CON ", rw.USSD_MAIN_MENU)
        if choice == "4":
            state.depth += 1
            state.stage = "sector_other"
            return _reply("CON ", rw.USSD_SECTOR_OTHER)
        return _reply("CON ", rw.USSD_SECTOR)

    if state.stage == "sector_other":
        sector = _tail(parts, state.depth)
        if not sector:
            return _reply("CON ", rw.USSD_SECTOR_OTHER)
        state.sector = sector
        state.depth += 1
        state.stage = "menu"
        return _reply("CON ", rw.USSD_MAIN_MENU)

    if state.stage == "menu":
        if choice == "1":
            state.depth += 1
            state.stage = "symptoms"
            return _reply("CON ", rw.USSD_SYMPTOMS)
        if choice == "2":
            state.depth += 1
            state.stage = "pests"
            return _reply("CON ", rw.USSD_PESTS)
        if choice == "3":
            summary = webhooks.alert_summary(state.sector)
            webhooks.clear_session(session_key)
            return _reply("END ", summary)
        return _reply("CON ", rw.USSD_MAIN_MENU)

    if state.stage == "symptoms":
        if choice in webhooks.SYMPTOMS:
            symptom_text = webhooks.SYMPTOMS[choice][0]
            return _finish_report(
                state=state,
                session_key=session_key,
                phone_number=phone_number,
                text=symptom_text,
            )
        if choice == "7":
            state.depth += 1
            state.stage = "symptoms_other"
            return _reply("CON ", rw.USSD_SYMPTOM_OTHER)
        return _reply("CON ", rw.USSD_SYMPTOMS)

    if state.stage == "symptoms_other":
        description = _tail(parts, state.depth)
        if not description:
            return _reply("CON ", rw.USSD_SYMPTOM_OTHER)
        return _finish_report(
            state=state,
            session_key=session_key,
            phone_number=phone_number,
            text=description,
        )

    if state.stage == "pests":
        pest_id = webhooks.PESTS.get(choice)
        if pest_id:
            return _finish_report(
                state=state,
                session_key=session_key,
                phone_number=phone_number,
                pest_id=pest_id,
            )
        return _reply("CON ", rw.USSD_PESTS)

    state = webhooks.reset_session(session_key)
    return _reply("CON ", rw.USSD_WELCOME)
