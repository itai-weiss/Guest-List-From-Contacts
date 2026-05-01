from __future__ import annotations

import logging
import os
import uuid
import hashlib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
import sys
import time
from typing import Any

from flask import Flask, redirect, render_template, request, send_file, url_for

os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from guest_list_from_contacts.matching import MatchResult, match_guest_rows  # noqa: E402
from guest_list_from_contacts.models import GuestRow  # noqa: E402
from guest_list_from_contacts.vcf_parser import ContactRecord, parse_vcf_text  # noqa: E402
from guest_list_from_contacts.workbook import load_guest_workbook, write_output_workbook  # noqa: E402


LOGGER = logging.getLogger("guest_list_from_contacts.web")
DEFAULT_MAX_CONTENT_LENGTH = 50 * 1024 * 1024
DEFAULT_SESSION_TTL_SECONDS = 2 * 60 * 60
DEFAULT_SESSION_CLEANUP_INTERVAL_SECONDS = 5 * 60
STATUS_LABELS = {
    "matched": "הותאם",
    "review": "לבדיקה",
    "unmatched": "לא הותאם",
}
REASON_LABELS = {
    "exact": "התאמה מלאה",
    "exact-single-phone": "התאמה מלאה עם טלפון יחיד",
    "multiple exact matches": "כמה התאמות מלאות",
    "manual-review": "הוכרע ידנית",
    "no candidates": "לא נמצאו מועמדים",
}
UPLOAD_ERROR_MESSAGE = (
    "לא הצלחנו לעבד את הקבצים שהועלו. ודאו שקובץ המוזמנים הוא קובץ .xlsx תקין "
    "ושקובצי אנשי הקשר הם ייצואי .vcf תקינים."
)


@dataclass
class SessionState:
    workbook_name: str
    workbook: dict
    guest_rows: list
    contacts: list[ContactRecord]
    results: list[MatchResult]
    overrides: dict[str, int] = field(default_factory=dict)
    contact_file_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)


SESSIONS: dict[str, SessionState] = {}
COOKIE_NAME = "gid"


def localize_reason(reason: str) -> str:
    if reason in REASON_LABELS:
        return REASON_LABELS[reason]

    single_phone_suffix = "-single-phone"
    uses_single_phone = reason.endswith(single_phone_suffix)
    base_reason = reason[: -len(single_phone_suffix)] if uses_single_phone else reason

    if base_reason.startswith("fuzzy:"):
        fuzzy_key = base_reason.split(":", 1)[1]
        label = f"דמיון לשם: {fuzzy_key}"
        if uses_single_phone:
            return f"{label} · טלפון יחיד"
        return label

    return reason


def cleanup_expired_sessions(
    session_store: dict[str, SessionState],
    ttl_seconds: int,
    now: float | None = None,
) -> list[str]:
    if ttl_seconds <= 0:
        return []

    current_time = time.time() if now is None else now
    expired_ids = [
        sid
        for sid, state in session_store.items()
        if current_time - state.last_accessed_at > ttl_seconds
    ]
    for sid in expired_ids:
        session_store.pop(sid, None)
    return expired_ids


def make_choice_key(guest: GuestRow) -> str:
    sheet_digest = hashlib.sha1(guest.sheet_name.encode("utf-8")).hexdigest()[:10]
    return f"review-{sheet_digest}-{guest.row_index}"


def apply_overrides(
    base_results: list[MatchResult], overrides: dict[str, int]
) -> list[MatchResult]:
    out: list[MatchResult] = []
    for r in base_results:
        if r.status == "review" and r.candidates:
            key = make_choice_key(r.guest)
            idx = overrides.get(key, 0)
            if 0 < idx <= len(r.candidates):
                cand = r.candidates[idx - 1]
                out.append(
                    MatchResult(
                        guest=r.guest,
                        status="matched",
                        matched_contact=cand.contact,
                        phone_number=(
                            cand.contact.preferred_phone.normalized_value
                            if cand.contact.preferred_phone
                            else ""
                        ),
                        confidence=cand.score,
                        reason="manual-review",
                        candidates=r.candidates,
                    )
                )
                continue
        out.append(r)
    return out


