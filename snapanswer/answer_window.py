"""Always-on-top answer overlay window."""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, QEvent, QPoint, QSettings, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .capture_exclusion import exclude_window_from_capture
from .config import AppSettings

APP_QSS = """
QWidget#root { background: transparent; }
QFrame#card {
    background: #141922;
    border: 1px solid #2b3342;
    border-radius: 14px;
}
QLabel { color: #e8edf7; }
QLabel#title { font-size: 13px; font-weight: 700; letter-spacing: 0.4px; }
QLabel#status { color: #8f9db6; font-size: 10px; }
QLabel#meta { color: #7f8da7; font-size: 10px; }
QLabel#brandDot {
    background: #6ea8fe;
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}
QPushButton {
    background: transparent;
    color: #b9c5da;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px 9px;
    font-size: 11px;
}
QPushButton:hover { background: #202838; color: #ffffff; }
QPushButton:pressed { background: #273145; }
QPushButton#primary {
    background: #24446f;
    border: 1px solid #3a69a5;
    color: #dceaff;
}
QPushButton#primary:hover { background: #2d5488; }
QPushButton#continuous:checked {
    background: #1d3b33;
    border: 1px solid #2e7a63;
    color: #8ff0c7;
}
QPushButton#usage:checked {
    background: #1e2f49;
    border: 1px solid #355d8d;
    color: #a9ccff;
}
QPushButton#close:hover { background: #5a2630; color: #ffdce2; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab {
    background: transparent;
    color: #7f8da7;
    padding: 6px 12px;
    margin-right: 4px;
    border-bottom: 2px solid transparent;
    font-size: 11px;
}
QTabBar::tab:selected { color: #dce7fb; border-bottom: 2px solid #6ea8fe; }
QTabBar::tab:hover { color: #ffffff; }
QTextBrowser {
    background: #0f131b;
    border: 1px solid #222a38;
    border-radius: 9px;
    color: #dbe4f3;
    padding: 10px;
    selection-background-color: #345f94;
}
QProgressBar {
    border: none;
    background: #1b2230;
    max-height: 2px;
    min-height: 2px;
}
QProgressBar::chunk { background: #6ea8fe; }
"""


class ResizeHandle(QWidget):
    """Visible bottom-right grip for resizing the frameless window."""

    def __init__(self, target: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._target = target
        self._start_global: QPoint | None = None
        self._start_size = QSize()
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("拖动调整浮窗大小")

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(154, 173, 200, 190), 1.4))
        width, height = self.width(), self.height()
        for offset in (4, 8, 12):
            painter.drawLine(width - offset, height - 3, width - 3, height - offset)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_global = event.globalPosition().toPoint()
            self._start_size = self._target.size()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._start_global is None:
            return
        delta = event.globalPosition().toPoint() - self._start_global
        minimum = self._target.minimumSize()
        width = max(minimum.width(), self._start_size.width() + delta.x())
        height = max(minimum.height(), self._start_size.height() + delta.y())
        self._target.resize(width, height)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._start_global = None
        event.accept()


