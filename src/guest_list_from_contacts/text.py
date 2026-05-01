from __future__ import annotations

import re
import unicodedata


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.replace("'", " ").replace('"', " ")
    normalized = re.sub(r"[^\w\s\u0590-\u05FF]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    return normalized