def build_review_items(
    base_results: list[MatchResult], overrides: dict[str, int]
) -> list[dict]:
    items: list[dict] = []
    for r in base_results:
        if r.status != "review" or not r.candidates:
            continue
        key = make_choice_key(r.guest)
        selected = overrides.get(key, 0)
        items.append(
            {
                "choice_key": key,
                "sheet": r.guest.sheet_name,
                "row_index": r.guest.row_index,
                "guest_name": r.guest.raw_name,
                "candidate_count": len(r.candidates),
                "top_score": f"{r.confidence:.0f}",
                "candidates": [
                    {
                        "name": c.contact.full_name,
                        "phone": (
                            c.contact.preferred_phone.normalized_value
                            if c.contact.preferred_phone
                            else "ללא טלפון"
                        ),
                        "score": f"{c.score:.1f}",
                    }
                    for c in r.candidates
                ],
                "selected_index": selected,
                "resolved": selected > 0,
            }
        )
    return items


def build_download_name(workbook_name: str) -> str:
    source = Path(workbook_name or "guest-list.xlsx")
    stem = source.stem or "guest-list"
    return f"{stem}-matched.xlsx"


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.update(
        MAX_CONTENT_LENGTH=DEFAULT_MAX_CONTENT_LENGTH,
        SESSION_TTL_SECONDS=DEFAULT_SESSION_TTL_SECONDS,
        SESSION_CLEANUP_INTERVAL_SECONDS=DEFAULT_SESSION_CLEANUP_INTERVAL_SECONDS,
    )
    if config:
        app.config.update(config)
    app.config.setdefault("_LAST_SESSION_CLEANUP_AT", 0.0)

    def _run_session_cleanup(force: bool = False) -> None:
        now = time.time()
        last_cleanup = float(app.config.get("_LAST_SESSION_CLEANUP_AT", 0.0))
        cleanup_interval = int(app.config["SESSION_CLEANUP_INTERVAL_SECONDS"])

        if not force and now - last_cleanup < cleanup_interval:
            return

        expired_ids = cleanup_expired_sessions(
            SESSIONS,
            int(app.config["SESSION_TTL_SECONDS"]),
            now=now,
        )
        app.config["_LAST_SESSION_CLEANUP_AT"] = now
        if expired_ids:
            LOGGER.info("Expired %s stale session(s).", len(expired_ids))

    def _get_session_state() -> SessionState | None:
        _run_session_cleanup()
        sid = request.cookies.get(COOKIE_NAME)
        if not sid:
            return None

        state = SESSIONS.get(sid)
        if state is None:
            return None

        now = time.time()
        ttl_seconds = int(app.config["SESSION_TTL_SECONDS"])
        if ttl_seconds > 0 and now - state.last_accessed_at > ttl_seconds:
            SESSIONS.pop(sid, None)
            LOGGER.info("Session expired on access for sid=%s", sid)
            return None

        state.last_accessed_at = now
        return state

    @app.after_request
    def add_security_headers(response: Any) -> Any:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(413)
    def request_entity_too_large(error: Any) -> tuple[str, int]:
        limit_mb = max(1, int(app.config["MAX_CONTENT_LENGTH"]) // (1024 * 1024))
        LOGGER.warning("Upload rejected because it exceeded the %s MB limit.", limit_mb)
        return (
            render_template(
                "index.html",
                error=f"העלאה מוגבלת ל-{limit_mb} MB לבקשה.",
            ),
            413,
        )

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.post("/upload")
    def upload() -> Any:
        workbook_file = request.files.get("workbook")
        contacts_files = [f for f in request.files.getlist("contacts") if f and f.filename]
        _run_session_cleanup()

        if not workbook_file or not workbook_file.filename:
            return render_template("index.html", error="בחרו קובץ מוזמנים (.xlsx)."), 400
        if not contacts_files:
            return render_template("index.html", error="בחרו לפחות קובץ אנשי קשר אחד (.vcf)."), 400

        try:
            workbook, guest_rows = load_guest_workbook(BytesIO(workbook_file.read()))
            contacts: list[ContactRecord] = []
            for cf in contacts_files:
                text = cf.read().decode("utf-8", errors="ignore")
                contacts.extend(parse_vcf_text(text))
            results = match_guest_rows(guest_rows, contacts)
        except Exception:
            LOGGER.exception(
                "Failed to process upload workbook=%s contacts=%s",
                workbook_file.filename,
                [cf.filename for cf in contacts_files],
            )
            return render_template("index.html", error=UPLOAD_ERROR_MESSAGE), 400

        sid = str(uuid.uuid4())
        SESSIONS[sid] = SessionState(
            workbook_name=workbook_file.filename,
            workbook=workbook,
            guest_rows=guest_rows,
            contacts=contacts,
            results=results,
            contact_file_count=len(contacts_files),
        )
        LOGGER.info(
            "Created session sid=%s guests=%s contacts=%s files=%s",
            sid,
            len(guest_rows),
            len(contacts),
            len(contacts_files),
        )
        response = redirect(url_for("review"))
        response.set_cookie(COOKIE_NAME, sid, httponly=True, samesite="Lax")
        return response

    @app.get("/review")
    def review() -> Any:
        state = _get_session_state()
        if state is None:
            return redirect(url_for("index"))

        live_results = apply_overrides(state.results, state.overrides)
        review_items = build_review_items(state.results, state.overrides)
        resolved_count = sum(1 for item in review_items if item["resolved"])

        matched = sum(1 for r in live_results if r.status == "matched")
        review_count = sum(1 for r in live_results if r.status == "review")
        unmatched = sum(1 for r in live_results if r.status == "unmatched")

        nums = {
            "tally": "II",
            "review": "III",
            "ledger": "IV" if review_items else "III",
        }

        return render_template(
            "review.html",
            results=live_results,
            review_items=review_items,
            resolved_count=resolved_count,
            metrics={"matched": matched, "review": review_count, "unmatched": unmatched},
            guest_count=len(state.guest_rows),
            contact_count=len(state.contacts),
            contact_file_count=state.contact_file_count,
            nums=nums,
            status_labels=STATUS_LABELS,
            reason_label=localize_reason,
        )

    @app.post("/resolve")
    def resolve() -> Any:
        state = _get_session_state()
        if state is None:
            return redirect(url_for("index"))

        choice_key = (request.form.get("choice_key") or "").strip()
        if not choice_key:
            return redirect(url_for("review"))

        try:
            candidate_index = int(request.form.get("candidate", "0"))
        except ValueError:
            candidate_index = 0

        if candidate_index <= 0:
            state.overrides.pop(choice_key, None)
        else:
            state.overrides[choice_key] = candidate_index

        return redirect(f"{url_for('review')}#card-{choice_key}")

    @app.get("/download")
    def download() -> Any:
        state = _get_session_state()
        if state is None:
            return redirect(url_for("index"))

        output = write_output_workbook(
            state.workbook,
            apply_overrides(state.results, state.overrides),
        )
        return send_file(
            BytesIO(output),
            mimetype=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            as_attachment=True,
            download_name=build_download_name(state.workbook_name),
        )

    @app.route("/reset", methods=["GET", "POST"])
    def reset() -> Any:
        sid = request.cookies.get(COOKIE_NAME)
        if sid and sid in SESSIONS:
            del SESSIONS[sid]
            LOGGER.info("Reset session sid=%s", sid)
        response = redirect(url_for("index"))
        response.delete_cookie(COOKIE_NAME)
        return response

    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    port = int(os.environ.get("GUEST_LIST_PORT", "8765"))
    create_app().run(host="127.0.0.1", port=port, debug=False)
