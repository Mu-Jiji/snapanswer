from pathlib import Path

from PyQt6.QtCore import QRect, Qt, QTime
from PyQt6.QtWidgets import QApplication

from snapanswer.answer_window import AnswerWindow
from snapanswer.app import format_hotkey
from snapanswer.config import AppSettings, Config, UsageSettings, load_config
from snapanswer.highlight import RegionHighlight
from snapanswer.settings_dialog import SettingsDialog
from snapanswer.usage import TokenUsage, snapshot_from_usage
from snapanswer.usage_panel import UsagePanel
from snapanswer.usage_strip import UsageStrip


def test_answer_window_renders_stream_and_copy(qtbot, tmp_path: Path) -> None:
    window = AnswerWindow(AppSettings(), str(tmp_path / "config.toml"))
    qtbot.addWidget(window)
    window.show_window()

    window.begin_request("题目：1+1=?", "test-model")
    window.append_delta("答案：2")
    qtbot.wait(120)
    assert "答案：2" in window.answer_view.toPlainText()

    window.finish_answer("**答案：** 2\n\n解析：一加一等于二。", 1.2, "test-model")
    assert "答案" in window.answer_view.toPlainText()
    window.copy_current()
    assert QApplication.clipboard().text().startswith("**答案：**")

    window.set_ocr_text("识别原文")
    assert window.ocr_view.toPlainText() == "识别原文"
    window.prepare_quit()
    window.close()


def test_answer_window_error_state(qtbot, tmp_path: Path) -> None:
    window = AnswerWindow(AppSettings(), str(tmp_path / "config.toml"))
    qtbot.addWidget(window)
    window.fail("网络错误")
    assert "出错了" in window.answer_view.toPlainText()
    assert not window.progress.isVisible()
    window.prepare_quit()
    window.close()


def test_settings_dialog_loads_values(qtbot) -> None:
    cfg = Config()
    cfg.llm.model = "demo-model"
    cfg.llm.api_key = "sk-secret"
    cfg.app.opacity = 0.82
    dialog = SettingsDialog(cfg, Path("/tmp/config.toml"))
    qtbot.addWidget(dialog)
    assert dialog.model_edit.text() == "demo-model"
    assert dialog.api_key_edit.echoMode().name == "Password"
    assert dialog.opacity_slider.value() == 82
    assert dialog.verify_check.isChecked() is True
    assert dialog.verify_delay_spin.value() == 1.2
    assert dialog.verify_threshold_spin.value() == 0.95
    dialog.reject()


def test_format_hotkey() -> None:
    assert format_hotkey("<ctrl>+<alt>+q") == "Ctrl+Alt+Q"
    assert format_hotkey("<ctrl>+<shift>+s") == "Ctrl+Shift+S"


def test_settings_dialog_saves_verification_options(qtbot, tmp_path: Path) -> None:
    cfg = Config()
    cfg.llm.base_url = "http://127.0.0.1:11434/v1"
    cfg.llm.model = "local-model"
    path = tmp_path / "config.toml"
    dialog = SettingsDialog(cfg, path)
    qtbot.addWidget(dialog)

    dialog.verify_check.setChecked(False)
    dialog.verify_delay_spin.setValue(2.5)
    dialog.verify_threshold_spin.setValue(1.0)
    dialog._save()

    loaded, _ = load_config(path)
    assert loaded.app.verify_after_answer is False
    assert loaded.app.verify_delay_sec == 2.5
    assert loaded.app.verify_similarity == 1.0
    assert loaded.app.highlight_region is False
    assert loaded.app.window_width == 540


