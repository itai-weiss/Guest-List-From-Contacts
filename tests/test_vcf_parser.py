from pathlib import Path
import quopri

from guest_list_from_contacts.vcf_parser import parse_vcf_contacts


def _qp(value: str) -> str:
    return quopri.encodestring(value.encode("utf-8")).decode("ascii")


def _write_contacts_fixture(tmp_path: Path) -> Path:
    fixture = (
        "BEGIN:VCARD\n"
        "VERSION:2.1\n"
        f"FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:{_qp('דביר הכט')}\n"
        f"N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:{_qp('הכט;דביר;;;')}\n"
        "TEL;CELL;PREF:0584935795\n"
        "END:VCARD\n"
        "BEGIN:VCARD\n"
        "VERSION:2.1\n"
        f"FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:{_qp('אביה קושמרו')}\n"
        f"N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:{_qp('קושמרו;אביה;;;')}\n"
        "TEL;TYPE=CELL:0503404232\n"
        "PHOTO;ENCODING=BASE64:/9j/4AAQSkZJRgABAQAAAQABAAD\n"
        " iVBORw0KGgoAAAANSUhEUgAAAAUA\n"
        " AAABCAIAAACQd1Pe\n"
        "END:VCARD\n"
    )
    path = tmp_path / "contacts.vcf"
    path.write_text(fixture, encoding="utf-8")
    return path


def test_parse_vcf_contacts_reads_hebrew_names_and_preferred_phone(tmp_path: Path) -> None:
    contacts = parse_vcf_contacts(_write_contacts_fixture(tmp_path))

    assert contacts
    assert any(contact.full_name == "דביר הכט" for contact in contacts)

    dbir = next(contact for contact in contacts if contact.full_name == "דביר הכט")
    assert dbir.preferred_phone is not None
    assert dbir.preferred_phone.normalized_value == "0584935795"


def test_parse_vcf_contacts_ignores_photo_payload_and_keeps_phone_data(tmp_path: Path) -> None:
    contacts = parse_vcf_contacts(_write_contacts_fixture(tmp_path))

    abiya = next(contact for contact in contacts if contact.full_name == "אביה קושמרו")
    assert abiya.preferred_phone is not None
    assert abiya.preferred_phone.normalized_value == "0503404232"
    assert len(contacts) == 2
