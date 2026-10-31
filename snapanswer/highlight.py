"""Optional click-through highlight around the locked OCR region."""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from .capture_exclusion import exclude_window_from_capture

ACCENT = QColor("#6ea8fe")


class RegionHighlight(QWidget):
    """Draws a thin frame just outside the selected region.

    The frame is intentionally outside the OCR crop and the native window is
    excluded from screen capture, so it cannot end up in the question image.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._region = QRect()
        self._screen_rect = QRect()
        self._capture_excluded = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def set_region(self, screen_rect: QRect, region: QRect) -> None:
        self._screen_rect = QRect(screen_rect)
        self._region = QRect(region)
        self.setGeometry(screen_rect)
        self.update()

    def show_highlight(self) -> None:
        if self._region.isEmpty():
            return
        self.show()
        if not self._capture_excluded:
            self._capture_excluded = exclude_window_from_capture(self)
        self.update()

    def hide_highlight(self) -> None:
        self.hide()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._capture_excluded:
            self._capture_excluded = exclude_window_from_capture(self)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._region.isEmpty() or self._screen_rect.isEmpty():
            return
        local = self._region.translated(-self._screen_rect.topLeft())
        # Draw outside the selected area so the crop stays clean even if capture
        # exclusion is unavailable.
        frame = local.adjusted(-2, -2, 2, 2).intersected(self.rect().adjusted(0, 0, -1, -1))
        if frame.width() < 2 or frame.height() < 2:
            frame = local.intersected(self.rect())
        if frame.isEmpty():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ACCENT, 2))
        painter.drawRoundedRect(frame, 5, 5)

        # Corner brackets make the region easier to spot on busy screens.
        length = 12
        painter.setPen(QPen(QColor(255, 255, 255, 225), 2))
        left, top, right, bottom = (
            frame.left(),
            frame.top(),
            frame.right(),
            frame.bottom(),
        )
        painter.drawLine(left, top, left + length, top)
        painter.drawLine(left, top, left, top + length)
        painter.drawLine(right, top, right - length, top)
        painter.drawLine(right, top, right, top + length)
        painter.drawLine(left, bottom, left + length, bottom)
        painter.drawLine(left, bottom, left, bottom - length)
        painter.drawLine(right, bottom, right - length, bottom)
        painter.drawLine(right, bottom, right, bottom - length)
        painter.end()
