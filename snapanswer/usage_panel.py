"""Small anchored panel showing token usage and estimated cost."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .capture_exclusion import exclude_window_from_capture
from .usage import UsageSnapshot

PANEL_QSS = """
QWidget#usageRoot { background: transparent; }
QFrame#usageCard {
    background: #111722;
    border: 1px solid #2b3648;
    border-radius: 12px;
}
QLabel { color: #e5edf9; }
QLabel#usageTitle { font-size: 12px; font-weight: 700; color: #f2f7ff; }
QLabel#usageBadge {
    background: #1c3a31;
    border: 1px solid #2f745f;
    border-radius: 6px;
    color: #8fe5c4;
    font-size: 9px;
    padding: 2px 6px;
}
QLabel#usageBadge[estimated="true"] {
    background: #3a301b;
    border-color: #7b6428;
    color: #f2d58a;
}
QLabel#usageTokens { font-size: 11px; color: #b8c6dd; }
QLabel#usageCost { font-size: 17px; font-weight: 700; color: #8fc0ff; }
QLabel#usageMeta { font-size: 9px; color: #7888a3; }
QPushButton {
    background: #1b2636;
    border: 1px solid #2c3a50;
    border-radius: 6px;
    color: #c6d5ea;
    padding: 4px 9px;
    font-size: 10px;
}
QPushButton:hover { background: #25354b; }
QPushButton#usageClose {
    border: none;
    background: transparent;
    color: #8091aa;
    padding: 2px 5px;
}
QPushButton#usageClose:hover { color: #ffffff; background: #3b2530; }
"""


class UsagePanel(QWidget):
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
        self.setStyleSheet(PANEL_QSS)
        self._build_ui()
        self.setFixedWidth(336)
        self.adjustSize()

    def _build_ui(self) -> None:
        self.setObjectName("usageRoot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("usageCard")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 150))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(13, 10, 13, 11)
        layout.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel("本次用量", card)
        title.setObjectName("usageTitle")
        header.addWidget(title)
        self.source_badge = QLabel("估算", card)
        self.source_badge.setObjectName("usageBadge")
        self.source_badge.setProperty("estimated", "true")
        header.addWidget(self.source_badge)
        header.addStretch(1)
        self.close_button = QPushButton("×", card)
        self.close_button.setObjectName("usageClose")
        self.close_button.setToolTip("隐藏用量小窗")
        self.close_button.clicked.connect(self._hide_by_user)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        self.tokens_label = QLabel("输入 —  ·  输出 —\n合计 — tokens", card)
        self.tokens_label.setObjectName("usageTokens")
        layout.addWidget(self.tokens_label)

        self.cost_label = QLabel("估算费用 —", card)
        self.cost_label.setObjectName("usageCost")
        layout.addWidget(self.cost_label)

        self.meta_label = QLabel("完成一次答题后显示", card)
        self.meta_label.setObjectName("usageMeta")
        self.meta_label.setWordWrap(True)
        layout.addWidget(self.meta_label)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        self.refresh_button = QPushButton("刷新", card)
        self.refresh_button.setToolTip("按当前单价重新计算并刷新显示")
        self.refresh_button.clicked.connect(self.refresh_requested)
        footer.addWidget(self.refresh_button)
        footer.addStretch(1)
        self.source_note = QLabel("API 未返回时使用本地估算", card)
        self.source_note.setObjectName("usageMeta")
        footer.addWidget(self.source_note)
        layout.addLayout(footer)

    def set_snapshot(self, snapshot: UsageSnapshot | None) -> None:
        self._snapshot = snapshot
        if snapshot is None:
            self.tokens_label.setText("输入 —  ·  输出 —\n合计 — tokens")
            self.cost_label.setText("估算费用 —")
            self.meta_label.setText("完成一次答题后显示")
            self.source_badge.setText("—")
            self.source_badge.setProperty("estimated", "false")
            self.source_note.setText("完成一次答题后显示")
            self._repolish_badge()
            self.adjustSize()
            return

        usage = snapshot.usage.normalized()
        self.tokens_label.setText(
            f"输入 {usage.prompt_tokens:,}  ·  输出 {usage.completion_tokens:,}\n"
            f"合计 {usage.total_tokens:,} tokens"
        )
        self.cost_label.setText(f"估算费用 {snapshot.formatted_cost()}")
        if not snapshot.cost_configured:
            self.cost_label.setStyleSheet("color: #98a8c0;")
        else:
            self.cost_label.setStyleSheet("")
        estimated = usage.source != "api"
        self.source_badge.setText("估算" if estimated else "API 返回")
        self.source_badge.setProperty("estimated", "true" if estimated else "false")
        self._repolish_badge()
        source = "本地估算" if estimated else "API usage"
        period = snapshot.period_label
        meta = f"{snapshot.model} · {snapshot.elapsed_sec:.1f}s"
        if period:
            meta += f" · {period}"
        meta += f" · {source}"
        self.meta_label.setText(meta)
        self.source_note.setText(
            "API 未返回时使用本地估算" if estimated else "token 与费用仅供参考"
        )
        self.adjustSize()

    def _repolish_badge(self) -> None:
        self.source_badge.style().unpolish(self.source_badge)
        self.source_badge.style().polish(self.source_badge)
        self.source_badge.update()

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
        size = self.sizeHint()
        width, height = size.width(), self.height()
        x = main_rect.left() - width - 8
        y = main_rect.bottom() - height + 1
        if x < area.left():
            x = main_rect.left()
            y = main_rect.bottom() + 8
        x = max(area.left(), min(x, area.right() - width))
        y = max(area.top(), min(y, area.bottom() - height))
        self.move(QPoint(x, y))

    def snapshot(self) -> UsageSnapshot | None:
        return self._snapshot
