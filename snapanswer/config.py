"""Configuration loading, validation, and persistence.

The public config file intentionally contains no secrets by default.  An API key
may be stored in it for convenience, but the recommended approach is to point
``llm.api_key_env`` at an environment variable instead.
"""

from __future__ import annotations

import contextlib
import copy
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - only reached on Python 3.10
    import tomli as tomllib

APP_NAME = "SnapAnswer"
DEFAULT_CONFIG_ENV = "SNAPANSWER_CONFIG"

DEFAULT_SYSTEM_PROMPT = """\
你是一位严谨、简洁的答题助手。用户会给你一段由 OCR 识别得到的题目文本，其中可能夹杂识别错误、换行或多余字符。

请按以下要求回答：
1. 先判断题意并纠正明显的 OCR 错误，再作答。
2. 第一行以「答案：」开头，直接给出最终答案；选择题写出选项字母和内容。
3. 空一行后写「解析：」，用 2-5 句话说明关键步骤或理由。
4. 计算题保留必要步骤，最终结果放在答案中。
5. 如果题目缺少关键条件，明确说明缺少什么，不要编造条件。
6. 使用简体中文；公式用清晰的文本或 LaTeX 行内写法。"""


class ConfigError(ValueError):
    """Raised when a configuration file cannot be interpreted."""


@dataclass
class AppSettings:
    hotkey_scan: str = "<ctrl>+<alt>+q"
    hotkey_toggle_continuous: str = "<ctrl>+<alt>+c"
    hotkey_show: str = "<ctrl>+<alt>+s"
    continuous: bool = False
    continuous_interval_sec: float = 2.0
    # After each answer, take another OCR pass of the locked region and compare
    # it with the text that produced the answer.  Only a material difference
    # triggers another model request.
    verify_after_answer: bool = True
    verify_delay_sec: float = 1.2
    verify_similarity: float = 0.95
    highlight_region: bool = False
    hide_on_capture: bool = True
    always_on_top: bool = True
    opacity: float = 0.97
    capture_delay_ms: int = 160
    window_width: int = 540
    window_height: int = 460


@dataclass
class OcrSettings:
    engine: str = "rapidocr"
    min_confidence: float = 0.35
    upscale_small: bool = True
    max_side: int = 2600
    padding: int = 8


@dataclass
class LlmSettings:
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    api_key_env: str = "DEEPSEEK_API_KEY"
    model: str = "deepseek-flash"
    temperature: float = 0.2
    max_tokens: int = 1400
    timeout_sec: float = 60.0
    stream: bool = True
    request_usage: bool = True
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class UsageSettings:
    show_panel: bool = False
    # "strip" = compact bar under the answer window; "card" = side card.
    display_mode: str = "strip"
    input_per_million: float = 2.0
    output_per_million: float = 8.0
    currency: str = "CNY"
    off_peak_enabled: bool = True
    off_peak_input_per_million: float = 1.0
    off_peak_output_per_million: float = 4.0
    # Local-time peak window. A start later than end wraps over midnight.
    # Defaults follow DeepSeek pricing: Beijing time, weekdays 09:00-12:00 and
    # 14:00-18:00 are peak; lunch, weekends and dates below are off-peak.
    peak_start: str = "09:00"
    peak_end: str = "18:00"
    lunch_break_enabled: bool = True
    lunch_start: str = "12:00"
    lunch_end: str = "14:00"
    peak_weekdays: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])
    off_peak_dates: list[str] = field(default_factory=list)


@dataclass
class Config:
    app: AppSettings = field(default_factory=AppSettings)
    ocr: OcrSettings = field(default_factory=OcrSettings)
    llm: LlmSettings = field(default_factory=LlmSettings)
    usage: UsageSettings = field(default_factory=UsageSettings)

    def copy(self) -> Config:
        return copy.deepcopy(self)


