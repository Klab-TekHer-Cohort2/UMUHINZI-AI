"""Small text-normalisation helpers shared by training and inference.

Keeping this in one place guarantees the model is trained and queried with
exactly the same text cleaning.
"""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace.

    Kinyarwanda does not use accents, but removing them makes the model more
    forgiving of typing differences. Apostrophes are kept because words such as
    "y'ibigori" are common in Kinyarwanda.
    """
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
