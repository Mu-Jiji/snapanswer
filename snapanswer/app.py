"""Application controller: capture, OCR/model pipeline, tray, and hotkeys."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPixmap,
    QScreen,
)
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from .answer_window import AnswerWindow
from .config import (
    Config,
    is_local_endpoint,
    resolve_api_key,
    save_config,
)
from .highlight import RegionHighlight
from .hotkeys import HotkeyManager
from .imaging import crop_logical_region, mask_image_rect, region_fingerprint
from .ocr import RapidOcrEngine
from .ocr_text import is_new_question, normalize_text, should_reanswer, similarity
from .selection import RegionSelector
from .settings_dialog import SettingsDialog
from .usage import TokenUsage, UsageSnapshot, snapshot_from_usage
from .usage_panel import UsagePanel
from .usage_strip import UsageStrip
from .workers import OcrWorker, SolveWorker

log = logging.getLogger(__name__)


def asset_path(*parts: str) -> Path | None:
    """Find a bundled asset in source checkouts and PyInstaller builds."""
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            roots.append(Path(bundled))
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parent.parent)
    for root in roots:
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    return None


def format_hotkey(hotkey: str) -> str:
    """Convert pynput syntax to a compact label for menus/tooltips."""
    text = (
        hotkey.replace("<ctrl>", "Ctrl")
        .replace("<alt>", "Alt")
        .replace("<shift>", "Shift")
        .replace("<cmd>", "Win")
    )
    return "+".join(part.upper() if len(part) == 1 else part for part in text.split("+"))


class SnapAnswerApp(QObject):
    def __init__(
        self,
        app: QApplication,
        config: Config,
        config_path: Path,
    ) -> None:
        super().__init__()
        self.qapp = app
        self.config = config
        self.config_path = config_path
        self.continuous = bool(config.app.continuous)
        self.ocr_engine = RapidOcrEngine(config.ocr)

        self.window = AnswerWindow(config.app, str(config_path))
        self.window.scan_requested.connect(self.request_scan)
        self.window.continuous_toggled.connect(self.set_continuous)
        self.window.settings_requested.connect(self.open_settings)
        self.window.hidden_by_user.connect(self._on_window_hidden)
        self.window.usage_toggled.connect(self._on_usage_toggled)
        self.window.geometry_changed.connect(self._sync_usage_position)

        self.highlight = RegionHighlight()
        self.usage_panel = UsagePanel()
        self.usage_strip = UsageStrip()
        for widget in (self.usage_panel, self.usage_strip):
            widget.refresh_requested.connect(self.refresh_usage)
            widget.hidden_by_user.connect(self._on_usage_hidden)
        self._usage_visible_pref = bool(config.usage.show_panel)
        self._last_usage: TokenUsage | None = None
        self._last_usage_model = ""
        self._last_usage_elapsed = 0.0
        self._last_usage_at = datetime.now()

        self.hotkeys = HotkeyManager(self)
        self.hotkeys.bridge.scan.connect(self.request_scan)
        self.hotkeys.bridge.toggle_continuous.connect(self.toggle_continuous)
        self.hotkeys.bridge.show_window.connect(self.show_window)
        self.hotkeys.error.connect(self._on_hotkey_error)

        self._selector: RegionSelector | None = None
        self._solve_worker: SolveWorker | None = None
        self._ocr_worker: OcrWorker | None = None
        self._scan_pending = False
        self._pending_scan = False
        self._restore_window_after_scan = False
        self._settings_open = False
        self._shutting_down = False

        self._locked_region: QRect | None = None
        self._locked_screen_name = ""
        self._last_solved_text = ""
        self._watch_fingerprint = ""
        self._watch_pending_text = ""
        self._watch_stable = 0
        self._ocr_purpose = ""
        self._verify_pending = False
        self._verifying = False

        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._watch_tick)

        self._verify_timer = QTimer(self)
        self._verify_timer.setSingleShot(True)
        self._verify_timer.timeout.connect(self._run_verification)

        self._tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._tray_scan: QAction | None = None
        self._tray_continuous: QAction | None = None

        self._build_tray()
        self._apply_settings_to_window()
        self._register_hotkeys()

    # --------------------------------------------------------------- startup
    def start(self) -> None:
        self.window.show_window()
        self.window.set_continuous_checked(self.continuous)
        if self.continuous:
            self.window.show_idle("连续扫描已开启，请先框选一个题目区域")
        else:
            self.window.show_idle("等待框选题目")
        if not resolve_api_key(self.config) and not is_local_endpoint(
            self.config.llm.base_url
        ):
            self.window.set_status("请先配置模型 API")
            QTimer.singleShot(700, self.open_settings)
        elif not self.window.isVisible():
            self.window.show_window()

    # ------------------------------------------------------------------ tray
    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("System tray is not available")
            return
        self._tray = QSystemTrayIcon(self._make_icon(), self)
        self._tray.setToolTip("SnapAnswer · 截图答题助手")
        menu = QMenu()
        self._tray_scan = QAction("框选题目", menu)
        self._tray_scan.triggered.connect(self.request_scan)
        menu.addAction(self._tray_scan)
        self._tray_continuous = QAction("连续扫描", menu)
        self._tray_continuous.setCheckable(True)
        self._tray_continuous.setChecked(self.continuous)
        self._tray_continuous.triggered.connect(self.set_continuous)
        menu.addAction(self._tray_continuous)
        menu.addSeparator()
        show_action = QAction("显示浮窗", menu)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)
        settings_action = QAction("设置…", menu)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)
        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.shutdown)
        menu.addAction(quit_action)
        self._tray_menu = menu
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()
        self._update_tray_labels()

    @staticmethod
    def _make_icon() -> QIcon:
        png = asset_path("assets", "icon.png")
        if png is not None:
            icon = QIcon(str(png))
            ico = asset_path("assets", "icon.ico")
            if ico is not None:
                icon.addFile(str(ico))
            if not icon.isNull():
                return icon

        # Fallback if the asset is not bundled (e.g. a minimal editable install).
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#6ea8fe"))
        painter.drawRoundedRect(2, 2, 60, 60, 16, 16)
        painter.setPen(QColor("#0d1522"))
        painter.setFont(QFont("Segoe UI", 34, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "S")
        painter.end()
        return QIcon(pixmap)

    def _update_tray_labels(self) -> None:
        if self._tray_scan is not None:
            self._tray_scan.setText(
                f"框选题目\t{format_hotkey(self.config.app.hotkey_scan)}"
            )
        if self._tray is not None:
            self._tray.setToolTip(
                f"SnapAnswer · {format_hotkey(self.config.app.hotkey_scan)} 框选"
            )

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.request_scan()
        elif reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.MiddleClick,
        }:
            self.show_window()

    def _notify(self, text: str, warning: bool = False) -> None:
        if self._tray is not None and self._tray.isVisible():
            icon = (
                QSystemTrayIcon.MessageIcon.Warning
                if warning
                else QSystemTrayIcon.MessageIcon.Information
            )
            self._tray.showMessage("SnapAnswer", text, icon, 3000)

    # -------------------------------------------------------------- hotkeys
    def _register_hotkeys(self) -> None:
        self.hotkeys.start(self.config.app)

    def _on_hotkey_error(self, message: str) -> None:
        log.warning("Hotkey error: %s", message)
        self.window.set_status(message)
        self._notify(message, warning=True)

    def show_window(self) -> None:
        self.window.show_window()
        self._refresh_highlight()
        self._show_usage_widget()

    def _on_window_hidden(self) -> None:
        self.highlight.hide_highlight()
        self._hide_usage_widgets()
        if self.continuous:
            self.set_continuous(False)
            self.window.set_status("浮窗已隐藏，连续扫描已暂停")
        else:
            self.window.set_status("浮窗已隐藏")

    # -------------------------------------------------------------- scanning
    def request_scan(self) -> None:
        if self._shutting_down:
            return
        if self._selector is not None:
            self._selector.open()
            return
        if self._scan_pending:
            return
        if self._is_busy():
            self._pending_scan = True
            self._stop_watching()
            self.window.set_status("正在停止上一次请求…")
            if self._solve_worker is not None:
                self._solve_worker.cancel()
            if self._ocr_worker is not None:
                self._ocr_worker.cancel()
            return

        self._pending_scan = False
        self._stop_watching()
        self.highlight.hide_highlight()
        self._hide_usage_widgets()
        self._restore_window_after_scan = self.window.isVisible()
        if self.config.app.hide_on_capture and self.window.isVisible():
            self.window.hide()
        self._scan_pending = True
        QTimer.singleShot(max(0, self.config.app.capture_delay_ms), self._show_selector)

    def _show_selector(self) -> None:
        self._scan_pending = False
        if self._shutting_down:
            return
        if self._is_busy():
            self._pending_scan = True
            return
        if self._selector is not None:
            return
        self.highlight.hide_highlight()
        self._hide_usage_widgets()
        screen = QGuiApplication.screenAt(self._cursor_pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            self._capture_failed("找不到可截图的显示器")
            return
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            self._capture_failed("屏幕截图失败，可能是系统权限或受保护内容")
            return
        image = pixmap.toImage()
        image.setDevicePixelRatio(1.0)
        selector = RegionSelector(image, screen.geometry())
        self._selector = selector
        selector.selected.connect(self._on_region_selected)
        selector.cancelled.connect(self._on_selection_cancelled)
        selector.open()

    @staticmethod
    def _cursor_pos() -> QPoint:
        from PyQt6.QtGui import QCursor

        return QCursor.pos()

    def _capture_failed(self, message: str) -> None:
        self._restore_window_after_scan = False
        self.window.show_window()
        self.window.fail(message)
        self._refresh_highlight()
        self._show_usage_widget()
        self._notify(message, warning=True)

    def _on_region_selected(self, crop: QImage, region: QRect) -> None:
        self._selector = None
        self._restore_window_after_scan = False
        if self._shutting_down:
            return
        self._locked_region = QRect(region)
        screen = QGuiApplication.screenAt(region.center())
        self._locked_screen_name = screen.name() if screen is not None else ""
        self._last_solved_text = ""
        self._hide_usage_widgets()
        self._reset_watch_state()
        self._start_solve_image(crop)
        self._refresh_highlight()

    def _on_selection_cancelled(self) -> None:
        self._selector = None
        if self._shutting_down:
            return
        if self.continuous and self._locked_region is not None:
            self.window.show_window(activate=False)
            self.window.set_status("已取消框选，继续连续扫描")
            self._start_watching()
            self._refresh_highlight()
            self._show_usage_widget()
            return
        if self._restore_window_after_scan:
            self.window.show_window()
            self.window.set_status("已取消框选")
        else:
            self.window.set_status("已取消框选")
        self._restore_window_after_scan = False
        self._refresh_highlight()
        self._show_usage_widget()

    def _start_solve_image(self, image: QImage) -> None:
        self.window.begin_ocr()
        worker = SolveWorker(
            llm_settings=self.config.llm,
            api_key=resolve_api_key(self.config),
            image=image,
            ocr_engine=self.ocr_engine,
            parent=self,
        )
        self._solve_worker = worker
        worker.ocr_done.connect(
            lambda text, w=worker: self._on_solve_ocr_done(w, text),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.ocr_failed.connect(
            lambda msg, w=worker: self._on_solve_ocr_failed(w, msg),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.delta.connect(
            lambda text, w=worker: self._on_solve_delta(w, text),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.answer_ready.connect(
            lambda answer, elapsed, model, usage, w=worker: self._on_solve_answer(
                w, answer, elapsed, model, usage
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.failed.connect(
            lambda message, partial, w=worker: self._on_solve_failed(w, message, partial),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.cancelled.connect(
            lambda partial, w=worker: self._on_solve_cancelled(w, partial),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished.connect(
            lambda w=worker: self._on_worker_finished(w),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.start()

    def _start_solve_text(self, question: str, activate: bool = False) -> None:
        self._hide_usage_widgets()
        self.window.begin_request(question, self.config.llm.model, activate=activate)
        worker = SolveWorker(
            llm_settings=self.config.llm,
            api_key=resolve_api_key(self.config),
            question=question,
            parent=self,
        )
        self._solve_worker = worker
        worker.delta.connect(
            lambda text, w=worker: self._on_solve_delta(w, text),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.answer_ready.connect(
            lambda answer, elapsed, model, usage, w=worker: self._on_solve_answer(
                w, answer, elapsed, model, usage
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.failed.connect(
            lambda message, partial, w=worker: self._on_solve_failed(w, message, partial),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.cancelled.connect(
            lambda partial, w=worker: self._on_solve_cancelled(w, partial),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished.connect(
            lambda w=worker: self._on_worker_finished(w),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.start()

    # ------------------------------------------------------------ solve slots
    def _on_solve_ocr_done(self, worker: SolveWorker, text: str) -> None:
        if worker is not self._solve_worker:
            return
        self.window.set_ocr_text(text)
        self.window.begin_request(text, self.config.llm.model, activate=True)

    def _on_solve_ocr_failed(self, worker: SolveWorker, message: str) -> None:
        if worker is not self._solve_worker:
            return
        self.window.fail(message)
        self._notify(message, warning=True)

    def _on_solve_delta(self, worker: SolveWorker, text: str) -> None:
        if worker is not self._solve_worker:
            return
        self.window.append_delta(text)

    def _on_solve_answer(
        self,
        worker: SolveWorker,
        answer: str,
        elapsed: float,
        model: str,
        usage: object,
    ) -> None:
        if worker is not self._solve_worker:
            return
        self.window.finish_answer(answer, elapsed, model)
        self._last_solved_text = worker.question or self._last_solved_text
        if isinstance(usage, TokenUsage):
            self._last_usage = usage
        else:
            self._last_usage = TokenUsage(source="unknown")
        self._last_usage_model = model
        self._last_usage_elapsed = elapsed
        self._last_usage_at = datetime.now()
        self._refresh_usage_panel()
        self._schedule_verification()

    # ---------------------------------------------------------------- usage
    def _usage_snapshot(self) -> UsageSnapshot | None:
        if self._last_usage is None:
            return None
        return snapshot_from_usage(
            self._last_usage,
            model=self._last_usage_model,
            elapsed_sec=self._last_usage_elapsed,
            settings=self.config.usage,
            priced_at=self._last_usage_at,
        )

    def _usage_widget(self) -> QWidget:
        if self.config.usage.display_mode == "card":
            return self.usage_panel
        return self.usage_strip

    def _hide_usage_widgets(self) -> None:
        self.usage_panel.hide_panel()
        self.usage_strip.hide_panel()

    def _show_usage_widget(self) -> None:
        if (
            not self._usage_visible_pref
            or self._last_usage is None
            or not self.window.isVisible()
            or self._settings_open
            or self._selector is not None
            or self._scan_pending
        ):
            return
        active = self._usage_widget()
        other = self.usage_strip if active is self.usage_panel else self.usage_panel
        other.hide_panel()
        active.show_panel()
        active.follow(self.window.frameGeometry())

    def _refresh_usage_panel(self) -> None:
        snapshot = self._usage_snapshot()
        self.usage_panel.set_snapshot(snapshot)
        self.usage_strip.set_snapshot(snapshot)
        self._show_usage_widget()

    def _sync_usage_position(self) -> None:
        for widget in (self.usage_panel, self.usage_strip):
            if widget.isVisible():
                widget.follow(self.window.frameGeometry())

    def _on_usage_toggled(self, checked: bool) -> None:
        self._usage_visible_pref = bool(checked)
        self.config.usage.show_panel = self._usage_visible_pref
        self._save_config_safely()
        if checked:
            self._refresh_usage_panel()
            self._show_usage_widget()
        else:
            self._hide_usage_widgets()

    def _on_usage_hidden(self) -> None:
        self._usage_visible_pref = False
        self.config.usage.show_panel = False
        self.window.set_usage_checked(False)
        self._hide_usage_widgets()
        self._save_config_safely()

    def refresh_usage(self) -> None:
        """Recalculate the panel with the current pricing settings."""
        self._refresh_usage_panel()
        self._show_usage_widget()

    def _on_solve_failed(self, worker: SolveWorker, message: str, partial: str) -> None:
        if worker is not self._solve_worker:
            return
        self.window.fail(message, partial)
        if worker.question:
            self._last_solved_text = worker.question
        self._notify(message.splitlines()[0] if message else "模型请求失败", warning=True)

    def _on_solve_cancelled(self, worker: SolveWorker, partial: str) -> None:
        if worker is not self._solve_worker or self._shutting_down:
            return
        self.window.set_busy(False)
        if partial.strip():
            self.window.finish_answer(partial, 0.0, self.config.llm.model)
            self.window.set_status("已停止生成")
        else:
            self.window.set_status("已取消本次请求")

    def _on_worker_finished(self, worker: SolveWorker) -> None:
        if worker is self._solve_worker:
            self._solve_worker = None
        worker.deleteLater()
        if self._shutting_down:
            return
        if self._pending_scan and not self._is_busy():
            self._pending_scan = False
            QTimer.singleShot(0, self.request_scan)
            return
        self._maybe_restart_watching()

    def _maybe_restart_watching(self) -> None:
        if (
            self.continuous
            and self._locked_region is not None
            and not self._is_busy()
            and not self._settings_open
            and self._selector is None
            and not self._pending_scan
            and not self._verify_pending
            and not self._verifying
            and not self._shutting_down
        ):
            # A normal watcher OCR pass leaves the periodic timer running; keep
            # its debounce state instead of resetting it here.
            if self._watch_timer.isActive():
                return
            self._start_watching(announce=False)

    # ------------------------------------------------------------- continuous
    def toggle_continuous(self) -> None:
        self.set_continuous(not self.continuous)

    def set_continuous(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._shutting_down:
            return
        self.continuous = enabled
        self.config.app.continuous = enabled
        self.window.set_continuous_checked(enabled)
        if self._tray_continuous is not None:
            self._tray_continuous.blockSignals(True)
            self._tray_continuous.setChecked(enabled)
            self._tray_continuous.blockSignals(False)
        self._save_config_safely()
        if not enabled:
            self._stop_watching()
            self.window.set_status("连续扫描已关闭")
            return
        if self._locked_region is None:
            self.window.show_window()
            self.window.set_status("连续扫描已开启，请框选区域")
            self.request_scan()
        else:
            self._start_watching()
            self._notify("连续扫描已开启")

    def _start_watching(self, announce: bool = True) -> None:
        if (
            not self.continuous
            or self._locked_region is None
            or self._is_busy()
            or self._selector is not None
            or self._settings_open
            or self._verify_pending
            or self._verifying
            or self._shutting_down
        ):
            return
        if not self.window.isVisible():
            self.window.show_window(activate=False)
        self._refresh_highlight()
        self._ensure_window_clear_of_region()
        self._watch_fingerprint = ""
        self._watch_pending_text = ""
        self._watch_stable = 0
        interval = int(self.config.app.continuous_interval_sec * 1000)
        self._watch_timer.start(max(800, interval))
        if announce:
            self.window.set_locked_state(True, self.config.app.continuous_interval_sec)

    def _stop_watching(self) -> None:
        self._watch_timer.stop()
        self._watch_pending_text = ""
        self._watch_stable = 0
        self._verify_timer.stop()
        self._verify_pending = False
        # If a verification OCR is already in flight, ignore its result.
        self._verifying = False

    def _reset_watch_state(self) -> None:
        self._stop_watching()
        self._watch_fingerprint = ""

    def _refresh_highlight(self) -> None:
        if (
            not self.config.app.highlight_region
            or self._locked_region is None
            or not self.window.isVisible()
            or self._selector is not None
            or self._scan_pending
            or self._shutting_down
        ):
            self.highlight.hide_highlight()
            return
        screen = self._screen_for_region()
        if screen is None:
            self.highlight.hide_highlight()
            return
        self.highlight.set_region(screen.geometry(), self._locked_region)
        self.highlight.show_highlight()

    def _screen_for_region(self) -> QScreen | None:
        if self._locked_region is None:
            return None
        for screen in QGuiApplication.screens():
            if self._locked_screen_name and screen.name() == self._locked_screen_name:
                return screen
        return QGuiApplication.screenAt(self._locked_region.center())

    def _ensure_window_clear_of_region(self) -> bool:
        """Move the answer window out of the locked capture region if possible."""
        if self._locked_region is None:
            return True
        frame = self.window.frameGeometry()
        if not frame.intersects(self._locked_region):
            return True
        screen = self._screen_for_region()
        if screen is None:
            return False
        region = self._locked_region
        gap = 14
        areas = [screen.availableGeometry()]
        areas.extend(
            other.availableGeometry()
            for other in QGuiApplication.screens()
            if other is not screen
        )
        for area in areas:
            width = min(self.window.width(), area.width())
            height = min(self.window.height(), area.height())
            candidates = [
                QPoint(region.right() + gap, region.top()),
                QPoint(region.left() - width - gap, region.top()),
                QPoint(region.left(), region.bottom() + gap),
                QPoint(region.left(), region.top() - height - gap),
                QPoint(area.left() + 16, area.top() + 16),
                QPoint(area.right() - width - 16, area.top() + 16),
                QPoint(area.left() + 16, area.bottom() - height - 16),
                QPoint(area.right() - width - 16, area.bottom() - height - 16),
            ]
            for point in candidates:
                candidate = QRect(point, self.window.size())
                if area.contains(candidate) and not candidate.intersects(region):
                    self.window.move(point)
                    return True
        return False

    def _watch_tick(self) -> None:
        if (
            not self.continuous
            or self._locked_region is None
            or self._is_busy()
            or self._selector is not None
            or self._scan_pending
            or self._verify_pending
            or self._verifying
            or self._shutting_down
        ):
            return
        # Move the window clear when possible; if the region is too large, the
        # overlap is masked in the captured frame instead of hiding the window.
        self._ensure_window_clear_of_region()
        self._capture_watch_frame()

    def _schedule_verification(self) -> None:
        """Queue a fresh OCR pass after an answer has been rendered."""
        if (
            not self.continuous
            or not self.config.app.verify_after_answer
            or self._locked_region is None
            or self._settings_open
            or self._shutting_down
        ):
            return
        self._watch_timer.stop()
        self._verify_pending = True
        delay = max(0.2, self.config.app.verify_delay_sec)
        self._verify_timer.start(int(delay * 1000))
        self.window.set_status(f"答题完成，{delay:.1f}s 后复核 OCR…")

    def _run_verification(self) -> None:
        self._verify_pending = False
        if (
            not self.continuous
            or not self.config.app.verify_after_answer
            or self._locked_region is None
            or self._settings_open
            or self._selector is not None
            or self._scan_pending
            or self._shutting_down
        ):
            self._maybe_restart_watching()
            return
        if self._is_busy():
            # A request may still be winding down; check again shortly.
            self._verify_pending = True
            self._verify_timer.start(400)
            return
        self._verifying = True
        self.window.set_status("正在复核 OCR…")
        self._ensure_window_clear_of_region()
        self._capture_watch_frame(verify=True)

    def _finish_verification(self) -> None:
        self._verifying = False
        self._maybe_restart_watching()

    def _mask_widget_overlap(self, crop: QImage, widget: QWidget) -> None:
        if (
            not widget.isVisible()
            or self._locked_region is None
            or crop.isNull()
        ):
            return
        overlap = widget.frameGeometry().intersected(self._locked_region)
        if overlap.isEmpty():
            return
        region = self._locked_region
        sx = crop.width() / region.width()
        sy = crop.height() / region.height()
        relative = overlap.translated(-region.topLeft())
        left = max(0, int(relative.x() * sx) - 1)
        top = max(0, int(relative.y() * sy) - 1)
        right = min(crop.width(), int((relative.x() + relative.width()) * sx) + 2)
        bottom = min(crop.height(), int((relative.y() + relative.height()) * sy) + 2)
        if right > left and bottom > top:
            mask_image_rect(crop, QRect(left, top, right - left, bottom - top))

    def _mask_window_overlap(self, crop: QImage) -> None:
        """Blank the parts of the crop covered by floating windows.

        This avoids hiding the answer window (which used to cause a visible
        flash) and prevents answer/usage text from being fed back into OCR.
        """
        self._mask_widget_overlap(crop, self.window)
        self._mask_widget_overlap(crop, self.usage_panel)
        self._mask_widget_overlap(crop, self.usage_strip)

    def _capture_watch_frame(self, verify: bool = False) -> None:
        blocked = (
            not self.continuous
            or self._locked_region is None
            or self._is_busy()
            or self._scan_pending
            or self._selector is not None
            or (not verify and (self._verify_pending or self._verifying))
        )
        if blocked:
            if verify:
                self._finish_verification()
            return
        screen = self._screen_for_region()
        if screen is None:
            self._stop_watching()
            self.window.set_status("框选所在显示器已断开")
            if verify:
                self._verifying = False
            return
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            self.window.set_status("复核截图失败" if verify else "连续扫描截图失败")
            if verify:
                self._finish_verification()
            return
        image = pixmap.toImage()
        image.setDevicePixelRatio(1.0)
        crop = crop_logical_region(image, screen.geometry(), self._locked_region)
        if crop.isNull():
            if verify:
                self._finish_verification()
            return
        self._mask_window_overlap(crop)
        if not verify:
            fingerprint = region_fingerprint(crop)
            if fingerprint == self._watch_fingerprint and not self._watch_pending_text:
                return
            self._watch_fingerprint = fingerprint
        worker = OcrWorker(crop, self.ocr_engine, parent=self)
        self._ocr_worker = worker
        self._ocr_purpose = "verify" if verify else "watch"
        if verify:
            worker.completed.connect(
                lambda text, w=worker: self._on_verify_ocr_done(w, text),
                Qt.ConnectionType.QueuedConnection,
            )
            worker.failed.connect(
                lambda msg, w=worker: self._on_verify_ocr_failed(w, msg),
                Qt.ConnectionType.QueuedConnection,
            )
        else:
            worker.completed.connect(
                lambda text, w=worker: self._on_watch_ocr_done(w, text),
                Qt.ConnectionType.QueuedConnection,
            )
            worker.failed.connect(
                lambda msg, w=worker: self._on_watch_ocr_failed(w, msg),
                Qt.ConnectionType.QueuedConnection,
            )
        worker.finished.connect(
            lambda w=worker: self._on_ocr_worker_finished(w),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.start()

    def _on_watch_ocr_done(self, worker: OcrWorker, text: str) -> None:
        if (
            worker is not self._ocr_worker
            or self._ocr_purpose != "watch"
            or self._pending_scan
        ):
            return
        text = normalize_text(text)
        if not text:
            return
        if self._last_solved_text and similarity(text, self._last_solved_text) >= 0.90:
            self._watch_pending_text = ""
            self._watch_stable = 0
            return
        if not is_new_question(text, self._last_solved_text):
            self._watch_pending_text = ""
            self._watch_stable = 0
            return
        if (
            self._watch_pending_text
            and similarity(text, self._watch_pending_text) >= 0.94
        ):
            self._watch_stable += 1
        else:
            self._watch_pending_text = text
            self._watch_stable = 1
        if self._watch_stable < 2:
            self.window.set_status("检测到题目变化，正在确认…")
            return

        self._last_solved_text = text
        self._watch_pending_text = ""
        self._watch_stable = 0
        self._watch_timer.stop()
        self._start_solve_text(text, activate=False)

    def _on_verify_ocr_done(self, worker: OcrWorker, text: str) -> None:
        if (
            worker is not self._ocr_worker
            or self._ocr_purpose != "verify"
            or not self._verifying
            or self._pending_scan
        ):
            return
        self._verifying = False
        text = normalize_text(text)
        if not text:
            self.window.set_status("复核未识别到文字，继续连续扫描")
            return
        threshold = self.config.app.verify_similarity
        if not should_reanswer(self._last_solved_text, text, threshold=threshold):
            interval = self.config.app.continuous_interval_sec
            self.window.set_status(f"复核完成 · 连续扫描中（每 {interval:.1f}s）")
            log.debug("Verification OCR matches the answered question")
            return
        log.info("Verification OCR found a changed question; re-answering")
        self._last_solved_text = text
        self._watch_pending_text = ""
        self._watch_stable = 0
        self.window.set_status("复核发现题目变化，重新作答…")
        self._start_solve_text(text, activate=False)

    def _on_verify_ocr_failed(self, worker: OcrWorker, message: str) -> None:
        if (
            worker is not self._ocr_worker
            or self._ocr_purpose != "verify"
            or not self._verifying
        ):
            return
        self._verifying = False
        log.debug("Verification OCR failed: %s", message)
        self.window.set_status(f"复核 OCR 失败，继续连续扫描：{message}")

    def _on_watch_ocr_failed(self, worker: OcrWorker, message: str) -> None:
        if worker is not self._ocr_worker or self._ocr_purpose != "watch":
            return
        log.debug("Continuous OCR failed: %s", message)
        self.window.set_status(f"连续扫描：{message}")

    def _on_ocr_worker_finished(self, worker: OcrWorker) -> None:
        if worker is self._ocr_worker:
            self._ocr_worker = None
        worker.deleteLater()
        self._ocr_purpose = ""
        self._verifying = False
        if self._shutting_down:
            return
        if self._pending_scan and not self._is_busy():
            self._pending_scan = False
            QTimer.singleShot(0, self.request_scan)
            return
        self._maybe_restart_watching()

    # --------------------------------------------------------------- settings
    def open_settings(self) -> None:
        if self._shutting_down or self._settings_open:
            return
        if self._selector is not None:
            self._selector.close()
        self._stop_watching()
        self.highlight.hide_highlight()
        self._hide_usage_widgets()
        self._settings_open = True
        accepted = False
        try:
            dialog_config = self.config.copy()
            dialog_config.app.window_width = self.window.width()
            dialog_config.app.window_height = self.window.height()
            dialog = SettingsDialog(dialog_config, self.config_path, self.window)
            if dialog.exec():
                accepted = True
                old_width, old_height = self.window.width(), self.window.height()
                self.config = dialog.result_config()
                old_ocr = self.ocr_engine.settings
                if old_ocr != self.config.ocr:
                    self.ocr_engine = RapidOcrEngine(self.config.ocr)
                self.continuous = self.config.app.continuous
                self.window.apply_settings(self.config.app)
                self.window.set_continuous_checked(self.continuous)
                if (old_width, old_height) != (
                    self.config.app.window_width,
                    self.config.app.window_height,
                ):
                    self.window.resize_to(
                        self.config.app.window_width,
                        self.config.app.window_height,
                    )
                self._usage_visible_pref = bool(self.config.usage.show_panel)
                self.window.set_usage_checked(self._usage_visible_pref)
                self._register_hotkeys()
                self._update_tray_labels()
                if self._tray_continuous is not None:
                    self._tray_continuous.blockSignals(True)
                    self._tray_continuous.setChecked(self.continuous)
                    self._tray_continuous.blockSignals(False)
                self.window.set_status("设置已保存")
                self._notify("设置已保存")
        except Exception as exc:  # pragma: no cover - defensive UI guard
            log.exception("Settings dialog failed")
            self.window.fail(f"打开设置失败：{exc}")
        finally:
            self._settings_open = False
        self._refresh_usage_panel()
        if not self._usage_visible_pref:
            self._hide_usage_widgets()
        self._refresh_highlight()
        if (
            self.continuous
            and self._locked_region is not None
            and not self._is_busy()
            and not self._shutting_down
        ):
            self._start_watching()
        if accepted and self._usage_visible_pref:
            self._show_usage_widget()

    def _apply_settings_to_window(self) -> None:
        self.window.apply_settings(self.config.app)
        self.window.set_continuous_checked(self.continuous)
        self.window.set_usage_checked(self._usage_visible_pref)

    def _save_config_safely(self) -> None:
        try:
            save_config(self.config, self.config_path)
        except OSError as exc:
            log.exception("Could not save config")
            self._notify(f"配置保存失败：{exc}", warning=True)

    # ---------------------------------------------------------------- helpers
    def _is_busy(self) -> bool:
        return self._solve_worker is not None or self._ocr_worker is not None

    # --------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        log.info("Shutting down")
        self._watch_timer.stop()
        self._verify_timer.stop()
        self._verify_pending = False
        self._verifying = False
        self.hotkeys.stop()
        if self._selector is not None:
            self._selector.close()
            self._selector = None
        workers: list[object] = []
        if self._solve_worker is not None:
            self._solve_worker.cancel()
            workers.append(self._solve_worker)
        if self._ocr_worker is not None:
            self._ocr_worker.cancel()
            workers.append(self._ocr_worker)
        for worker in workers:
            if not worker.wait(3000):  # type: ignore[attr-defined]
                log.warning("Worker did not stop; terminating")
                worker.terminate()  # type: ignore[attr-defined]
                worker.wait(800)  # type: ignore[attr-defined]
        self.highlight.hide_highlight()
        self._hide_usage_widgets()
        if self._tray is not None:
            self._tray.hide()
        self.window.prepare_quit()
        self.window.close()
        self.qapp.quit()