def user_config_dir() -> Path:
    """Return the per-user config directory for the current platform."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME.lower()


def project_config_path() -> Path:
    """Config path used when running from a git checkout."""
    return Path(__file__).resolve().parent.parent / "config.toml"


def default_config_path() -> Path:
    return user_config_dir() / "config.toml"


def fallback_config_path() -> Path:
    """Writable fallback for locked-down environments."""
    return Path(tempfile.gettempdir()) / "snapanswer-data" / "config.toml"


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env_path = os.environ.get(DEFAULT_CONFIG_ENV)
    if env_path:
        return Path(env_path).expanduser().resolve()
    repo_path = project_config_path()
    if repo_path.exists():
        return repo_path
    return default_config_path()


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] 必须是一个表（table）")
    return value


def _str(table: dict[str, Any], key: str, default: str, prefix: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{prefix}{key} 必须是字符串")
    return value


def _bool(table: dict[str, Any], key: str, default: bool, prefix: str) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{prefix}{key} 必须是 true 或 false")
    return value


def _int(table: dict[str, Any], key: str, default: int, prefix: str) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{prefix}{key} 必须是整数")
    return value


def _float(table: dict[str, Any], key: str, default: float, prefix: str) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{prefix}{key} 必须是数字")
    return float(value)


def _clock(table: dict[str, Any], key: str, default: str, prefix: str) -> str:
    value = _str(table, key, default, prefix).strip()
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ConfigError(f"{prefix}{key} 必须是 HH:MM 格式的时间，例如 08:30") from exc
    return parsed.strftime("%H:%M")


def _choice(
    table: dict[str, Any],
    key: str,
    default: str,
    choices: set[str],
    prefix: str,
) -> str:
    value = _str(table, key, default, prefix).strip().lower()
    if value not in choices:
        raise ConfigError(f"{prefix}{key} 必须是 {' / '.join(sorted(choices))}")
    return value


def _str_list(
    table: dict[str, Any], key: str, default: list[str], prefix: str
) -> list[str]:
    value = table.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{prefix}{key} 必须是字符串数组")
    return list(value)


def _weekday_list(table: dict[str, Any], prefix: str) -> list[int]:
    value = table.get("peak_weekdays", [1, 2, 3, 4, 5])
    if not isinstance(value, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    ):
        raise ConfigError(f"{prefix}peak_weekdays 必须是整数数组（1=周一 … 7=周日）")
    days = sorted(set(value))
    if any(day < 1 or day > 7 for day in days):
        raise ConfigError(f"{prefix}peak_weekdays 只能是 1-7")
    return days


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _date_list(table: dict[str, Any], prefix: str) -> list[str]:
    values = _str_list(table, "off_peak_dates", [], prefix)
    normalized: list[str] = []
    for value in values:
        try:
            normalized.append(date.fromisoformat(value).isoformat())
        except ValueError as exc:
            raise ConfigError(
                f"{prefix}off_peak_dates 中的日期必须是 YYYY-MM-DD：{value}"
            ) from exc
    return normalized


def config_from_dict(data: dict[str, Any]) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("配置文件顶层必须是表（table）")
    app_data = _table(data, "app")
    ocr_data = _table(data, "ocr")
    llm_data = _table(data, "llm")

    app = AppSettings(
        hotkey_scan=_str(app_data, "hotkey_scan", AppSettings.hotkey_scan, "[app]."),
        hotkey_toggle_continuous=_str(
            app_data,
            "hotkey_toggle_continuous",
            AppSettings.hotkey_toggle_continuous,
            "[app].",
        ),
        hotkey_show=_str(app_data, "hotkey_show", AppSettings.hotkey_show, "[app]."),
        continuous=_bool(app_data, "continuous", AppSettings.continuous, "[app]."),
        continuous_interval_sec=_float(
            app_data, "continuous_interval_sec", AppSettings.continuous_interval_sec, "[app]."
        ),
        verify_after_answer=_bool(
            app_data, "verify_after_answer", AppSettings.verify_after_answer, "[app]."
        ),
        verify_delay_sec=_float(
            app_data, "verify_delay_sec", AppSettings.verify_delay_sec, "[app]."
        ),
        verify_similarity=_float(
            app_data, "verify_similarity", AppSettings.verify_similarity, "[app]."
        ),
        highlight_region=_bool(
            app_data, "highlight_region", AppSettings.highlight_region, "[app]."
        ),
        hide_on_capture=_bool(
            app_data, "hide_on_capture", AppSettings.hide_on_capture, "[app]."
        ),
        always_on_top=_bool(
            app_data, "always_on_top", AppSettings.always_on_top, "[app]."
        ),
        opacity=_float(app_data, "opacity", AppSettings.opacity, "[app]."),
        capture_delay_ms=_int(
            app_data, "capture_delay_ms", AppSettings.capture_delay_ms, "[app]."
        ),
        window_width=_int(app_data, "window_width", AppSettings.window_width, "[app]."),
        window_height=_int(
            app_data, "window_height", AppSettings.window_height, "[app]."
        ),
    )

    ocr = OcrSettings(
        engine=_str(ocr_data, "engine", OcrSettings.engine, "[ocr]."),
        min_confidence=_float(
            ocr_data, "min_confidence", OcrSettings.min_confidence, "[ocr]."
        ),
        upscale_small=_bool(
            ocr_data, "upscale_small", OcrSettings.upscale_small, "[ocr]."
        ),
        max_side=_int(ocr_data, "max_side", OcrSettings.max_side, "[ocr]."),
        padding=_int(ocr_data, "padding", OcrSettings.padding, "[ocr]."),
    )

    headers_data = llm_data.get("headers", {})
    if not isinstance(headers_data, dict):
        raise ConfigError("[llm.headers] 必须是一个表（table）")
    headers = {}
    for key, value in headers_data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ConfigError("[llm.headers] 的键和值都必须是字符串")
        headers[key] = value

    llm = LlmSettings(
        base_url=_str(llm_data, "base_url", LlmSettings.base_url, "[llm]."),
        api_key=_str(llm_data, "api_key", LlmSettings.api_key, "[llm]."),
        api_key_env=_str(llm_data, "api_key_env", LlmSettings.api_key_env, "[llm]."),
        model=_str(llm_data, "model", LlmSettings.model, "[llm]."),
        temperature=_float(
            llm_data, "temperature", LlmSettings.temperature, "[llm]."
        ),
        max_tokens=_int(llm_data, "max_tokens", LlmSettings.max_tokens, "[llm]."),
        timeout_sec=_float(
            llm_data, "timeout_sec", LlmSettings.timeout_sec, "[llm]."
        ),
        stream=_bool(llm_data, "stream", LlmSettings.stream, "[llm]."),
        request_usage=_bool(
            llm_data, "request_usage", LlmSettings.request_usage, "[llm]."
        ),
        system_prompt=_str(
            llm_data, "system_prompt", LlmSettings.system_prompt, "[llm]."
        ),
        headers=headers,
    )

    usage_data = _table(data, "usage")
    usage = UsageSettings(
        show_panel=_bool(
            usage_data, "show_panel", UsageSettings.show_panel, "[usage]."
        ),
        display_mode=_choice(
            usage_data,
            "display_mode",
            UsageSettings.display_mode,
            {"strip", "card"},
            "[usage].",
        ),
        input_per_million=_float(
            usage_data,
            "input_per_million",
            UsageSettings.input_per_million,
            "[usage].",
        ),
        output_per_million=_float(
            usage_data,
            "output_per_million",
            UsageSettings.output_per_million,
            "[usage].",
        ),
        currency=_str(usage_data, "currency", UsageSettings.currency, "[usage]."),
        off_peak_enabled=_bool(
            usage_data,
            "off_peak_enabled",
            UsageSettings.off_peak_enabled,
            "[usage].",
        ),
        off_peak_input_per_million=_float(
            usage_data,
            "off_peak_input_per_million",
            UsageSettings.off_peak_input_per_million,
            "[usage].",
        ),
        off_peak_output_per_million=_float(
            usage_data,
            "off_peak_output_per_million",
            UsageSettings.off_peak_output_per_million,
            "[usage].",
        ),
        peak_start=_clock(
            usage_data, "peak_start", UsageSettings.peak_start, "[usage]."
        ),
        peak_end=_clock(usage_data, "peak_end", UsageSettings.peak_end, "[usage]."),
        lunch_break_enabled=_bool(
            usage_data,
            "lunch_break_enabled",
            UsageSettings.lunch_break_enabled,
            "[usage].",
        ),
        lunch_start=_clock(
            usage_data, "lunch_start", UsageSettings.lunch_start, "[usage]."
        ),
        lunch_end=_clock(
            usage_data, "lunch_end", UsageSettings.lunch_end, "[usage]."
        ),
        peak_weekdays=_weekday_list(usage_data, "[usage]."),
        off_peak_dates=_date_list(usage_data, "[usage]."),
    )

    cfg = Config(app=app, ocr=ocr, llm=llm, usage=usage)
    normalize_config(cfg)
    return cfg


def apply_deepseek_defaults(cfg: Config) -> bool:
    """Fill the documented deepseek-flash reference prices for old configs.

    Only runs when the endpoint is DeepSeek and no input/output price has been
    configured, so an explicit user price is never overwritten.
    """
    if "api.deepseek.com" not in cfg.llm.base_url:
        return False
    if cfg.usage.currency.upper() != "CNY":
        return False
    if cfg.usage.input_per_million or cfg.usage.output_per_million:
        return False
    cfg.usage.input_per_million = 2.0
    cfg.usage.output_per_million = 8.0
    cfg.usage.off_peak_enabled = True
    cfg.usage.off_peak_input_per_million = 1.0
    cfg.usage.off_peak_output_per_million = 4.0
    cfg.usage.peak_start = "09:00"
    cfg.usage.peak_end = "18:00"
    cfg.usage.lunch_break_enabled = True
    cfg.usage.lunch_start = "12:00"
    cfg.usage.lunch_end = "14:00"
    cfg.usage.peak_weekdays = [1, 2, 3, 4, 5]
    return True


def normalize_config(cfg: Config) -> None:
    cfg.app.continuous_interval_sec = min(
        30.0, max(0.8, cfg.app.continuous_interval_sec)
    )
    cfg.app.verify_delay_sec = min(10.0, max(0.2, cfg.app.verify_delay_sec))
    cfg.app.verify_similarity = min(1.0, max(0.5, cfg.app.verify_similarity))
    cfg.app.opacity = min(1.0, max(0.35, cfg.app.opacity))
    cfg.app.capture_delay_ms = min(1500, max(0, cfg.app.capture_delay_ms))
    cfg.app.window_width = min(1600, max(380, cfg.app.window_width))
    cfg.app.window_height = min(1600, max(260, cfg.app.window_height))
    cfg.ocr.min_confidence = min(0.99, max(0.0, cfg.ocr.min_confidence))
    cfg.ocr.max_side = min(6000, max(640, cfg.ocr.max_side))
    cfg.ocr.padding = min(80, max(0, cfg.ocr.padding))
    cfg.llm.temperature = min(2.0, max(0.0, cfg.llm.temperature))
    cfg.llm.max_tokens = min(32768, max(64, cfg.llm.max_tokens))
    cfg.llm.timeout_sec = min(300.0, max(5.0, cfg.llm.timeout_sec))
    cfg.usage.input_per_million = min(10000.0, max(0.0, cfg.usage.input_per_million))
    cfg.usage.output_per_million = min(10000.0, max(0.0, cfg.usage.output_per_million))
    cfg.usage.off_peak_input_per_million = min(
        10000.0, max(0.0, cfg.usage.off_peak_input_per_million)
    )
    cfg.usage.off_peak_output_per_million = min(
        10000.0, max(0.0, cfg.usage.off_peak_output_per_million)
    )
    cfg.usage.currency = cfg.usage.currency.strip().upper() or "CNY"
    if cfg.usage.display_mode not in {"strip", "card"}:
        cfg.usage.display_mode = "strip"
    cfg.usage.peak_weekdays = sorted(
        {day for day in cfg.usage.peak_weekdays if 1 <= day <= 7}
    )
    cfg.usage.off_peak_dates = sorted(
        {
            value
            for value in cfg.usage.off_peak_dates
            if _valid_date(value)
        }
    )


def validate_config(cfg: Config) -> list[str]:
    issues: list[str] = []
    parsed = urlparse(cfg.llm.base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        issues.append("模型 base_url 必须是有效的 http(s) 地址，例如 https://api.deepseek.com/v1")
    if not cfg.llm.model.strip():
        issues.append("模型名称不能为空")
    if not cfg.llm.system_prompt.strip():
        issues.append("系统提示词不能为空")
    for label, hotkey in (
        ("框选快捷键", cfg.app.hotkey_scan),
        ("连续扫描快捷键", cfg.app.hotkey_toggle_continuous),
        ("显示浮窗快捷键", cfg.app.hotkey_show),
    ):
        if not hotkey.strip():
            issues.append(f"{label}不能为空")
    time_fields = [
        ("高峰开始时间", cfg.usage.peak_start),
        ("高峰结束时间", cfg.usage.peak_end),
    ]
    if cfg.usage.lunch_break_enabled:
        time_fields.extend(
            [
                ("午间低谷开始时间", cfg.usage.lunch_start),
                ("午间低谷结束时间", cfg.usage.lunch_end),
            ]
        )
    for label, value in time_fields:
        try:
            datetime.strptime(value.strip(), "%H:%M")
        except ValueError:
            issues.append(f"{label}必须是 HH:MM 格式")
    if not cfg.usage.peak_weekdays:
        issues.append("高峰星期不能为空")
    for value in cfg.usage.off_peak_dates:
        if not _valid_date(value):
            issues.append(f"额外低谷日期格式错误：{value}（应为 YYYY-MM-DD）")
    return issues


def load_config(path: str | Path | None = None, create: bool = True) -> tuple[Config, Path]:
    config_path = resolve_config_path(path)
    if not config_path.exists():
        if not create:
            raise FileNotFoundError(config_path)
        cfg = Config()
        try:
            save_config(cfg, config_path)
        except OSError:
            if path is not None:
                raise
            config_path = fallback_config_path()
            if not config_path.exists():
                save_config(cfg, config_path)
    try:
        with config_path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件格式错误：{exc}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件：{exc}") from exc
    cfg = config_from_dict(data)
    apply_deepseek_defaults(cfg)
    return cfg, config_path


def save_config(cfg: Config, path: str | Path) -> Path:
    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(cfg)
    text = tomli_w.dumps(payload)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    os.replace(temporary, config_path)
    if os.name != "nt":
        with contextlib.suppress(OSError):
            config_path.chmod(0o600)
    return config_path


def resolve_api_key(cfg: Config) -> str:
    """Resolve the key from config first, then the configured environment variable."""
    if cfg.llm.api_key.strip():
        return cfg.llm.api_key.strip()
    for env_name in (cfg.llm.api_key_env.strip(), "SNAPANSWER_API_KEY"):
        if env_name and os.environ.get(env_name):
            return os.environ[env_name].strip()
    return ""


def is_local_endpoint(base_url: str) -> bool:
    """Best-effort check for local/private model servers that need no API key."""
    host = (urlparse(base_url).hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}:
        return True
    if host.endswith(".local"):
        return True
    try:
        import ipaddress

        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback
    except ValueError:
        return False


def masked_api_key(cfg: Config) -> str:
    key = resolve_api_key(cfg)
    if not key:
        return "未配置"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}…{key[-4:]}"
