"""Train the lightweight pest classifier.

Usage (from the project folder, with the venv active):

    python -m app.ml.train

The script reads `app/data/training_data.json`, trains a TF-IDF + logistic
regression pipeline and saves it to `app/ml/model.joblib`.

The diagnosis module also calls `train_model()` automatically when the model
file is missing or older than the training data, so the app works out of the
box after cloning.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import Pipeline

from app.ml.text import normalize

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR.parent / "data"
TRAINING_FILE = DATA_DIR / "training_data.json"
MODEL_FILE = ML_DIR / "model.joblib"


def build_pipeline() -> Pipeline:
    """Create the TF-IDF + Logistic Regression classifier.

    TF-IDF turns a symptom sentence into weighted word/n-gram features.
    Logistic Regression is small, fast and gives probability scores that we
    can treat as confidence.
    """
    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    ngram_range=(1, 2),
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(max_iter=1000, C=4.0),
            ),
        ]
    )


def load_training_rows() -> list[dict]:
    """Read the sample symptom phrases from JSON."""
    return json.loads(TRAINING_FILE.read_text(encoding="utf-8"))


def train_model(save: bool = True, verbose: bool = False) -> Pipeline:
    """Train the classifier and optionally save it to disk."""
    rows = load_training_rows()
    texts = [normalize(row["text"]) for row in rows]
    labels = [row["pest_id"] for row in rows]

    model = build_pipeline()
    model.fit(texts, labels)

    if verbose:
        # A quick sanity check on the tiny demo dataset. Cross-validation is
        # only a rough signal here because the dataset is intentionally small.
        scores = cross_val_score(build_pipeline(), texts, labels, cv=3)
        print(f"Training examples: {len(texts)}")
        print(f"Pests/classes: {len(set(labels))}")
        print(f"3-fold cross-validation accuracy: {scores.mean():.2f}")

    if save:
        joblib.dump(model, MODEL_FILE)
        if verbose:
            print(f"Saved model to: {MODEL_FILE}")

    return model


if __name__ == "__main__":
    train_model(verbose=True)
