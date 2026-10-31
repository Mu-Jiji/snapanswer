"""File/console logging setup."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

_ACTIVE_LOG_PATH: Path | None = None


def log_dir() -> Path:
    if _ACTIVE_LOG_PATH is not None:
        return _ACTIVE_LOG_PATH.parent
    return _preferred_log_dir()


def _preferred_log_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "SnapAnswer" / "logs"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "snapanswer" / "logs"


def _candidate_log_dirs() -> list[Path]:
    return [
        _preferred_log_dir(),
        Path(tempfile.gettempdir()) / "snapanswer-data" / "logs",
        Path.cwd() / ".snapanswer" / "logs",
    ]


def setup_logging(debug: bool = False) -> Path:
    global _ACTIVE_LOG_PATH
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    path = _preferred_log_dir() / "snapanswer.log"
    for directory in _candidate_log_dirs():
        candidate = directory / "snapanswer.log"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                candidate, maxBytes=1_500_000, backupCount=3, encoding="utf-8"
            )
        except OSError:
            continue
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        path = candidate
        break
    _ACTIVE_LOG_PATH = path

    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        console.setLevel(logging.DEBUG if debug else logging.WARNING)
        root.addHandler(console)
    return path


def install_qt_message_handler() -> None:
    """Route Qt warnings into the Python log instead of stderr only."""
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:  # pragma: no cover
        return

    log = logging.getLogger("qt")
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, context, message):  # noqa: ANN001
        log.log(levels.get(mode, logging.INFO), "%s", message)

    qInstallMessageHandler(handler)
