from __future__ import annotations

from collections import defaultdict

from rapidfuzz import fuzz

from .models import GuestRow, MatchCandidate, MatchResult
from .text import normalize_name
from .vcf_parser import ContactRecord


AUTO_MATCH_THRESHOLD = 96.0
REVIEW_THRESHOLD = 78.0


def build_contact_name_keys(contact: ContactRecord) -> set[str]:
    keys: set[str] = set()
    full_name = normalize_name(contact.full_name)
    if full_name:
        keys.add(full_name)
        tokens = full_name.split()
        if len(tokens) > 1:
            keys.add(" ".join(reversed(tokens)))
            keys.add(" ".join(sorted(tokens)))

    structured_tokens = [normalize_name(part) for part in contact.structured_name if normalize_name(part)]
    if structured_tokens:
        keys.add(" ".join(structured_tokens))
        keys.add(" ".join(reversed(structured_tokens)))
        keys.add(" ".join(sorted(structured_tokens)))
    return {key for key in keys if key}


def match_guest_rows(guest_rows: list[GuestRow], contacts: list[ContactRecord]) -> list[MatchResult]:
    contacts = _deduplicate_contacts(contacts)
    indexed_contacts = _index_contacts(contacts)
    results: list[MatchResult] = []
    for guest in guest_rows:
        exact_matches = indexed_contacts.get(guest.normalized_name, [])
        if len(exact_matches) == 1:
            results.append(_matched_result(guest, exact_matches[0], 100.0, "exact"))
            continue
        if len(exact_matches) > 1:
            candidates = tuple(MatchCandidate(contact=contact, score=100.0, reason="exact-duplicate") for contact in exact_matches)
            single_phone_candidate = _single_preferred_phone_candidate(candidates)
            if single_phone_candidate is not None:
                results.append(_matched_result(guest, single_phone_candidate.contact, 100.0, "exact-single-phone"))
                continue
            results.append(
                MatchResult(
                    guest=guest,
                    status="review",
                    matched_contact=None,
                    phone_number="",
                    confidence=100.0,
                    reason="multiple exact matches",
                    candidates=candidates,
                )
            )
            continue

        candidates = _rank_candidates(guest, contacts)
        if not candidates:
            results.append(
                MatchResult(
                    guest=guest,
                    status="unmatched",
                    matched_contact=None,
                    phone_number="",
                    confidence=0.0,
                    reason="no candidates",
                    candidates=(),
                )
            )
            continue

        top_candidate = candidates[0]
        second_score = candidates[1].score if len(candidates) > 1 else 0.0
        score_gap = top_candidate.score - second_score
        if top_candidate.score >= AUTO_MATCH_THRESHOLD and score_gap >= 4.0:
            results.append(_matched_result(guest, top_candidate.contact, top_candidate.score, top_candidate.reason))
        elif top_candidate.score >= REVIEW_THRESHOLD:
            review_candidates = tuple(candidates[:5])
            single_phone_candidate = _single_preferred_phone_candidate(review_candidates)
            if single_phone_candidate is not None:
                results.append(
                    _matched_result(
                        guest,
                        single_phone_candidate.contact,
                        single_phone_candidate.score,
                        f"{single_phone_candidate.reason}-single-phone",
                    )
                )
                continue
            results.append(
                MatchResult(
                    guest=guest,
                    status="review",
                    matched_contact=None,
                    phone_number="",
                    confidence=top_candidate.score,
                    reason=top_candidate.reason,
                    candidates=review_candidates,
                )
            )
        else:
            results.append(
                MatchResult(
                    guest=guest,
                    status="unmatched",
                    matched_contact=None,
                    phone_number="",
                    confidence=top_candidate.score,
                    reason=top_candidate.reason,
                    candidates=tuple(candidates[:5]),
                )
            )
    return results


def _index_contacts(contacts: list[ContactRecord]) -> dict[str, list[ContactRecord]]:
    indexed: dict[str, list[ContactRecord]] = defaultdict(list)
    for contact in contacts:
        for key in build_contact_name_keys(contact):
            indexed[key].append(contact)
    return indexed


def _rank_candidates(guest: GuestRow, contacts: list[ContactRecord]) -> list[MatchCandidate]:
    ranked: list[MatchCandidate] = []
    for contact in contacts:
        keys = build_contact_name_keys(contact)
        if not keys:
            continue
        best_key = max(keys, key=lambda key: _combined_score(guest.normalized_name, key))
        score = _combined_score(guest.normalized_name, best_key)
        if score < 55:
            continue
        ranked.append(MatchCandidate(contact=contact, score=score, reason=f"fuzzy:{best_key}"))
    ranked.sort(key=lambda candidate: candidate.score, reverse=True)
    return ranked


def _single_preferred_phone_candidate(candidates: tuple[MatchCandidate, ...]) -> MatchCandidate | None:
    candidates_by_phone: dict[str, MatchCandidate] = {}
    for candidate in candidates:
        preferred_phone = candidate.contact.preferred_phone
        if preferred_phone is None:
            continue
        phone = preferred_phone.normalized_value
        if not phone:
            continue
        candidates_by_phone.setdefault(phone, candidate)
    if len(candidates_by_phone) != 1:
        return None
    return next(iter(candidates_by_phone.values()))


def _deduplicate_contacts(contacts: list[ContactRecord]) -> list[ContactRecord]:
    unique_contacts: list[ContactRecord] = []
    seen_signatures: set[tuple[str, tuple[str, ...]]] = set()
    for contact in contacts:
        signature = _contact_signature(contact)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        unique_contacts.append(contact)
    return unique_contacts


def _contact_signature(contact: ContactRecord) -> tuple[str, tuple[str, ...]]:
    normalized_name = normalize_name(contact.full_name)
    normalized_phones = tuple(sorted(phone.normalized_value for phone in contact.phones if phone.normalized_value))
    return normalized_name, normalized_phones


def _combined_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    token_sort = fuzz.token_sort_ratio(left, right)
    token_set = fuzz.token_set_ratio(left, right)
    partial = fuzz.partial_ratio(left, right)
    return round((token_sort * 0.45) + (token_set * 0.4) + (partial * 0.15), 2)


def _matched_result(guest: GuestRow, contact: ContactRecord, score: float, reason: str) -> MatchResult:
    preferred_phone = contact.preferred_phone
    return MatchResult(
        guest=guest,
        status="matched",
        matched_contact=contact,
        phone_number=preferred_phone.normalized_value if preferred_phone is not None else "",
        confidence=score,
        reason=reason,
        candidates=(),
    )
