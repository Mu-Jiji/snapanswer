"""Global hotkeys with a Qt-signal bridge (pynput runs on its own thread)."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal

from .config import AppSettings

log = logging.getLogger(__name__)


class HotkeyBridge(QObject):
    scan = pyqtSignal()
    toggle_continuous = pyqtSignal()
    show_window = pyqtSignal()


class HotkeyManager(QObject):
    error = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.bridge = HotkeyBridge(self)
        self._listener = None

    def start(self, settings: AppSettings) -> None:
        self.stop()
        mapping: dict[str, object] = {}
        try:
            from pynput import keyboard

            candidates = {
                settings.hotkey_scan: self.bridge.scan.emit,
                settings.hotkey_toggle_continuous: self.bridge.toggle_continuous.emit,
                settings.hotkey_show: self.bridge.show_window.emit,
            }
            for hotkey, callback in candidates.items():
                hotkey = hotkey.strip()
                if not hotkey:
                    continue
                try:
                    keyboard.HotKey.parse(hotkey)
                except ValueError:
                    self.error.emit(f"无效的全局快捷键：{hotkey}")
                    continue
                if hotkey in mapping:
                    self.error.emit(f"快捷键重复，已忽略：{hotkey}")
                    continue
                mapping[hotkey] = callback
            if not mapping:
                return
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
            log.info("Global hotkeys registered: %s", ", ".join(mapping))
        except Exception as exc:  # pragma: no cover - platform input backend
            log.exception("Could not register global hotkeys")
            self.error.emit(f"全局快捷键注册失败：{exc}")
            self._listener = None

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:  # pragma: no cover
            log.debug("Error while stopping hotkey listener", exc_info=True)
