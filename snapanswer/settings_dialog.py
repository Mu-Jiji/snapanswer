"""Configuration dialog."""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import Qt, QTime, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .config import (
    Config,
    is_local_endpoint,
    resolve_api_key,
    save_config,
    validate_config,
)

DIALOG_QSS = """
QDialog { background: #121720; color: #dbe4f3; }
QWidget { color: #dbe4f3; font-size: 12px; }
QLabel#hint { color: #8795ad; font-size: 11px; }
QLabel#section { color: #a9bfe2; font-weight: 600; }
QGroupBox {
    border: 1px solid #273041;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: 600;
    color: #b9c8e2;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit {
    background: #0d121a;
    border: 1px solid #2a3446;
    border-radius: 6px;
    padding: 5px 7px;
    color: #e6edf9;
    selection-background-color: #345f94;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus { border-color: #5b8fd0; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #151c28;
    border: 1px solid #2a3446;
    selection-background-color: #27456c;
}
QPushButton {
    background: #1d2635;
    border: 1px solid #2d3a4e;
    border-radius: 6px;
    padding: 6px 12px;
    color: #d7e2f4;
}
QPushButton:hover { background: #263349; }
QPushButton#save { background: #2b5f9e; border-color: #3d78bd; color: white; font-weight: 600; }
QPushButton#save:hover { background: #356fae; }
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent;
    color: #8493ab;
    padding: 8px 14px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: #e6efff; border-bottom: 2px solid #6ea8fe; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator {
    width: 15px; height: 15px;
    border: 1px solid #39465b; border-radius: 4px; background: #0d121a;
}
QCheckBox::indicator:checked { background: #4d84c7; border-color: #6ea8fe; }
QSlider::groove:horizontal { height: 4px; background: #263143; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #5b8fd0; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; margin: -6px 0; border-radius: 7px; background: #cfe1fb;
}
"""


PRESETS = [
    {
        "name": "DeepSeek 官方 API",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-flash",
        "env": "DEEPSEEK_API_KEY",
    },
    {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "env": "OPENAI_API_KEY",
    },
    {
        "name": "硅基流动 SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "env": "SILICONFLOW_API_KEY",
    },
    {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat-v3-0324",
        "env": "OPENROUTER_API_KEY",
    },
    {
        "name": "本地 Ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
        "env": "",
    },
    {
        "name": "本地 LM Studio",
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "local-model",
        "env": "",
    },
    {
        "name": "自定义 / 其他兼容服务",
        "base_url": "",
        "model": "",
        "env": "",
    },
]


