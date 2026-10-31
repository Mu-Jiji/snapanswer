"""Windows-only best-effort exclusion of a window from screen capture."""

from __future__ import annotations

import ctypes
import logging
import sys

from PyQt6.QtWidgets import QWidget

log = logging.getLogger(__name__)

WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_window_from_capture(widget: QWidget) -> bool:
    """Ask Windows to omit this window from screen captures.

    This is available on Windows 10 2004+ and is intentionally best-effort: if
    the API fails (older Windows, unusual desktop compositor), continuous mode
    still masks the window rectangle in the captured frame.
    """
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        user32.SetWindowDisplayAffinity.restype = ctypes.c_bool
        if user32.SetWindowDisplayAffinity(
            ctypes.c_void_p(hwnd), WDA_EXCLUDEFROMCAPTURE
        ):
            return True
        error = ctypes.GetLastError()
        log.debug("SetWindowDisplayAffinity failed (error=%s)", error)
    except (AttributeError, OSError, ValueError):
        log.debug("Window capture exclusion is not available", exc_info=True)
    return False
