from guest_list_from_contacts.matching import match_guest_rows
from guest_list_from_contacts.models import GuestRow
from guest_list_from_contacts.text import normalize_name
from guest_list_from_contacts.vcf_parser import ContactRecord, PhoneNumber


def test_normalize_name_collapses_spacing_and_punctuation() -> None:
    assert normalize_name("  נעם   פריג'ה ") == "נעם פריג ה"


def test_normalize_name_preserves_hebrew_word_order_for_exact_matching() -> None:
    assert normalize_name("דביר הכט") == "דביר הכט"


def test_match_guest_rows_deduplicates_identical_contacts_before_exact_match() -> None:
    guest_rows = [
        GuestRow(
            sheet_name="Guests",
            row_index=0,
            raw_name="אביגיל כהן",
            normalized_name=normalize_name("אביגיל כהן"),
            values={"שם": "אביגיל כהן"},
        )
    ]
    repeated_contact = ContactRecord(
        full_name="אביגיל כהן",
        structured_name=("כהן", "אביגיל"),
        phones=(
            PhoneNumber(
                raw_value="0585304356",
                normalized_value="0585304356",
                kinds=("CELL",),
                preferred=True,
            ),
        ),
    )

    results = match_guest_rows(guest_rows, [repeated_contact, repeated_contact])

    assert len(results) == 1
    assert results[0].status == "matched"
    assert results[0].phone_number == "0585304356"
    assert results[0].reason == "exact"


def test_match_guest_rows_auto_matches_multiple_exact_contacts_with_one_phone() -> None:
    guest_rows = [
        GuestRow(
            sheet_name="Guests",
            row_index=0,
            raw_name="Ori Bina",
            normalized_name=normalize_name("Ori Bina"),
            values={"name": "Ori Bina"},
        )
    ]
    contact_with_phone = ContactRecord(
        full_name="Ori Bina",
        structured_name=("Bina", "Ori"),
        phones=(
            PhoneNumber(
                raw_value="0525665352",
                normalized_value="0525665352",
                kinds=("CELL",),
                preferred=True,
            ),
        ),
    )
    contact_without_phone = ContactRecord(
        full_name="Ori Bina",
        structured_name=("Bina", "Ori"),
        phones=(),
    )

    results = match_guest_rows(guest_rows, [contact_with_phone, contact_without_phone])

    assert len(results) == 1
    assert results[0].status == "matched"
    assert results[0].phone_number == "0525665352"
    assert results[0].matched_contact == contact_with_phone
    assert results[0].reason == "exact-single-phone"


def test_match_guest_rows_still_reviews_multiple_exact_contacts_with_multiple_phones() -> None:
    guest_rows = [
        GuestRow(
            sheet_name="Guests",
            row_index=0,
            raw_name="Ori Bina",
            normalized_name=normalize_name("Ori Bina"),
            values={"name": "Ori Bina"},
        )
    ]
    first_contact = ContactRecord(
        full_name="Ori Bina",
        structured_name=("Bina", "Ori"),
        phones=(
            PhoneNumber(
                raw_value="0525665352",
                normalized_value="0525665352",
                kinds=("CELL",),
                preferred=True,
            ),
        ),
    )
    second_contact = ContactRecord(
        full_name="Ori Bina",
        structured_name=("Bina", "Ori"),
        phones=(
            PhoneNumber(
                raw_value="0520000000",
                normalized_value="0520000000",
                kinds=("CELL",),
                preferred=True,
            ),
        ),
    )

    results = match_guest_rows(guest_rows, [first_contact, second_contact])

    assert len(results) == 1
    assert results[0].status == "review"
    assert results[0].phone_number == ""
    assert results[0].reason == "multiple exact matches"
