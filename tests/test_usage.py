from datetime import datetime, time

from snapanswer.config import UsageSettings
from snapanswer.usage import (
    TokenUsage,
    estimate_tokens,
    estimate_usage,
    format_money,
    is_off_peak,
    parse_clock,
    snapshot_from_usage,
    usage_from_payload,
)


def test_estimate_tokens_handles_cjk_and_ascii() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("你好") == 2
    assert estimate_tokens("hello world") >= 2


def test_estimate_usage_has_positive_total() -> None:
    usage = estimate_usage("system prompt + question", "answer")
    assert usage.source == "estimated"
    assert usage.prompt_tokens > 0
    assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens


def test_usage_from_payload_supports_openai_fields() -> None:
    usage = usage_from_payload(
        {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 25,
                "total_tokens": 125,
            }
        }
    )
    assert usage is not None
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 25
    assert usage.total_tokens == 125
    assert usage.source == "api"


def test_usage_from_payload_can_be_missing() -> None:
    assert usage_from_payload({}) is None
    assert usage_from_payload({"usage": {"prompt_tokens": 0}}) is None


def test_cost_and_formatting() -> None:
    snapshot = snapshot_from_usage(
        TokenUsage(1_000_000, 500_000, 1_500_000, "api"),
        model="deepseek-chat",
        elapsed_sec=1.0,
        settings=UsageSettings(
            input_per_million=0.5,
            output_per_million=2.0,
            currency="CNY",
            off_peak_enabled=False,
        ),
    )
    assert snapshot.cost == 1.5
    assert snapshot.formatted_cost() == "¥1.5000"
    assert format_money(0) == "0"


def test_cost_unconfigured() -> None:
    snapshot = snapshot_from_usage(
        TokenUsage(10, 20, 30, "api"),
        model="local",
        elapsed_sec=0.1,
        settings=UsageSettings(
            input_per_million=0.0,
            output_per_million=0.0,
            off_peak_enabled=False,
        ),
    )
    assert snapshot.cost is None
    assert snapshot.formatted_cost() == "未配置单价"


def test_parse_clock() -> None:
    assert parse_clock("08:30") == time(8, 30)
    assert parse_clock("00:05") == time(0, 5)


def test_deepseek_peak_schedule() -> None:
    settings = UsageSettings()
    friday = datetime(2026, 10, 30)
    assert is_off_peak(friday.replace(hour=8, minute=59), settings)
    assert not is_off_peak(friday.replace(hour=9, minute=0), settings)
    assert not is_off_peak(friday.replace(hour=11, minute=59), settings)
    assert is_off_peak(friday.replace(hour=12, minute=0), settings)
    assert is_off_peak(friday.replace(hour=13, minute=59), settings)
    assert not is_off_peak(friday.replace(hour=14, minute=0), settings)
    assert not is_off_peak(friday.replace(hour=17, minute=59), settings)
    assert is_off_peak(friday.replace(hour=18, minute=0), settings)
    saturday = datetime(2026, 10, 31, 10, 0)
    assert is_off_peak(saturday, settings)


def test_custom_overnight_peak_and_holiday() -> None:
    settings = UsageSettings(
        peak_start="22:00",
        peak_end="08:00",
        lunch_break_enabled=False,
        off_peak_dates=["2026-10-01"],
    )
    assert not is_off_peak(datetime(2026, 10, 30, 23, 0), settings)
    assert not is_off_peak(datetime(2026, 10, 30, 7, 0), settings)
    assert is_off_peak(datetime(2026, 10, 30, 12, 0), settings)
    assert is_off_peak(datetime(2026, 10, 1, 12, 0), settings)


def test_snapshot_uses_peak_and_off_peak_prices() -> None:
    settings = UsageSettings(
        input_per_million=2.0,
        output_per_million=8.0,
        off_peak_enabled=True,
        off_peak_input_per_million=1.0,
        off_peak_output_per_million=4.0,
    )
    usage = TokenUsage(1_000_000, 500_000, 1_500_000, "api")
    peak = snapshot_from_usage(
        usage,
        model="m",
        elapsed_sec=1.0,
        settings=settings,
        priced_at=datetime(2026, 10, 30, 10, 0),
    )
    assert peak.period == "peak"
    assert peak.period_label == "高峰时段"
    assert peak.cost == 6.0

    off_peak = snapshot_from_usage(
        usage,
        model="m",
        elapsed_sec=1.0,
        settings=settings,
        priced_at=datetime(2026, 10, 30, 2, 0),
    )
    assert off_peak.period == "off_peak"
    assert off_peak.period_label == "低谷时段"
    assert off_peak.cost == 3.0
