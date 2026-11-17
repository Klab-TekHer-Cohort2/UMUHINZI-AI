"""Tests for SQLite persistence and identifier hashing."""

import sqlite3

import pytest

from app import config
from app.db import storage

RAW_PHONE = "+250788123456"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "umuhinzi-test.db"
    monkeypatch.setattr(config, "DB_FILE", db_path)
    storage.init_db()
    yield db_path


def test_hash_identifier_is_stable_and_never_raw():
    first = storage.hash_identifier(RAW_PHONE)
    second = storage.hash_identifier(RAW_PHONE)

    assert first == second
    assert first != RAW_PHONE
    assert len(first) == 64
    assert storage.hash_identifier("") is None
    assert storage.hash_identifier(None) is None


def test_save_diagnosis_stores_only_hashed_identifier(temp_db):
    reporter_hash = storage.hash_identifier(RAW_PHONE)

    report_id = storage.save_diagnosis(
        reporter_hash=reporter_hash,
        pest_id="fall_armyworm",
        sector="Kacyiru",
        district="Gasabo",
    )

    assert report_id > 0
    reports = storage.list_recent_diagnoses()
    assert len(reports) == 1
    assert reports[0]["pest_id"] == "fall_armyworm"
    assert reports[0]["sector"] == "Kacyiru"
    assert reports[0]["district"] == "Gasabo"
    assert reports[0]["reporter_hash"] == reporter_hash
    assert reports[0]["created_at"]

    with sqlite3.connect(temp_db) as conn:
        row = conn.execute("SELECT * FROM diagnoses").fetchone()

    assert RAW_PHONE not in repr(row)
    assert reporter_hash in repr(row)


def test_registration_hashes_phone(temp_db):
    phone_hash = storage.hash_identifier(RAW_PHONE)

    registration_id = storage.save_registration(
        role="farmer",
        name="Aline",
        phone_hash=phone_hash,
        sector="Kacyiru",
        district="Gasabo",
    )

    assert registration_id > 0
    with sqlite3.connect(temp_db) as conn:
        row = conn.execute("SELECT * FROM registrations").fetchone()

    assert RAW_PHONE not in repr(row)
    assert phone_hash in repr(row)


def test_recent_reports_are_limited_and_newest_first(temp_db):
    for index in range(3):
        storage.save_diagnosis(
            reporter_hash=storage.hash_identifier(f"session-{index}"),
            pest_id="bean_fly",
            sector="Kacyiru",
            district="Gasabo",
            created_at=f"2026-01-0{index + 1}T00:00:00+00:00",
        )

    reports = storage.list_recent_diagnoses(limit=2)

    assert len(reports) == 2
    assert reports[0]["created_at"] == "2026-01-03T00:00:00+00:00"
    assert reports[1]["created_at"] == "2026-01-02T00:00:00+00:00"
