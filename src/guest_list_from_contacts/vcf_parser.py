from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import quopri
import re
from typing import Iterable


_VCARD_SPLIT = "BEGIN:VCARD"
_FIELD_NAME_RE = re.compile(r"^(?P<name>[^;:]+)(?P<params>(?:;[^:]+)*):(?P<value>.*)$")


@dataclass(slots=True)
class PhoneNumber:
    raw_value: str
    normalized_value: str
    kinds: tuple[str, ...]
    preferred: bool


@dataclass(slots=True)
class ContactRecord:
    full_name: str
    structured_name: tuple[str, ...]
    phones: tuple[PhoneNumber, ...]

    @property
    def preferred_phone(self) -> PhoneNumber | None:
        if not self.phones:
            return None
        ranked = sorted(
            self.phones,
            key=lambda phone: (
                0 if phone.preferred and "CELL" in phone.kinds else 1,
                0 if "CELL" in phone.kinds else 1,
                0 if phone.preferred else 1,
                0 if "HOME" in phone.kinds else 1,
            ),
        )
        return ranked[0]


def parse_vcf_contacts(file_path: str | Path) -> list[ContactRecord]:
    raw_text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    return parse_vcf_text(raw_text)


def parse_vcf_text(raw_text: str) -> list[ContactRecord]:
    unfolded_cards = _split_cards(_unfold_lines(raw_text))
    contacts: list[ContactRecord] = []
    for lines in unfolded_cards:
        contact = _parse_card(lines)
        if contact is not None:
            contacts.append(contact)
    return contacts


def _unfold_lines(raw_text: str) -> list[str]:
    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded: list[str] = []
    for line in lines:
        if not line:
            if unfolded and unfolded[-1].startswith("PHOTO"):
                continue
            unfolded.append(line)
            continue
        if line[0] in {" ", "\t"} and unfolded:
            unfolded[-1] += line[1:]
            continue
        unfolded.append(line)
    return unfolded


def _split_cards(lines: Iterable[str]) -> list[list[str]]:
    cards: list[list[str]] = []
    current: list[str] = []
    in_photo = False
    for line in lines:
        if line == _VCARD_SPLIT:
            current = [line]
            in_photo = False
            continue
        if not current:
            continue
        if line.startswith("PHOTO"):
            in_photo = True
            continue
        if in_photo:
            if line == "END:VCARD":
                cards.append(current)
                current = []
                in_photo = False
            continue
        if line == "END:VCARD":
            cards.append(current)
            current = []
            continue
        current.append(line)
    return cards


def _parse_card(lines: list[str]) -> ContactRecord | None:
    full_name = ""
    structured_name: tuple[str, ...] = ()
    phones: list[PhoneNumber] = []
    for line in lines:
        field_match = _FIELD_NAME_RE.match(line)
        if field_match is None:
            continue
        field_name = field_match.group("name").upper()
        params = _parse_params(field_match.group("params"))
        value = _decode_value(field_match.group("value"), params)
        if field_name == "FN":
            full_name = value.strip()
        elif field_name == "N":
            structured_name = tuple(part.strip() for part in value.split(";") if part.strip())
        elif field_name == "TEL":
            phones.append(
                PhoneNumber(
                    raw_value=value.strip(),
                    normalized_value=_normalize_phone(value),
                    kinds=tuple(sorted(params.get("TYPE", ()))),
                    preferred="PREF" in params,
                )
            )
    resolved_name = full_name or " ".join(structured_name).strip()
    if not resolved_name:
        return None
    return ContactRecord(
        full_name=resolved_name,
        structured_name=structured_name,
        phones=tuple(phone for phone in phones if phone.normalized_value),
    )


def _parse_params(raw_params: str) -> dict[str, tuple[str, ...]]:
    parsed: dict[str, tuple[str, ...]] = {}
    if not raw_params:
        return parsed
    for token in raw_params.split(";"):
        if not token:
            continue
        if "=" not in token:
            parsed[token.upper()] = ()
            continue
        key, raw_value = token.split("=", 1)
        parsed[key.upper()] = tuple(part.upper() for part in raw_value.split(",") if part)
    return parsed


def _decode_value(value: str, params: dict[str, tuple[str, ...]]) -> str:
    encoding = params.get("ENCODING", ())
    if "QUOTED-PRINTABLE" in encoding:
        decoded_bytes = quopri.decodestring(value)
        charset = next(iter(params.get("CHARSET", ())), "utf-8")
        return decoded_bytes.decode(charset, errors="replace")
    return value


def _normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value)
    if digits.startswith("972"):
        digits = "0" + digits[3:]
    if digits.startswith("00"):
        digits = digits[2:]
    return digits