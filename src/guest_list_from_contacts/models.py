from __future__ import annotations

from dataclasses import dataclass

from .vcf_parser import ContactRecord


@dataclass(slots=True)
class GuestRow:
    sheet_name: str
    row_index: int
    raw_name: str
    normalized_name: str
    values: dict[str, object]


@dataclass(slots=True)
class MatchCandidate:
    contact: ContactRecord
    score: float
    reason: str


@dataclass(slots=True)
class MatchResult:
    guest: GuestRow
    status: str
    matched_contact: ContactRecord | None
    phone_number: str
    confidence: float
    reason: str
    candidates: tuple[MatchCandidate, ...]