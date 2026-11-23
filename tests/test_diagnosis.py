"""Stage 2 tests: knowledge base, diagnosis model, keyword fallback, API."""

from fastapi.testclient import TestClient

from app.i18n import rw
from app.main import app
from app.ml.diagnosis import (
    build_reply,
    diagnose,
    keyword_match,
    list_pests,
    load_pests,
)

client = TestClient(app)

REQUIRED_PESTS = {
    "fall_armyworm",
    "maize_stalk_borer",
    "cassava_mosaic",
    "bean_fly",
    "banana_bacterial_wilt",
    "potato_late_blight",
}


def test_knowledge_base_has_required_pests():
    pests = load_pests()
    assert REQUIRED_PESTS.issubset(pests.keys())
    for pest in pests.values():
        assert pest["name_rw"]
        assert pest["name_en"]
        assert pest["crops"]["rw"]
        assert pest["keywords"]["rw"]
        assert pest["treatment"]["rw"]
        assert pest["prevention"]["rw"]


def test_model_diagnoses_fall_armyworm_kinyarwanda():
    result = diagnose("amababi y'ibigori arashye kandi afite uduhumbi")
    assert result.pest_id == "fall_armyworm"
    assert result.confident is True
    assert result.confidence >= 0.45
    assert result.method in {"model", "keywords"}


def test_diagnosis_handles_lowercase_text_without_diacritics():
    plain = "amababi y'ibigori arashye kandi afite uduhumbi"
    variant = "ÁMABABI Y'IBIGORI ARASHYE KANDI AFITE UDUHUMBI"

    assert diagnose(plain).pest_id == "fall_armyworm"
    assert diagnose(variant).pest_id == "fall_armyworm"


def test_model_diagnoses_potato_late_blight_english():
    result = diagnose("potato leaves have dark spots and white mold")
    assert result.pest_id == "potato_late_blight"
    assert result.confidence >= 0.45


def test_keyword_fallback_matches_banana_wilt():
    result = keyword_match("igitoke cyanjye gifite umutobe wera mu gishishwa")
    assert result is not None
    assert result.pest_id == "banana_bacterial_wilt"
    assert result.method == "keywords"
    assert "umutobe wera" in result.matched_keywords


def test_unknown_text_is_not_guessed():
    result = diagnose("mfite ikibazo gishya")
    assert result.pest_id is None
    assert result.confident is False
    assert build_reply(result) == rw.LOW_CONFIDENCE_REPLY


def test_reply_is_short_kinyarwanda():
    result = diagnose("isazi ziri ku mizi y'ibishyimbo")
    reply = build_reply(result)
    assert result.pest_id == "bean_fly"
    assert result.name_rw in reply
    assert "Icyo wakora" in reply
    # Keep replies short for live phone calls.
    assert len(reply) < 700


def test_pests_endpoint():
    response = client.get("/pests")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 6
    assert any(p["id"] == "fall_armyworm" for p in body["pests"])


def test_diagnose_endpoint():
    response = client.post(
        "/diagnose",
        json={"text": "amababi y'imyumbati arimo mosaic kandi agoretse"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["diagnosis"]["pest_id"] == "cassava_mosaic"
    assert body["reply_rw"]
    assert "Twahisemo" in body["reply_rw"]
