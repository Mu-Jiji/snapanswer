"""Generate docs/preview.png without touching the user's desktop.

Run with QT_QPA_PLATFORM=offscreen:
    python tools/make_preview.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QFontDatabase,
    QImage,
    QLinearGradient,
    QPainter,
)
from PyQt6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from snapanswer.answer_window import AnswerWindow  # noqa: E402
from snapanswer.config import AppSettings, UsageSettings  # noqa: E402
from snapanswer.usage import TokenUsage, snapshot_from_usage  # noqa: E402
from snapanswer.usage_panel import UsagePanel  # noqa: E402
from snapanswer.usage_strip import UsageStrip  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv[:1])
    font_path = Path(r"C:\Windows\Fonts\msyh.ttc")
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    window = AnswerWindow(AppSettings(), str(ROOT / "config.toml"))
    window.resize(570, 430)
    window.set_continuous_checked(True)
    window.set_ocr_text(
        "2. 在 Python 中，下列哪个表达式的结果是 3？\n"
        "A. 7 // 2\nB. 7 % 2\nC. 7 / 2\nD. 7 ** 2"
    )
    window.finish_answer(
        "**答案：A. `7 // 2`**\n\n"
        "解析：`//` 是向下取整的整除运算符，`7 // 2 = 3`。\n\n"
        "- `7 % 2` 的结果是余数 `1`\n"
        "- `7 / 2` 的结果是浮点数 `3.5`\n"
        "- `7 ** 2` 的结果是 `49`\n\n"
        "> 连续扫描已开启，题目变化时会自动更新答案。",
        2.4,
        "deepseek-flash",
    )
    window.set_status("复核完成 · 连续扫描中（每 2.0s）")
    window.show()
    app.processEvents()
    app.processEvents()

    shot = window.grab()
    padding = 52
    canvas = QImage(shot.width() + padding * 2, shot.height() + padding * 2, QImage.Format.Format_RGB32)
    gradient = QLinearGradient(0, 0, canvas.width(), canvas.height())
    gradient.setColorAt(0.0, QColor("#0a0f18"))
    gradient.setColorAt(0.55, QColor("#101b2d"))
    gradient.setColorAt(1.0, QColor("#1c2a40"))
    painter = QPainter(canvas)
    painter.fillRect(canvas.rect(), gradient)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QColor(110, 168, 254, 100))
    painter.setFont(QFont("Segoe UI", 12))
    title = "SnapAnswer · 截图答题浮窗"
    title_width = painter.fontMetrics().horizontalAdvance(title)
    icon = QImage(str(ROOT / "assets" / "icon.png"))
    icon_size = 26
    total_width = title_width + (icon_size + 8 if not icon.isNull() else 0)
    start_x = (canvas.width() - total_width) // 2
    if not icon.isNull():
        painter.drawImage(
            QRect(start_x, 13, icon_size, icon_size),
            icon,
        )
        start_x += icon_size + 8
    painter.drawText(
        QRect(start_x, 12, title_width + 2, 30),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        title,
    )
    painter.drawPixmap(QPoint(padding, padding), shot)
    painter.end()

    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    target = docs / "preview.png"
    canvas.save(str(target), "PNG")
    print(target)

    demo_snapshot = snapshot_from_usage(
        TokenUsage(1248, 326, 1574, "api"),
        model="deepseek-flash",
        elapsed_sec=2.4,
        settings=UsageSettings(
            show_panel=True,
            input_per_million=2.0,
            output_per_million=8.0,
            currency="CNY",
            off_peak_enabled=True,
            off_peak_input_per_million=1.0,
            off_peak_output_per_million=4.0,
        ),
        priced_at=datetime(2026, 10, 30, 2, 0),
    )
    panel = UsagePanel()
    panel.set_snapshot(demo_snapshot)
    panel.show()
    app.processEvents()
    panel_shot = panel.grab()
    panel_padding = 30
    panel_canvas = QImage(
        panel_shot.width() + panel_padding * 2,
        panel_shot.height() + panel_padding * 2 + 24,
        QImage.Format.Format_RGB32,
    )
    panel_gradient = QLinearGradient(0, 0, panel_canvas.width(), panel_canvas.height())
    panel_gradient.setColorAt(0.0, QColor("#0a0f18"))
    panel_gradient.setColorAt(1.0, QColor("#172338"))
    panel_painter = QPainter(panel_canvas)
    panel_painter.fillRect(panel_canvas.rect(), panel_gradient)
    panel_painter.setPen(QColor(140, 170, 220, 160))
    panel_painter.setFont(QFont("Segoe UI", 11))
    panel_painter.drawText(
        QRect(0, 8, panel_canvas.width(), 24),
        Qt.AlignmentFlag.AlignHCenter,
        "答题后 Token / 费用小窗",
    )
    panel_painter.drawPixmap(QPoint(panel_padding, panel_padding + 22), panel_shot)
    panel_painter.end()
    panel_target = docs / "usage-panel.png"
    panel_canvas.save(str(panel_target), "PNG")
    print(panel_target)

    strip = UsageStrip()
    strip.set_snapshot(demo_snapshot)
    strip.show()
    app.processEvents()
    strip_shot = strip.grab()
    strip_padding = 24
    strip_canvas = QImage(
        max(420, strip_shot.width() + strip_padding * 2),
        strip_shot.height() + strip_padding * 2 + 22,
        QImage.Format.Format_RGB32,
    )
    strip_gradient = QLinearGradient(0, 0, strip_canvas.width(), strip_canvas.height())
    strip_gradient.setColorAt(0.0, QColor("#0a0f18"))
    strip_gradient.setColorAt(1.0, QColor("#172338"))
    strip_painter = QPainter(strip_canvas)
    strip_painter.fillRect(strip_canvas.rect(), strip_gradient)
    strip_painter.setPen(QColor(140, 170, 220, 160))
    strip_painter.setFont(QFont("Segoe UI", 11))
    strip_painter.drawText(
        QRect(0, 6, strip_canvas.width(), 22),
        Qt.AlignmentFlag.AlignHCenter,
        "浮窗下方紧凑用量条",
    )
    strip_painter.drawPixmap(
        QPoint((strip_canvas.width() - strip_shot.width()) // 2, strip_padding + 20),
        strip_shot,
    )
    strip_painter.end()
    strip_target = docs / "usage-strip.png"
    strip_canvas.save(str(strip_target), "PNG")
    print(strip_target)

    strip.hide()
    panel.hide()
    window.prepare_quit()
    window.close()


if __name__ == "__main__":
    main()
