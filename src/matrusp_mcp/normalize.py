"""Normalização de texto e horários da fonte pública."""

from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_marks.casefold().split())


def parse_time(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*(\d{1,2})\s*:\s*(\d{2})\s*", value)
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return hour * 60 + minute


def normalize_day(value: str) -> str | None:
    day = normalize_text(value).replace("-feira", "")
    aliases = {
        "seg": "mon",
        "segunda": "mon",
        "segunda feira": "mon",
        "mon": "mon",
        "ter": "tue",
        "terca": "tue",
        "terça": "tue",
        "tue": "tue",
        "qua": "wed",
        "quarta": "wed",
        "wed": "wed",
        "qui": "thu",
        "quinta": "thu",
        "thu": "thu",
        "sex": "fri",
        "sexta": "fri",
        "fri": "fri",
        "sab": "sat",
        "sábado": "sat",
        "sat": "sat",
        "dom": "sun",
        "domingo": "sun",
        "sun": "sun",
    }
    return aliases.get(day)
