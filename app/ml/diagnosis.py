"""Pest diagnosis: TF-IDF model with a keyword-matching fallback.

How a sentence is classified
1. Normalise the farmer's text.
2. Ask the trained TF-IDF + Logistic Regression model for a pest and a
   probability (confidence).
3. If the model is not confident enough, match symptom keywords from
   `app/data/pests.json`.
4. If neither is confident, return "unknown" so the voice layer can politely
   ask the farmer to describe the problem again. We NEVER present a low
   confidence guess as certain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import joblib

from app.i18n import rw
from app.ml.text import normalize

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR.parent / "data"
PESTS_FILE = DATA_DIR / "pests.json"
TRAINING_FILE = DATA_DIR / "training_data.json"
MODEL_FILE = ML_DIR / "model.joblib"

# Model confidence needed before we trust the classifier.
MODEL_CONFIDENCE_THRESHOLD = 0.45
# Keyword confidence needed before we trust keyword matching.
KEYWORD_CONFIDENCE_THRESHOLD = 0.35


@dataclass
class DiagnosisResult:
    """Result returned to the API, dashboard and voice layer."""

    pest_id: str | None
    name_rw: str | None
    name_en: str | None
    crops_rw: list[str] = field(default_factory=list)
    confidence: float = 0.0
    method: str = "none"  # "model", "keywords" or "none"
    matched_keywords: list[str] = field(default_factory=list)

    @property
    def confident(self) -> bool:
        """True only when a real pest was identified confidently."""
        return self.pest_id is not None

    def to_dict(self) -> dict:
        return {
            "pest_id": self.pest_id,
            "name_rw": self.name_rw,
            "name_en": self.name_en,
            "crops_rw": self.crops_rw,
            "confidence": round(self.confidence, 2),
            "method": self.method,
            "matched_keywords": self.matched_keywords,
            "confident": self.confident,
        }


@lru_cache(maxsize=1)
def load_pests() -> dict[str, dict]:
    """Load the knowledge base as {pest_id: pest}."""
    payload = json.loads(PESTS_FILE.read_text(encoding="utf-8"))
    return {pest["id"]: pest for pest in payload["pests"]}


def list_pests() -> list[dict]:
    """Return a short list for the `/pests` endpoint and dashboard."""
    return [
        {
            "id": pest["id"],
            "name_rw": pest["name_rw"],
            "name_en": pest["name_en"],
            "crops_rw": pest["crops"]["rw"],
            "crops_en": pest["crops"]["en"],
        }
        for pest in load_pests().values()
    ]


def get_pest(pest_id: str) -> dict:
    return load_pests()[pest_id]


@lru_cache(maxsize=1)
def _keyword_index() -> dict[str, list[tuple[str, int]]]:
    """Build {pest_id: [(normalised keyword, word_count), ...]} once."""
    index: dict[str, list[tuple[str, int]]] = {}
    for pest_id, pest in load_pests().items():
        keywords = pest["keywords"]["rw"] + pest["keywords"]["en"]
        index[pest_id] = [
            (normalize(keyword), max(1, len(keyword.split())))
            for keyword in keywords
            if keyword.strip()
        ]
    return index


def _make_result(
    pest_id: str,
    confidence: float,
    method: str,
    matched_keywords: list[str] | None = None,
) -> DiagnosisResult:
    pest = get_pest(pest_id)
    return DiagnosisResult(
        pest_id=pest_id,
        name_rw=pest["name_rw"],
        name_en=pest["name_en"],
        crops_rw=pest["crops"]["rw"],
        confidence=max(0.0, min(1.0, confidence)),
        method=method,
        matched_keywords=matched_keywords or [],
    )


def _unknown(confidence: float = 0.0) -> DiagnosisResult:
    return DiagnosisResult(
        pest_id=None,
        name_rw=None,
        name_en=None,
        confidence=max(0.0, min(1.0, confidence)),
        method="none",
    )


def keyword_match(text: str) -> DiagnosisResult | None:
    """Score each pest by how many symptom keywords appear in the text.

    Longer phrases (e.g. "amababi y'ibigori arashye") count more than a single
    generic word (e.g. "inyo"). This is the fallback when the ML model is
    unsure.
    """
    normalised = normalize(text)
    if not normalised:
        return None

    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}

    for pest_id, keywords in _keyword_index().items():
        score = 0.0
        matched: list[str] = []
        for keyword, word_count in keywords:
            if keyword and keyword in normalised:
                score += word_count
                matched.append(keyword)
        if score > 0:
            scores[pest_id] = score
            hits[pest_id] = matched

    if not scores:
        return None

    best_pest = max(scores, key=scores.get)  # type: ignore[arg-type]
    total_score = sum(scores.values())
    share = scores[best_pest] / total_score if total_score else 0.0

    # Confidence grows with the number of distinct keyword hits, but stays
    # below 0.9 because keyword matching is a fallback.
    confidence = min(0.88, 0.45 + 0.10 * len(hits[best_pest]))
    if share < 0.5:
        # The text matched several pests; be less certain.
        confidence *= 0.65

    return _make_result(best_pest, confidence, "keywords", hits[best_pest])


def _model_needs_training() -> bool:
    if not MODEL_FILE.exists():
        return True
    try:
        model_time = MODEL_FILE.stat().st_mtime
        data_time = TRAINING_FILE.stat().st_mtime
        pests_time = PESTS_FILE.stat().st_mtime
    except OSError:
        return True
    return model_time < max(data_time, pests_time)


@lru_cache(maxsize=1)
def _load_model():
    """Load the saved model, training it automatically if needed."""
    if _model_needs_training():
        # Imported here to avoid a circular import at module load time.
        from app.ml.train import train_model

        return train_model(save=True)
    try:
        return joblib.load(MODEL_FILE)
    except Exception:
        from app.ml.train import train_model

        return train_model(save=True)


def _predict_with_model(text: str) -> tuple[str | None, float]:
    model = _load_model()
    probabilities = model.predict_proba([normalize(text)])[0]
    best_index = int(probabilities.argmax())
    return str(model.classes_[best_index]), float(probabilities[best_index])


def diagnose(text: str) -> DiagnosisResult:
    """Return the most likely pest, or an unknown result when unsure."""
    if not text or len(normalize(text)) < 3:
        return _unknown()

    model_label: str | None = None
    model_confidence = 0.0
    try:
        model_label, model_confidence = _predict_with_model(text)
    except Exception:
        # A broken/missing model must never take down a live call; fall back to
        # keyword matching instead.
        model_label, model_confidence = None, 0.0

    if model_label and model_confidence >= MODEL_CONFIDENCE_THRESHOLD:
        return _make_result(model_label, model_confidence, "model")

    keyword_result = keyword_match(text)
    if (
        keyword_result is not None
        and keyword_result.confidence >= KEYWORD_CONFIDENCE_THRESHOLD
    ):
        return keyword_result

    # Never return a low-confidence guess as if it were a diagnosis.
    best_effort = model_confidence
    if keyword_result is not None:
        best_effort = max(best_effort, keyword_result.confidence)
    return _unknown(best_effort)


def build_reply(result: DiagnosisResult) -> str:
    """Build the short Kinyarwanda sentence spoken/read back to the farmer."""
    if not result.pest_id:
        return rw.LOW_CONFIDENCE_REPLY

    pest = get_pest(result.pest_id)
    treatment_steps = pest["treatment"]["rw"][:2]
    prevention_tips = pest["prevention"]["rw"][:1]

    return rw.DIAGNOSIS_REPLY.format(
        name=result.name_rw,
        steps=" ".join(treatment_steps),
        prevention=prevention_tips[0] if prevention_tips else "",
    )


def diagnose_and_reply(text: str) -> dict:
    """Convenience helper used by the API, dashboard and tests."""
    result = diagnose(text)
    return {
        "diagnosis": result.to_dict(),
        "reply_rw": build_reply(result),
    }