class SettingsDialog(QDialog):
    def __init__(self, config: Config, config_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.config = config.copy()
        self.config_path = config_path
        self._loading = True
        self.setWindowTitle("SnapAnswer 设置")
        self.setMinimumSize(700, 700)
        self.resize(760, 780)
        self.setStyleSheet(DIALOG_QSS)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._build_ui()
        self._load_config()
        self._loading = False

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        title = QLabel("设置", self)
        title.setFont(QFont("Microsoft YaHei UI", 15, QFont.Weight.Bold))
        layout.addWidget(title)
        subtitle = QLabel("模型、OCR、统计与快捷键。配置保存在本机，不会上传。", self)
        subtitle.setObjectName("hint")
        layout.addWidget(subtitle)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_model_tab(), "模型")
        self.tabs.addTab(self._build_scan_tab(), "OCR 与扫描")
        self.tabs.addTab(self._build_usage_tab(), "统计")
        self.tabs.addTab(self._build_hotkey_tab(), "快捷键")
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        path_label = QLabel(str(self.config_path), self)
        path_label.setObjectName("hint")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bottom.addWidget(path_label, 1)
        open_button = QPushButton("打开所在文件夹", self)
        open_button.clicked.connect(self._open_config_folder)
        bottom.addWidget(open_button)
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        save = QPushButton("保存", self)
        save.setObjectName("save")
        save.setDefault(True)
        save.clicked.connect(self._save)
        bottom.addWidget(save)
        layout.addLayout(bottom)

    def _build_model_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(8)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("服务预设", page))
        self.preset_combo = QComboBox(page)
        for preset in PRESETS:
            self.preset_combo.addItem(preset["name"])
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        preset_row.addWidget(self.preset_combo, 1)
        layout.addLayout(preset_row)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)

        self.base_url_edit = QLineEdit(page)
        self.base_url_edit.setPlaceholderText("https://api.deepseek.com/v1")
        form.addRow("Base URL", self.base_url_edit)

        key_row = QHBoxLayout()
        self.api_key_edit = QLineEdit(page)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("留空则读取环境变量；本地模型可留空")
        key_row.addWidget(self.api_key_edit, 1)
        self.show_key_button = QPushButton("显示", page)
        self.show_key_button.setCheckable(True)
        self.show_key_button.setFixedWidth(52)
        self.show_key_button.toggled.connect(self._toggle_key_visibility)
        key_row.addWidget(self.show_key_button)
        form.addRow("API Key", key_row)

        self.env_edit = QLineEdit(page)
        self.env_edit.setPlaceholderText("例如 DEEPSEEK_API_KEY")
        form.addRow("Key 环境变量", self.env_edit)

        self.model_edit = QLineEdit(page)
        self.model_edit.setPlaceholderText("deepseek-flash")
        form.addRow("模型名称", self.model_edit)

        self.temperature_spin = QDoubleSpinBox(page)
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setDecimals(1)
        form.addRow("Temperature", self.temperature_spin)

        self.max_tokens_spin = QSpinBox(page)
        self.max_tokens_spin.setRange(64, 32768)
        self.max_tokens_spin.setSingleStep(128)
        form.addRow("最大输出 tokens", self.max_tokens_spin)

        self.timeout_spin = QDoubleSpinBox(page)
        self.timeout_spin.setRange(5.0, 300.0)
        self.timeout_spin.setSuffix(" 秒")
        form.addRow("请求超时", self.timeout_spin)

        self.stream_check = QCheckBox("流式输出（模型边生成边显示，推荐）", page)
        form.addRow("", self.stream_check)
        layout.addLayout(form)

        key_hint = QLabel(
            "密钥优先读取环境变量（推荐）；如果在本机保存，会以明文写入配置文件，请注意权限。",
            page,
        )
        key_hint.setObjectName("hint")
        key_hint.setWordWrap(True)
        layout.addWidget(key_hint)

        prompt_group = QGroupBox("系统提示词（高级）", page)
        prompt_layout = QVBoxLayout(prompt_group)
        self.prompt_edit = QPlainTextEdit(prompt_group)
        self.prompt_edit.setMinimumHeight(110)
        self.prompt_edit.setFont(QFont("Consolas", 9))
        prompt_layout.addWidget(self.prompt_edit)
        layout.addWidget(prompt_group, 1)
        return page

    def _build_scan_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(10)

        ocr_group = QGroupBox("OCR（RapidOCR · 本地离线）", page)
        ocr_form = QFormLayout(ocr_group)
        self.confidence_spin = QDoubleSpinBox(ocr_group)
        self.confidence_spin.setRange(0.0, 0.99)
        self.confidence_spin.setSingleStep(0.05)
        self.confidence_spin.setDecimals(2)
        ocr_form.addRow("最低置信度", self.confidence_spin)

        self.upscale_check = QCheckBox("小面积文本自动放大 2 倍", ocr_group)
        ocr_form.addRow("", self.upscale_check)

        self.max_side_spin = QSpinBox(ocr_group)
        self.max_side_spin.setRange(640, 6000)
        self.max_side_spin.setSingleStep(200)
        ocr_form.addRow("图像最长边", self.max_side_spin)

        self.padding_spin = QSpinBox(ocr_group)
        self.padding_spin.setRange(0, 80)
        self.padding_spin.setSuffix(" px")
        ocr_form.addRow("白边填充", self.padding_spin)
        layout.addWidget(ocr_group)

        behavior_group = QGroupBox("浮窗与连续扫描", page)
        form = QFormLayout(behavior_group)
        self.interval_spin = QDoubleSpinBox(behavior_group)
        self.interval_spin.setRange(0.8, 30.0)
        self.interval_spin.setSingleStep(0.2)
        self.interval_spin.setSuffix(" 秒")
        form.addRow("连续模式检查间隔", self.interval_spin)

        self.verify_check = QCheckBox("答题后自动复核 OCR（连续模式）", behavior_group)
        self.verify_check.setToolTip(
            "答案生成后重新截图并识别同一区域；只有文本与上次题目明显不同时才再次请求模型。"
        )
        form.addRow("", self.verify_check)

        self.verify_delay_spin = QDoubleSpinBox(behavior_group)
        self.verify_delay_spin.setRange(0.2, 10.0)
        self.verify_delay_spin.setSingleStep(0.2)
        self.verify_delay_spin.setSuffix(" 秒")
        form.addRow("复核等待时间", self.verify_delay_spin)

        self.verify_threshold_spin = QDoubleSpinBox(behavior_group)
        self.verify_threshold_spin.setRange(0.50, 1.00)
        self.verify_threshold_spin.setSingleStep(0.01)
        self.verify_threshold_spin.setDecimals(2)
        self.verify_threshold_spin.setToolTip(
            "新旧 OCR 文本的相似度低于该值时重新作答。1.00 表示只要文本有差异就重答；"
            "0.95 可忽略少量 OCR 噪声。"
        )
        form.addRow("复核差异阈值", self.verify_threshold_spin)

        self.highlight_check = QCheckBox("高亮当前框选的区域", behavior_group)
        self.highlight_check.setToolTip(
            "在锁定区域外沿显示一个鼠标可穿透的细边框，便于确认连续扫描范围。"
        )
        form.addRow("", self.highlight_check)

        self.hide_check = QCheckBox("手动框选时暂时隐藏浮窗", behavior_group)
        form.addRow("", self.hide_check)

        self.top_check = QCheckBox("浮窗始终置顶", behavior_group)
        form.addRow("", self.top_check)

        size_row = QHBoxLayout()
        self.window_width_spin = QSpinBox(behavior_group)
        self.window_width_spin.setRange(380, 1600)
        self.window_width_spin.setSingleStep(10)
        self.window_width_spin.setSuffix(" px")
        self.window_height_spin = QSpinBox(behavior_group)
        self.window_height_spin.setRange(260, 1600)
        self.window_height_spin.setSingleStep(10)
        self.window_height_spin.setSuffix(" px")
        size_row.addWidget(QLabel("宽", behavior_group))
        size_row.addWidget(self.window_width_spin)
        size_row.addSpacing(8)
        size_row.addWidget(QLabel("高", behavior_group))
        size_row.addWidget(self.window_height_spin)
        size_row.addStretch(1)
        form.addRow("浮窗大小", size_row)

        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, behavior_group)
        self.opacity_slider.setRange(35, 100)
        self.opacity_label = QLabel("97%", behavior_group)
        self.opacity_label.setFixedWidth(38)
        self.opacity_slider.valueChanged.connect(
            lambda value: self.opacity_label.setText(f"{value}%")
        )
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_label)
        form.addRow("浮窗不透明度", opacity_row)

        self.delay_spin = QSpinBox(behavior_group)
        self.delay_spin.setRange(0, 1500)
        self.delay_spin.setSingleStep(20)
        self.delay_spin.setSuffix(" ms")
        form.addRow("截图前等待", self.delay_spin)
        layout.addWidget(behavior_group)

        note = QLabel(
            "连续模式：框选一次后锁定该区域，每隔一段时间检查屏幕。每次答案生成后还会"
            "主动复核一遍 OCR，若与上次题目有明显出入，会把新文本再次交给模型作答。"
            "按 Esc 或隐藏浮窗可暂停。",
            page,
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_usage_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(10)

        group = QGroupBox("Token 与费用", page)
        form = QFormLayout(group)

        self.show_usage_check = QCheckBox("答题后显示 Token/费用小窗", group)
        self.show_usage_check.setToolTip(
            "在浮窗左下角外侧显示本次请求的输入/输出 token、耗时与估算费用。"
        )
        form.addRow("", self.show_usage_check)

        self.display_mode_combo = QComboBox(group)
        self.display_mode_combo.addItem("浮窗下方紧凑条", "strip")
        self.display_mode_combo.addItem("浮窗左下侧卡片", "card")
        form.addRow("显示样式", self.display_mode_combo)

        self.currency_combo = QComboBox(group)
        self.currency_combo.addItems(["CNY", "USD", "EUR"])
        form.addRow("计价货币", self.currency_combo)

        self.input_price_spin = QDoubleSpinBox(group)
        self.input_price_spin.setRange(0.0, 10000.0)
        self.input_price_spin.setDecimals(4)
        self.input_price_spin.setSingleStep(0.01)
        self.input_price_spin.setSuffix(" / 百万 tokens")
        self.input_price_spin.setToolTip("启用分时计价时，此价格用于高峰时段")
        form.addRow("输入单价", self.input_price_spin)

        self.output_price_spin = QDoubleSpinBox(group)
        self.output_price_spin.setRange(0.0, 10000.0)
        self.output_price_spin.setDecimals(4)
        self.output_price_spin.setSingleStep(0.01)
        self.output_price_spin.setSuffix(" / 百万 tokens")
        self.output_price_spin.setToolTip("启用分时计价时，此价格用于高峰时段")
        form.addRow("输出单价", self.output_price_spin)
        layout.addWidget(group)

        peak_group = QGroupBox("高低峰分时计价", page)
        peak_form = QFormLayout(peak_group)
        self.off_peak_check = QCheckBox("启用高峰 / 低谷不同单价", peak_group)
        self.off_peak_check.setToolTip(
            "高峰时段使用上面的输入/输出单价；高峰时段之外使用低谷单价。"
        )
        self.off_peak_check.toggled.connect(self._set_off_peak_enabled)
        peak_form.addRow("", self.off_peak_check)

        peak_time_row = QHBoxLayout()
        self.peak_start_edit = QTimeEdit(peak_group)
        self.peak_start_edit.setDisplayFormat("HH:mm")
        self.peak_start_edit.setMinimumWidth(86)
        self.peak_start_edit.setToolTip("开始晚于结束表示跨午夜；起止相同表示全天高峰")
        self.peak_end_edit = QTimeEdit(peak_group)
        self.peak_end_edit.setDisplayFormat("HH:mm")
        self.peak_end_edit.setMinimumWidth(86)
        self.peak_end_edit.setToolTip("高峰结束时间（不含）")
        peak_time_row.addWidget(self.peak_start_edit)
        peak_time_row.addWidget(QLabel("至", peak_group))
        peak_time_row.addWidget(self.peak_end_edit)
        peak_time_row.addStretch(1)
        peak_form.addRow("高峰时段", peak_time_row)

        lunch_row = QHBoxLayout()
        self.lunch_check = QCheckBox("午间低谷", peak_group)
        self.lunch_check.toggled.connect(self._set_lunch_enabled)
        self.lunch_start_edit = QTimeEdit(peak_group)
        self.lunch_start_edit.setDisplayFormat("HH:mm")
        self.lunch_start_edit.setMinimumWidth(86)
        self.lunch_end_edit = QTimeEdit(peak_group)
        self.lunch_end_edit.setDisplayFormat("HH:mm")
        self.lunch_end_edit.setMinimumWidth(86)
        lunch_row.addWidget(self.lunch_check)
        lunch_row.addWidget(self.lunch_start_edit)
        lunch_row.addWidget(QLabel("至", peak_group))
        lunch_row.addWidget(self.lunch_end_edit)
        lunch_row.addStretch(1)
        peak_form.addRow("", lunch_row)

        weekday_row = QHBoxLayout()
        self.weekday_checks: list[tuple[int, QCheckBox]] = []
        for index, label in enumerate(("一", "二", "三", "四", "五", "六", "日"), start=1):
            check = QCheckBox(label, peak_group)
            check.setToolTip(f"周{label}是否按高峰时段计价")
            self.weekday_checks.append((index, check))
            weekday_row.addWidget(check)
        weekday_row.addStretch(1)
        peak_form.addRow("高峰星期", weekday_row)

        self.holiday_edit = QLineEdit(peak_group)
        self.holiday_edit.setPlaceholderText("YYYY-MM-DD，逗号分隔，可留空")
        self.holiday_edit.setToolTip("这些日期全天按低谷计价，例如法定节假日")
        peak_form.addRow("额外低谷日期", self.holiday_edit)

        self.off_peak_input_spin = QDoubleSpinBox(peak_group)
        self.off_peak_input_spin.setRange(0.0, 10000.0)
        self.off_peak_input_spin.setDecimals(4)
        self.off_peak_input_spin.setSingleStep(0.01)
        self.off_peak_input_spin.setSuffix(" / 百万 tokens")
        peak_form.addRow("低谷输入单价", self.off_peak_input_spin)

        self.off_peak_output_spin = QDoubleSpinBox(peak_group)
        self.off_peak_output_spin.setRange(0.0, 10000.0)
        self.off_peak_output_spin.setDecimals(4)
        self.off_peak_output_spin.setSingleStep(0.01)
        self.off_peak_output_spin.setSuffix(" / 百万 tokens")
        peak_form.addRow("低谷输出单价", self.off_peak_output_spin)
        deepseek_button = QPushButton("应用 DeepSeek 默认价（deepseek-flash）", peak_group)
        deepseek_button.setToolTip(
            "填入缓存未命中参考价：高峰 2/8 元、低谷 1/4 元；周一至周五 "
            "09:00-12:00、14:00-18:00 为高峰。"
        )
        deepseek_button.clicked.connect(self._apply_deepseek_pricing)
        peak_form.addRow("", deepseek_button)
        layout.addWidget(peak_group)
        self._off_peak_widgets = [
            self.peak_start_edit,
            self.peak_end_edit,
            self.lunch_check,
            self.lunch_start_edit,
            self.lunch_end_edit,
            self.holiday_edit,
            self.off_peak_input_spin,
            self.off_peak_output_spin,
        ]
        self._off_peak_widgets.extend(check for _, check in self.weekday_checks)

        request_group = QGroupBox("API 用量", page)
        request_form = QFormLayout(request_group)
        self.request_usage_check = QCheckBox(
            "请求服务端返回 token usage（stream_options）", request_group
        )
        self.request_usage_check.setToolTip(
            "优先显示服务端返回的真实 token；如果服务端不支持该参数，程序会自动重试并改用本地估算。"
        )
        request_form.addRow("", self.request_usage_check)
        layout.addWidget(request_group)

        hint = QLabel(
            "费用 = 输入 token × 输入单价 + 输出 token × 输出单价。单价请按服务商计费页填写；"
            "留 0 时只显示 token，费用显示「未配置单价」。\n"
            "启用分时计价后，高峰时段使用上面的单价，其余时间使用低谷单价；"
            "高峰时段可以跨午夜（例如 22:00 至 08:00），按本机时间判断。",
            page,
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_hotkey_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(10)

        group = QGroupBox("全局快捷键", page)
        form = QFormLayout(group)
        self.hotkey_scan_edit = QLineEdit(group)
        form.addRow("框选题目", self.hotkey_scan_edit)
        self.hotkey_continuous_edit = QLineEdit(group)
        form.addRow("连续扫描开关", self.hotkey_continuous_edit)
        self.hotkey_show_edit = QLineEdit(group)
        form.addRow("显示浮窗", self.hotkey_show_edit)
        layout.addWidget(group)

        hint = QLabel(
            "语法示例：<ctrl>+<alt>+q、<ctrl>+<shift>+s。修改后保存即可生效；"
            "如果快捷键被其他程序占用，注册会失败，但托盘和浮窗按钮仍然可用。",
            page,
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        restore = QPushButton("恢复默认快捷键", page)
        restore.clicked.connect(self._restore_hotkeys)
        layout.addWidget(restore, 0, Qt.AlignmentFlag.AlignLeft)

        behavior = QLabel(
            "关闭浮窗只会隐藏到系统托盘。退出程序请使用托盘菜单的「退出」。",
            page,
        )
        behavior.setObjectName("hint")
        behavior.setWordWrap(True)
        layout.addWidget(behavior)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------- loading
    def _load_config(self) -> None:
        cfg = self.config
        self.base_url_edit.setText(cfg.llm.base_url)
        self.api_key_edit.setText(cfg.llm.api_key)
        self.env_edit.setText(cfg.llm.api_key_env)
        self.model_edit.setText(cfg.llm.model)
        self.temperature_spin.setValue(cfg.llm.temperature)
        self.max_tokens_spin.setValue(cfg.llm.max_tokens)
        self.timeout_spin.setValue(cfg.llm.timeout_sec)
        self.stream_check.setChecked(cfg.llm.stream)
        self.prompt_edit.setPlainText(cfg.llm.system_prompt)
        self._select_matching_preset()

        self.confidence_spin.setValue(cfg.ocr.min_confidence)
        self.upscale_check.setChecked(cfg.ocr.upscale_small)
        self.max_side_spin.setValue(cfg.ocr.max_side)
        self.padding_spin.setValue(cfg.ocr.padding)

        self.interval_spin.setValue(cfg.app.continuous_interval_sec)
        self.verify_check.setChecked(cfg.app.verify_after_answer)
        self.verify_delay_spin.setValue(cfg.app.verify_delay_sec)
        self.verify_threshold_spin.setValue(cfg.app.verify_similarity)
        self.highlight_check.setChecked(cfg.app.highlight_region)
        self.hide_check.setChecked(cfg.app.hide_on_capture)
        self.top_check.setChecked(cfg.app.always_on_top)
        self.window_width_spin.setValue(cfg.app.window_width)
        self.window_height_spin.setValue(cfg.app.window_height)
        self.opacity_slider.setValue(round(cfg.app.opacity * 100))
        self.opacity_label.setText(f"{round(cfg.app.opacity * 100)}%")
        self.delay_spin.setValue(cfg.app.capture_delay_ms)

        self.show_usage_check.setChecked(cfg.usage.show_panel)
        mode_index = self.display_mode_combo.findData(cfg.usage.display_mode)
        self.display_mode_combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        index = self.currency_combo.findText(cfg.usage.currency.upper())
        self.currency_combo.setCurrentIndex(index if index >= 0 else 0)
        self.input_price_spin.setValue(cfg.usage.input_per_million)
        self.output_price_spin.setValue(cfg.usage.output_per_million)
        self.off_peak_check.setChecked(cfg.usage.off_peak_enabled)
        start = QTime.fromString(cfg.usage.peak_start, "HH:mm")
        end = QTime.fromString(cfg.usage.peak_end, "HH:mm")
        if start.isValid():
            self.peak_start_edit.setTime(start)
        if end.isValid():
            self.peak_end_edit.setTime(end)
        self.lunch_check.setChecked(cfg.usage.lunch_break_enabled)
        lunch_start = QTime.fromString(cfg.usage.lunch_start, "HH:mm")
        lunch_end = QTime.fromString(cfg.usage.lunch_end, "HH:mm")
        if lunch_start.isValid():
            self.lunch_start_edit.setTime(lunch_start)
        if lunch_end.isValid():
            self.lunch_end_edit.setTime(lunch_end)
        for index, check in self.weekday_checks:
            check.setChecked(index in cfg.usage.peak_weekdays)
        self.holiday_edit.setText(", ".join(cfg.usage.off_peak_dates))
        self.off_peak_input_spin.setValue(cfg.usage.off_peak_input_per_million)
        self.off_peak_output_spin.setValue(cfg.usage.off_peak_output_per_million)
        self._set_off_peak_enabled(cfg.usage.off_peak_enabled)
        self.request_usage_check.setChecked(cfg.llm.request_usage)

        self.hotkey_scan_edit.setText(cfg.app.hotkey_scan)
        self.hotkey_continuous_edit.setText(cfg.app.hotkey_toggle_continuous)
        self.hotkey_show_edit.setText(cfg.app.hotkey_show)

    def _select_matching_preset(self) -> None:
        base = self.base_url_edit.text().strip().rstrip("/")
        matched = len(PRESETS) - 1
        for index, preset in enumerate(PRESETS):
            if preset["base_url"].rstrip("/") == base:
                matched = index
                break
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(matched)
        self.preset_combo.blockSignals(False)

    def _apply_preset(self, index: int) -> None:
        if self._loading or index < 0 or index >= len(PRESETS):
            return
        preset = PRESETS[index]
        if not preset["base_url"]:
            return
        self.base_url_edit.setText(preset["base_url"])
        self.model_edit.setText(preset["model"])
        self.env_edit.setText(preset["env"])

    def _set_off_peak_enabled(self, enabled: bool) -> None:
        for widget in self._off_peak_widgets:
            widget.setEnabled(enabled)
        if enabled:
            self._set_lunch_enabled(self.lunch_check.isChecked())

    def _set_lunch_enabled(self, enabled: bool) -> None:
        active = self.off_peak_check.isChecked() and enabled
        self.lunch_start_edit.setEnabled(active)
        self.lunch_end_edit.setEnabled(active)

    def _apply_deepseek_pricing(self) -> None:
        self.currency_combo.setCurrentText("CNY")
        self.input_price_spin.setValue(2.0)
        self.output_price_spin.setValue(8.0)
        self.off_peak_check.setChecked(True)
        self.off_peak_input_spin.setValue(1.0)
        self.off_peak_output_spin.setValue(4.0)
        self.peak_start_edit.setTime(QTime(9, 0))
        self.peak_end_edit.setTime(QTime(18, 0))
        self.lunch_check.setChecked(True)
        self.lunch_start_edit.setTime(QTime(12, 0))
        self.lunch_end_edit.setTime(QTime(14, 0))
        for index, check in self.weekday_checks:
            check.setChecked(index <= 5)
        self.holiday_edit.clear()
        self._set_off_peak_enabled(True)

    def _toggle_key_visibility(self, visible: bool) -> None:
        self.api_key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.show_key_button.setText("隐藏" if visible else "显示")

    def _restore_hotkeys(self) -> None:
        self.hotkey_scan_edit.setText("<ctrl>+<alt>+q")
        self.hotkey_continuous_edit.setText("<ctrl>+<alt>+c")
        self.hotkey_show_edit.setText("<ctrl>+<alt>+s")

    # -------------------------------------------------------------- saving
    def _save(self) -> None:
        cfg = self.config.copy()
        cfg.llm.base_url = self.base_url_edit.text().strip()
        cfg.llm.api_key = self.api_key_edit.text().strip()
        cfg.llm.api_key_env = self.env_edit.text().strip()
        cfg.llm.model = self.model_edit.text().strip()
        cfg.llm.temperature = self.temperature_spin.value()
        cfg.llm.max_tokens = self.max_tokens_spin.value()
        cfg.llm.timeout_sec = self.timeout_spin.value()
        cfg.llm.stream = self.stream_check.isChecked()
        cfg.llm.request_usage = self.request_usage_check.isChecked()
        cfg.llm.system_prompt = self.prompt_edit.toPlainText().strip()

        cfg.ocr.min_confidence = self.confidence_spin.value()
        cfg.ocr.upscale_small = self.upscale_check.isChecked()
        cfg.ocr.max_side = self.max_side_spin.value()
        cfg.ocr.padding = self.padding_spin.value()

        cfg.app.continuous_interval_sec = self.interval_spin.value()
        cfg.app.verify_after_answer = self.verify_check.isChecked()
        cfg.app.verify_delay_sec = self.verify_delay_spin.value()
        cfg.app.verify_similarity = self.verify_threshold_spin.value()
        cfg.app.highlight_region = self.highlight_check.isChecked()
        cfg.app.hide_on_capture = self.hide_check.isChecked()
        cfg.app.always_on_top = self.top_check.isChecked()
        cfg.app.window_width = self.window_width_spin.value()
        cfg.app.window_height = self.window_height_spin.value()
        cfg.app.opacity = self.opacity_slider.value() / 100.0
        cfg.app.capture_delay_ms = self.delay_spin.value()
        cfg.app.hotkey_scan = self.hotkey_scan_edit.text().strip()
        cfg.app.hotkey_toggle_continuous = self.hotkey_continuous_edit.text().strip()
        cfg.app.hotkey_show = self.hotkey_show_edit.text().strip()

        cfg.usage.show_panel = self.show_usage_check.isChecked()
        cfg.usage.display_mode = str(self.display_mode_combo.currentData())
        cfg.usage.currency = self.currency_combo.currentText()
        cfg.usage.input_per_million = self.input_price_spin.value()
        cfg.usage.output_per_million = self.output_price_spin.value()
        cfg.usage.off_peak_enabled = self.off_peak_check.isChecked()
        cfg.usage.off_peak_input_per_million = self.off_peak_input_spin.value()
        cfg.usage.off_peak_output_per_million = self.off_peak_output_spin.value()
        cfg.usage.peak_start = self.peak_start_edit.time().toString("HH:mm")
        cfg.usage.peak_end = self.peak_end_edit.time().toString("HH:mm")
        cfg.usage.lunch_break_enabled = self.lunch_check.isChecked()
        cfg.usage.lunch_start = self.lunch_start_edit.time().toString("HH:mm")
        cfg.usage.lunch_end = self.lunch_end_edit.time().toString("HH:mm")
        cfg.usage.peak_weekdays = [
            index for index, check in self.weekday_checks if check.isChecked()
        ]
        cfg.usage.off_peak_dates = [
            part
            for part in re.split(r"[,，;；\s]+", self.holiday_edit.text().strip())
            if part
        ]

        issues = validate_config(cfg)
        if issues:
            QMessageBox.warning(self, "配置有误", "\n".join(f"• {issue}" for issue in issues))
            return

        key = resolve_api_key(cfg)
        if not key and not is_local_endpoint(cfg.llm.base_url):
            answer = QMessageBox.question(
                self,
                "尚未配置 API Key",
                "当前没有检测到 API Key。云端服务通常会返回 401，是否仍要保存？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            save_config(cfg, self.config_path)
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", f"无法写入配置文件：\n{exc}")
            return
        self.config = cfg
        self.accept()

    def _open_config_folder(self) -> None:
        folder = Path(self.config_path).parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "无法打开", f"无法创建配置目录：\n{exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def result_config(self) -> Config:
        return self.config
