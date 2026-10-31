from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest

from snapanswer.selection import RegionSelector


def test_region_selector_emits_cropped_image(qtbot) -> None:
    screenshot = QImage(800, 600, QImage.Format.Format_RGB32)
    screenshot.fill(QColor("#ffffff"))
    screen_rect = QRect(0, 0, 800, 600)
    selector = RegionSelector(screenshot, screen_rect)
    qtbot.addWidget(selector)
    selector.open()
    QTest.qWait(50)

    with qtbot.waitSignal(selector.selected, timeout=1500) as blocker:
        QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        QTest.mouseMove(selector, QPoint(300, 250))
        QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(300, 250))

    crop, rect = blocker.args
    assert 199 <= crop.width() <= 202
    assert 149 <= crop.height() <= 152
    assert rect.left() == 100
    assert rect.top() == 100


def test_region_selector_escape_cancels(qtbot) -> None:
    screenshot = QImage(400, 300, QImage.Format.Format_RGB32)
    screenshot.fill(QColor("#ffffff"))
    selector = RegionSelector(screenshot, QRect(0, 0, 400, 300))
    qtbot.addWidget(selector)
    selector.open()
    QTest.qWait(30)
    with qtbot.waitSignal(selector.cancelled, timeout=1000):
        QTest.keyClick(selector, Qt.Key.Key_Escape)
