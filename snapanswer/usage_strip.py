"""Compact one-line token/cost strip shown below the answer window."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .capture_exclusion import exclude_window_from_capture
from .usage import UsageSnapshot

STRIP_QSS = """
QWidget#stripRoot { background: transparent; }
QFrame#stripCard {
    background: #101722;
    border: 1px solid #2b3648;
    border-radius: 9px;
}
QLabel { color: #aebdd4; font-size: 10px; }
QLabel#stripTokens { color: #b8c6dd; }
QLabel#stripCost { color: #8fc0ff; font-weight: 700; font-size: 11px; }
QLabel#stripPeriod {
    color: #8fe5c4;
    background: #1c3a31;
    border: 1px solid #2f745f;
    border-radius: 5px;
    padding: 1px 5px;
    font-size: 9px;
}
QLabel#stripPeriod[period="off_peak"] {
    color: #f2d58a;
    background: #3a301b;
    border-color: #7b6428;
}
QPushButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    color: #8d9db5;
    padding: 2px 6px;
    font-size: 9px;
}
QPushButton:hover { background: #202b3d; color: #ffffff; }
QPushButton#stripClose:hover { background: #4a2730; color: #ffdce2; }
"""


class UsageStrip(QWidget):
    refresh_requested = pyqtSignal()
    hidden_by_user = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot: UsageSnapshot | None = None
        self._capture_excluded = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(STRIP_QSS)
        self.setFixedWidth(360)
        self._build_ui()
        self.adjustSize()

    def _build_ui(self) -> None:
        self.setObjectName("stripRoot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 5, 6, 6)
        outer.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("stripCard")
        outer.addWidget(card)

        row = QHBoxLayout(card)
        row.setContentsMargins(10, 3, 6, 3)
        row.setSpacing(8)
        self.tokens_label = QLabel("暂无用量", card)
        self.tokens_label.setObjectName("stripTokens")
        row.addWidget(self.tokens_label)
        self.cost_label = QLabel("费用 —", card)
        self.cost_label.setObjectName("stripCost")
        row.addWidget(self.cost_label)
        self.period_label = QLabel("", card)
        self.period_label.setObjectName("stripPeriod")
        self.period_label.hide()
        row.addWidget(self.period_label)
        row.addStretch(1)
        self.refresh_button = QPushButton("刷新", card)
        self.refresh_button.setToolTip("按当前单价重新计算并刷新")
        self.refresh_button.clicked.connect(self.refresh_requested)
        row.addWidget(self.refresh_button)
        self.close_button = QPushButton("×", card)
        self.close_button.setObjectName("stripClose")
        self.close_button.setToolTip("隐藏用量条")
        self.close_button.clicked.connect(self._hide_by_user)
        row.addWidget(self.close_button)

    def set_snapshot(self, snapshot: UsageSnapshot | None) -> None:
        self._snapshot = snapshot
        if snapshot is None:
            self.tokens_label.setText("暂无用量")
            self.cost_label.setText("费用 —")
            self.period_label.hide()
            self.setToolTip("完成一次答题后显示 token 与费用")
            self.adjustSize()
            return

        usage = snapshot.usage.normalized()
        self.tokens_label.setText(f"{usage.total_tokens:,} tok")
        if snapshot.cost_configured:
            self.cost_label.setText(snapshot.formatted_cost())
        else:
            self.cost_label.setText("费用 —")
        period = snapshot.period_label
        if period:
            self.period_label.setText("高峰" if snapshot.period == "peak" else "低谷")
            self.period_label.setProperty("period", snapshot.period)
            self.period_label.style().unpolish(self.period_label)
            self.period_label.style().polish(self.period_label)
            self.period_label.show()
        else:
            self.period_label.hide()
        source = "API usage" if usage.source == "api" else "本地估算"
        self.setToolTip(
            f"输入 {usage.prompt_tokens:,} · 输出 {usage.completion_tokens:,} · "
            f"合计 {usage.total_tokens:,}\n"
            f"{snapshot.model} · {snapshot.elapsed_sec:.1f}s · {source}"
            + (f" · {period}" if period else "")
        )
        self.adjustSize()

    def _hide_by_user(self) -> None:
        self.hide()
        self.hidden_by_user.emit()

    def show_panel(self) -> None:
        was_visible = self.isVisible()
        if not was_visible:
            self.show()
        if not self._capture_excluded:
            self._capture_excluded = exclude_window_from_capture(self)
        if not was_visible:
            self.raise_()

    def hide_panel(self) -> None:
        self.hide()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._capture_excluded:
            self._capture_excluded = exclude_window_from_capture(self)

    def follow(self, main_rect: QRect) -> None:
        if main_rect.isEmpty():
            return
        screen = QGuiApplication.screenAt(main_rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        width = self.width()
        height = self.height()
        # frameGeometry includes the translucent shadow margin; align with the
        # visible card's left edge, like the red guide box in the design.
        x = main_rect.left() + 12
        y = main_rect.bottom() + 8
        if y + height > area.bottom():
            y = main_rect.top() - height - 8
        x = max(area.left(), min(x, area.right() - width))
        y = max(area.top(), min(y, area.bottom() - height))
        self.move(QPoint(x, y))