class AnswerWindow(QWidget):
    scan_requested = pyqtSignal()
    continuous_toggled = pyqtSignal(bool)
    settings_requested = pyqtSignal()
    usage_toggled = pyqtSignal(bool)
    hidden_by_user = pyqtSignal()
    geometry_changed = pyqtSignal()

    def __init__(self, settings: AppSettings, config_path: str = "") -> None:
        super().__init__()
        self._settings = settings
        self._config_path = config_path
        self._drag_offset: QPoint | None = None
        self._stream_text = ""
        self._last_answer = ""
        self._allow_close = False
        self._capture_excluded = False
        self._settings_store = QSettings("SnapAnswer", "SnapAnswer")
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(60)
        self._flush_timer.timeout.connect(self._flush_stream)
        self._copy_reset_timer = QTimer(self)
        self._copy_reset_timer.setSingleShot(True)
        self._copy_reset_timer.timeout.connect(lambda: self.copy_button.setText("复制"))

        self._build_ui()
        self.setWindowTitle("SnapAnswer")
        self.setWindowOpacity(settings.opacity)
        self.setMinimumSize(380, 260)
        self.setStyleSheet(APP_QSS)
        self._apply_window_flags()
        self._restore_geometry()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.setObjectName("root")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(14, 11, 14, 10)
        layout.setSpacing(8)

        self.header = QWidget(self.card)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(7)
        dot = QLabel(self.header)
        dot.setObjectName("brandDot")
        header.addWidget(dot)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_label = QLabel("SNAPANSWER", self.header)
        self.title_label.setObjectName("title")
        self.status_label = QLabel("等待框选题目", self.header)
        self.status_label.setObjectName("status")
        titles.addWidget(self.title_label)
        titles.addWidget(self.status_label)
        header.addLayout(titles)
        header.addStretch(1)

        self.scan_button = QPushButton("框选", self.header)
        self.scan_button.setObjectName("primary")
        self.scan_button.setToolTip("框选新的题目区域（全局快捷键见设置）")
        self.scan_button.clicked.connect(self.scan_requested)
        header.addWidget(self.scan_button)

        self.continuous_button = QPushButton("连续", self.header)
        self.continuous_button.setObjectName("continuous")
        self.continuous_button.setCheckable(True)
        self.continuous_button.setToolTip("锁定框选区域：题目变化时自动识别，答题后再复核一次")
        self.continuous_button.toggled.connect(self._on_continuous_toggled)
        header.addWidget(self.continuous_button)

        self.settings_button = QPushButton("设置", self.header)
        self.settings_button.clicked.connect(self.settings_requested)
        header.addWidget(self.settings_button)

        self.close_button = QPushButton("×", self.header)
        self.close_button.setObjectName("close")
        self.close_button.setToolTip("隐藏浮窗（程序继续在托盘运行）")
        self.close_button.clicked.connect(self._hide_by_user)
        header.addWidget(self.close_button)
        layout.addWidget(self.header)

        self.progress = QProgressBar(self.card)
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.tabs = QTabWidget(self.card)
        self.answer_view = self._make_browser()
        self.ocr_view = self._make_browser()
        self.tabs.addTab(self.answer_view, "答案")
        self.tabs.addTab(self.ocr_view, "识别原文")
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(2, 0, 0, 0)
        footer.setSpacing(6)
        self.meta_label = QLabel("答案由 AI 生成，请自行核对", self.card)
        self.meta_label.setObjectName("meta")
        footer.addWidget(self.meta_label)
        footer.addStretch(1)
        self.usage_button = QPushButton("用量", self.card)
        self.usage_button.setObjectName("usage")
        self.usage_button.setCheckable(True)
        self.usage_button.setToolTip("显示本次识别的 token 与估算费用")
        self.usage_button.toggled.connect(self.usage_toggled)
        footer.addWidget(self.usage_button)
        self.copy_button = QPushButton("复制", self.card)
        self.copy_button.setToolTip("复制当前标签页内容")
        self.copy_button.clicked.connect(self.copy_current)
        footer.addWidget(self.copy_button)
        self.resize_handle = ResizeHandle(self, self.card)
        footer.addWidget(self.resize_handle, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(footer)

        for widget in (self.header, self.title_label, self.status_label):
            widget.installEventFilter(self)
        self.answer_view.setOpenLinks(True)
        self.answer_view.setOpenExternalLinks(True)
        self.ocr_view.setOpenLinks(False)
        self._set_placeholder()

    def _make_browser(self) -> QTextBrowser:
        browser = QTextBrowser(self.card)
        browser.setFont(QFont("Microsoft YaHei UI", 10))
        browser.setOpenLinks(False)
        browser.document().setDefaultStyleSheet(
            "p { margin: 0 0 8px 0; line-height: 150%; }"
            "h1,h2,h3 { color: #f3f7ff; }"
            "code { background: #1c2534; color: #d7e5ff; font-family: Consolas; }"
            "pre { background: #101722; color: #d7e5ff; padding: 8px; }"
            "blockquote { color: #9fb0cc; border-left: 2px solid #3d5d86; }"
        )
        return browser

    def _set_placeholder(self) -> None:
        self.answer_view.setMarkdown(
            "### 准备就绪\n\n"
            "点击 **框选**，或使用全局快捷键，在屏幕上拖出题目区域。\n\n"
            "- OCR 会自动提取中文/英文题目\n"
            "- 答案会显示在这个置顶浮窗里\n"
            "- 开启 **连续** 后，锁定区域中的题目变化时会自动更新答案"
        )
        self.ocr_view.setPlainText("识别结果将显示在这里。")

    # --------------------------------------------------------------- public
    def apply_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self.setWindowOpacity(settings.opacity)
        self.continuous_button.blockSignals(True)
        self.continuous_button.setChecked(settings.continuous)
        self.continuous_button.blockSignals(False)
        self._apply_window_flags()
        self._refresh_continuous_style()

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_busy(self, busy: bool, text: str | None = None) -> None:
        self.progress.setVisible(busy)
        self.scan_button.setEnabled(not busy)
        if text is not None:
            self.set_status(text)

    def set_continuous_checked(self, checked: bool) -> None:
        self.continuous_button.blockSignals(True)
        self.continuous_button.setChecked(checked)
        self.continuous_button.blockSignals(False)
        self._refresh_continuous_style()

    def set_usage_checked(self, checked: bool) -> None:
        self.usage_button.blockSignals(True)
        self.usage_button.setChecked(checked)
        self.usage_button.blockSignals(False)

    def _refresh_continuous_style(self) -> None:
        if self.continuous_button.isChecked():
            self.continuous_button.setToolTip("连续扫描已开启：题目变化时自动重答，答题后还会复核 OCR")
        else:
            self.continuous_button.setToolTip("锁定框选区域：题目变化时自动识别，答题后再复核一次")

    def show_window(self, activate: bool = True) -> None:
        if not self.isVisible():
            self.show()
        if not self._capture_excluded:
            self._capture_excluded = exclude_window_from_capture(self)
        if activate:
            self.raise_()
            self.activateWindow()

    def begin_ocr(self) -> None:
        self._stream_text = ""
        self._last_answer = ""
        self._flush_timer.stop()
        self.answer_view.setPlainText("")
        self.ocr_view.setPlainText("正在识别屏幕文字…")
        self.tabs.setCurrentIndex(0)
        self.meta_label.setText("RapidOCR · 识别中…")
        self.set_busy(True, "正在识别题目…")
        self.show_window(activate=True)

    def begin_request(self, question: str, model: str, activate: bool = True) -> None:
        self._stream_text = ""
        self._last_answer = ""
        self._flush_timer.stop()
        self.answer_view.setPlainText("")
        self.ocr_view.setPlainText(question)
        self.tabs.setCurrentIndex(0)
        self.meta_label.setText(f"{model} · 请求中…")
        self.set_busy(True, "模型思考中…")
        self.show_window(activate=activate)

    def set_ocr_text(self, text: str) -> None:
        self.ocr_view.setPlainText(text)

    def append_delta(self, delta: str) -> None:
        self._stream_text += delta
        if not self._flush_timer.isActive():
            self._flush_timer.start()
        self.progress.setVisible(False)

    def _flush_stream(self) -> None:
        if not self._stream_text:
            self._flush_timer.stop()
            return
        self.answer_view.setPlainText(self._stream_text)
        scrollbar = self.answer_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def finish_answer(self, answer: str, elapsed_sec: float, model: str) -> None:
        self._flush_timer.stop()
        self._stream_text = answer
        self._last_answer = answer
        self._set_markdown(answer)
        self.set_busy(False)
        self.meta_label.setText(f"{model} · {elapsed_sec:.1f}s · 请自行核对答案")
        self.set_status("回答完成")

    def fail(self, message: str, partial: str = "") -> None:
        self._flush_timer.stop()
        self.set_busy(False)
        self.tabs.setCurrentIndex(0)
        body = ""
        if partial.strip():
            body += partial.strip() + "\n\n"
        body += f"> **出错了**\n>\n> {message.strip().replace(chr(10), chr(10) + '> ')}"
        self._set_markdown(body)
        self.set_status("请求失败")
        self.meta_label.setText("检查设置后重试")

    def show_idle(self, message: str = "等待框选题目") -> None:
        self._flush_timer.stop()
        self.set_busy(False)
        self.set_status(message)
        self.meta_label.setText("答案由 AI 生成，请自行核对")

    def set_locked_state(self, locked: bool, interval_sec: float = 2.0) -> None:
        if locked:
            self.set_status(f"连续扫描中 · 每 {interval_sec:.1f}s 检查一次")
        else:
            self.set_status("连续扫描已暂停")

    def _set_markdown(self, text: str) -> None:
        try:
            self.answer_view.setMarkdown(text)
        except Exception:
            self.answer_view.setPlainText(text)
        scrollbar = self.answer_view.verticalScrollBar()
        scrollbar.setValue(0)

    def copy_current(self) -> None:
        if self.tabs.currentIndex() == 0:
            text = self._last_answer or self.answer_view.toPlainText()
        else:
            text = self.ocr_view.toPlainText()
        QApplication.clipboard().setText(text)
        self.copy_button.setText("已复制")
        self._copy_reset_timer.start(1300)

    def _on_continuous_toggled(self, checked: bool) -> None:
        self._refresh_continuous_style()
        self.continuous_toggled.emit(checked)

    # ------------------------------------------------------------- geometry
    def _apply_window_flags(self) -> None:
        visible = self.isVisible()
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        # Changing window flags may recreate the native window handle.
        self._capture_excluded = False
        if visible:
            self.show()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._capture_excluded:
            self._capture_excluded = exclude_window_from_capture(self)

    def _restore_geometry(self) -> None:
        stored = self._settings_store.value("window/geometry", QByteArray())
        restored = False
        if isinstance(stored, QByteArray) and not stored.isEmpty():
            restored = self.restoreGeometry(stored)
        if not restored or not self._is_on_any_screen():
            self.resize(self._settings.window_width, self._settings.window_height)
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self.move(
                    area.right() - self.width() - 32,
                    area.top() + 48,
                )

    def _is_on_any_screen(self) -> bool:
        frame = self.frameGeometry()
        return any(
            screen.availableGeometry().intersects(frame)
            for screen in QGuiApplication.screens()
        )

    def save_geometry(self) -> None:
        self._settings_store.setValue("window/geometry", self.saveGeometry())

    def resize_to(self, width: int, height: int) -> None:
        self.resize(
            max(self.minimumWidth(), int(width)),
            max(self.minimumHeight(), int(height)),
        )

    # -------------------------------------------------------------- events
    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.geometry_changed.emit()
    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched in {self.header, self.title_label, self.status_label}:
            if event.type() == QEvent.Type.MouseButtonPress:
                mouse = event
                if isinstance(mouse, QMouseEvent) and mouse.button() == Qt.MouseButton.LeftButton:
                    self._drag_offset = mouse.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    return True
            elif event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                mouse = event
                if isinstance(mouse, QMouseEvent):
                    self.move(mouse.globalPosition().toPoint() - self._drag_offset)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
        return super().eventFilter(watched, event)

    def _hide_by_user(self) -> None:
        self.save_geometry()
        self.hide()
        self.hidden_by_user.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._hide_by_user()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._allow_close:
            self.save_geometry()
            event.accept()
            return
        self.save_geometry()
        self.hide()
        self.hidden_by_user.emit()
        event.ignore()

    def prepare_quit(self) -> None:
        self._allow_close = True
        self.save_geometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._settings.window_width, self._settings.window_height)