def test_settings_dialog_saves_usage_options(qtbot, tmp_path: Path) -> None:
    cfg = Config()
    cfg.llm.base_url = "http://127.0.0.1:11434/v1"
    cfg.llm.model = "local-model"
    path = tmp_path / "config.toml"
    dialog = SettingsDialog(cfg, path)
    qtbot.addWidget(dialog)

    dialog.show_usage_check.setChecked(True)
    dialog.display_mode_combo.setCurrentIndex(
        dialog.display_mode_combo.findData("card")
    )
    dialog.currency_combo.setCurrentText("USD")
    dialog.input_price_spin.setValue(0.15)
    dialog.output_price_spin.setValue(0.6)
    dialog.off_peak_check.setChecked(True)
    dialog.peak_start_edit.setTime(QTime(22, 0))
    dialog.peak_end_edit.setTime(QTime(8, 0))
    dialog.lunch_check.setChecked(False)
    dialog.lunch_start_edit.setTime(QTime(12, 30))
    dialog.lunch_end_edit.setTime(QTime(13, 30))
    for index, check in dialog.weekday_checks:
        check.setChecked(index in {1, 3, 5})
    dialog.holiday_edit.setText("2026-10-01, 2026-10-02")
    dialog.off_peak_input_spin.setValue(0.05)
    dialog.off_peak_output_spin.setValue(0.2)
    dialog.request_usage_check.setChecked(False)
    dialog.highlight_check.setChecked(True)
    dialog.window_width_spin.setValue(620)
    dialog.window_height_spin.setValue(520)
    dialog._save()

    loaded, _ = load_config(path)
    assert loaded.usage.show_panel is True
    assert loaded.usage.display_mode == "card"
    assert loaded.usage.currency == "USD"
    assert loaded.usage.input_per_million == 0.15
    assert loaded.usage.output_per_million == 0.6
    assert loaded.usage.off_peak_enabled is True
    assert loaded.usage.peak_start == "22:00"
    assert loaded.usage.peak_end == "08:00"
    assert loaded.usage.lunch_break_enabled is False
    assert loaded.usage.lunch_start == "12:30"
    assert loaded.usage.lunch_end == "13:30"
    assert loaded.usage.peak_weekdays == [1, 3, 5]
    assert loaded.usage.off_peak_dates == ["2026-10-01", "2026-10-02"]
    assert loaded.usage.off_peak_input_per_million == 0.05
    assert loaded.usage.off_peak_output_per_million == 0.2
    assert loaded.llm.request_usage is False
    assert loaded.app.highlight_region is True
    assert loaded.app.window_width == 620
    assert loaded.app.window_height == 520


def test_answer_window_resize_to_clamps_minimum(qtbot, tmp_path: Path) -> None:
    window = AnswerWindow(AppSettings(), str(tmp_path / "config.toml"))
    qtbot.addWidget(window)
    window.resize_to(640, 500)
    assert (window.width(), window.height()) == (640, 500)
    window.resize_to(100, 100)
    assert window.width() >= window.minimumWidth()
    assert window.height() >= window.minimumHeight()
    window.prepare_quit()
    window.close()


def test_region_highlight_paints_and_ignores_input(qtbot) -> None:
    highlight = RegionHighlight()
    qtbot.addWidget(highlight)
    highlight.set_region(QRect(0, 0, 600, 400), QRect(100, 80, 300, 180))
    highlight.show_highlight()
    qtbot.wait(30)
    shot = highlight.grab()
    assert shot.width() == 600
    assert shot.height() == 400
    assert highlight.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    highlight.hide_highlight()


def test_usage_panel_renders_snapshot(qtbot) -> None:
    panel = UsagePanel()
    qtbot.addWidget(panel)
    snapshot = snapshot_from_usage(
        TokenUsage(1200, 300, 1500, "api"),
        model="deepseek-chat",
        elapsed_sec=2.4,
        settings=UsageSettings(
            input_per_million=0.5,
            output_per_million=2.0,
            currency="CNY",
        ),
    )
    panel.set_snapshot(snapshot)
    assert "1,200" in panel.tokens_label.text()
    assert "1,500" in panel.tokens_label.text()
    assert "¥" in panel.cost_label.text()
    assert "deepseek-chat" in panel.meta_label.text()

    refreshed: list[bool] = []
    panel.refresh_requested.connect(lambda: refreshed.append(True))
    panel.refresh_button.click()
    assert refreshed == [True]


def test_usage_strip_renders_period_and_refresh(qtbot) -> None:
    from datetime import datetime

    strip = UsageStrip()
    qtbot.addWidget(strip)
    snapshot = snapshot_from_usage(
        TokenUsage(1200, 300, 1500, "api"),
        model="deepseek-flash",
        elapsed_sec=2.4,
        settings=UsageSettings(
            input_per_million=2.0,
            output_per_million=8.0,
            off_peak_enabled=True,
            off_peak_input_per_million=1.0,
            off_peak_output_per_million=4.0,
        ),
        priced_at=datetime(2026, 10, 30, 2, 0),
    )
    strip.set_snapshot(snapshot)
    assert "1,500" in strip.tokens_label.text()
    assert "¥" in strip.cost_label.text()
    assert strip.period_label.text() == "低谷"
    assert "输入 1,200" in strip.toolTip()

    refreshed: list[bool] = []
    strip.refresh_requested.connect(lambda: refreshed.append(True))
    strip.refresh_button.click()
    assert refreshed == [True]
