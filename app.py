from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import socket
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser
from pathlib import Path
import sys

from werkzeug.serving import make_server

from flask_app import create_app


LOGGER = logging.getLogger("guest_list_from_contacts.launcher")
APP_DIR_NAME = "GuestListFromContacts"
SERVER_READY_TIMEOUT_SECONDS = 10.0
SERVER_READY_RETRY_SECONDS = 0.2


def _default_log_path() -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return local_app_data / APP_DIR_NAME / "logs" / "app.log"


def _configure_logging() -> Path:
    log_path = _default_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return log_path

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    return log_path


def _resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(url: str, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1.0) as response:
                return 200 <= response.status < 500
        except URLError:
            time.sleep(SERVER_READY_RETRY_SECONDS)
    return False


def _open_browser_when_ready(url: str) -> None:
    if not _wait_for_server(url, SERVER_READY_TIMEOUT_SECONDS):
        LOGGER.warning("Server did not become ready before browser launch timeout.")

    try:
        opened = webbrowser.open(url)
    except Exception:
        LOGGER.exception("Failed to open the browser for %s", url)
        return

    LOGGER.info("Browser launch requested for %s (opened=%s)", url, opened)


def main() -> int:
    log_path = _configure_logging()
    root_path = _resource_path("")
    if str(root_path) not in sys.path:
        sys.path.insert(0, str(root_path))

    LOGGER.info("Starting desktop launcher (log=%s)", log_path)

    try:
        app = create_app()
        port = _find_free_port()
        url = f"http://127.0.0.1:{port}/"
        server = make_server("127.0.0.1", port, app, threaded=True)

        opener = threading.Thread(
            target=_open_browser_when_ready,
            args=(url,),
            daemon=True,
        )
        opener.start()

        print(f"Guest List From Contacts is running at {url}", flush=True)
        print("Close this window to stop the app.", flush=True)
        LOGGER.info("Server listening on %s", url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            LOGGER.info("Shutdown requested by user.")
        finally:
            server.server_close()
            LOGGER.info("Server stopped.")
    except Exception:
        LOGGER.exception("Launcher failed during startup.")
        print(
            "Guest List From Contacts could not start. Check the log file for details.",
            flush=True,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
