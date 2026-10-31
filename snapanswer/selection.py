"""Full-screen translucent region selector."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QWidget

from .imaging import crop_logical_region

ACCENT = QColor("#6ea8fe")
DIM = QColor(6, 10, 18, 150)


class RegionSelector(QWidget):
    """Shows a frozen screenshot and lets the user drag a rectangle."""

    selected = pyqtSignal(QImage, QRect)  # cropped image, absolute logical rect
    cancelled = pyqtSignal()

    def __init__(self, screenshot: QImage, screen_rect: QRect, parent: QWidget | None = None):
        super().__init__(parent)
        self._screenshot = screenshot
        self._screen_rect = screen_rect
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._selection = QRect()
        self._finished = False
        self._screen_name = ""
        screen = QGuiApplication.screenAt(screen_rect.center())
        if screen is not None:
            self._screen_name = screen.name()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(screen_rect)

    def open(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def selection_rect(self) -> QRect:
        return self._selection

    def _update_selection(self, point: QPoint) -> None:
        if self._origin is None:
            return
        self._selection = QRect(self._origin, point).normalized().intersected(self.rect())
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(self.rect(), self._screenshot)
        painter.fillRect(self.rect(), DIM)

        if not self._selection.isNull() and self._selection.width() > 0:
            painter.drawImage(self._selection, self._screenshot, self._source_rect())
            pen = QPen(ACCENT, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._selection.adjusted(1, 1, -1, -1))
            self._draw_handles(painter)
            self._draw_size_badge(painter)
        else:
            self._draw_hint(painter)

        if self._selection.isNull():
            self._draw_crosshair(painter)
        painter.end()

    def _source_rect(self) -> QRect:
        """Map the logical widget selection to the screenshot's pixel grid."""
        if self._screenshot.isNull() or self.width() <= 0 or self.height() <= 0:
            return QRect()
        sx = self._screenshot.width() / self.width()
        sy = self._screenshot.height() / self.height()
        return QRect(
            int(self._selection.left() * sx),
            int(self._selection.top() * sy),
            max(1, int(self._selection.width() * sx)),
            max(1, int(self._selection.height() * sy)),
        )

    def _draw_handles(self, painter: QPainter) -> None:
        painter.setBrush(ACCENT)
        painter.setPen(Qt.PenStyle.NoPen)
        size = 6
        for point in (
            self._selection.topLeft(),
            self._selection.topRight(),
            self._selection.bottomLeft(),
            self._selection.bottomRight(),
        ):
            painter.drawEllipse(point, size // 2, size // 2)

    def _draw_size_badge(self, painter: QPainter) -> None:
        text = f"{self._selection.width()} × {self._selection.height()}"
        font = QFont("Microsoft YaHei UI", 9)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 18
        height = metrics.height() + 8
        x = self._selection.left()
        y = self._selection.top() - height - 8
        if y < self.rect().top() + 8:
            y = self._selection.top() + 8
        if x + width > self.rect().right() - 8:
            x = self.rect().right() - width - 8
        badge = QRect(x, y, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 14, 22, 220))
        painter.drawRoundedRect(badge, 6, 6)
        painter.setPen(QColor("#e8eefc"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_hint(self, painter: QPainter) -> None:
        font = QFont("Microsoft YaHei UI", 12)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        title = "拖动鼠标框选题目区域"
        subtitle = "松开鼠标后自动识别 · 右键 / Esc 取消"
        width = max(metrics.horizontalAdvance(title), metrics.horizontalAdvance(subtitle)) + 48
        height = 76
        center_x = self.rect().center().x()
        top = self.rect().top() + max(40, int(self.height() * 0.16))
        card = QRect(center_x - width // 2, top, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(12, 17, 28, 232))
        painter.drawRoundedRect(card, 12, 12)
        painter.setPen(QPen(ACCENT, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), 11, 11)
        painter.setPen(QColor("#f2f6ff"))
        painter.drawText(
            card.adjusted(0, 10, 0, -34),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            title,
        )
        small = QFont("Microsoft YaHei UI", 9)
        painter.setFont(small)
        painter.setPen(QColor("#aab7d4"))
        painter.drawText(
            card.adjusted(0, 38, 0, -8),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            subtitle,
        )

    def _draw_crosshair(self, painter: QPainter) -> None:
        cursor = self.mapFromGlobal(self.cursor().pos())
        if not self.rect().contains(cursor):
            return
        pen = QPen(QColor(255, 255, 255, 90), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(self.rect().left(), cursor.y(), self.rect().right(), cursor.y())
        painter.drawLine(cursor.x(), self.rect().top(), cursor.x(), self.rect().bottom())

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._finished = False
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._selection = QRect(self._origin, self._origin)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._current = event.position().toPoint()
        if self._origin is not None:
            self._update_selection(self._current)
        else:
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        self._update_selection(event.position().toPoint())
        selection = self._selection.intersected(self.rect())
        if selection.width() < 12 or selection.height() < 12:
            self._origin = None
            self._current = None
            self._selection = QRect()
            self.update()
            return
        absolute = selection.translated(self._screen_rect.topLeft())
        crop = crop_logical_region(self._screenshot, self._screen_rect, absolute)
        if crop.isNull():
            self._origin = None
            self._selection = QRect()
            self.update()
            return
        self._finished = True
        self.hide()
        self.selected.emit(crop, absolute)
        self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._finished:
            self._finished = True
            self.cancelled.emit()
        super().closeEvent(event)

    def _cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.hide()
        self.cancelled.emit()
        self.close()
