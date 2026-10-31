"""Token accounting, estimated usage, and cost formatting."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time

from .config import UsageSettings

CURRENCY_SYMBOLS = {"CNY": "¥", "USD": "$", "EUR": "€"}


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    source: str = "unknown"  # "api" | "estimated"

    def normalized(self) -> TokenUsage:
        prompt = max(0, int(self.prompt_tokens))
        completion = max(0, int(self.completion_tokens))
        total = max(int(self.total_tokens), prompt + completion)
        return TokenUsage(prompt, completion, total, self.source)


@dataclass
class UsageSnapshot:
    model: str
    elapsed_sec: float
    usage: TokenUsage
    input_per_million: float = 0.0
    output_per_million: float = 0.0
    currency: str = "CNY"
    priced_at: datetime = field(default_factory=datetime.now)
    period: str = "flat"  # "flat" | "peak" | "off_peak"

    @property
    def period_label(self) -> str:
        return {"peak": "高峰时段", "off_peak": "低谷时段"}.get(self.period, "")

    @property
    def cost(self) -> float | None:
        if self.input_per_million <= 0 and self.output_per_million <= 0:
            return None
        usage = self.usage.normalized()
        return (
            usage.prompt_tokens / 1_000_000 * self.input_per_million
            + usage.completion_tokens / 1_000_000 * self.output_per_million
        )

    @property
    def cost_configured(self) -> bool:
        return self.input_per_million > 0 or self.output_per_million > 0

    def formatted_cost(self) -> str:
        cost = self.cost
        if cost is None:
            return "未配置单价"
        symbol = CURRENCY_SYMBOLS.get(self.currency.upper())
        if symbol:
            return f"{symbol}{format_money(cost)}"
        return f"{format_money(cost)} {self.currency}"


def parse_clock(value: str) -> time:
    parsed = datetime.strptime(value.strip(), "%H:%M")
    return parsed.time()


def is_off_peak(moment: datetime, settings: UsageSettings) -> bool:
    """Whether *moment* falls outside the configured peak schedule.

    Weekends, optional holiday dates and the configured lunch break are always
    off-peak. A peak start later than end (for example 22:00–08:00) wraps over
    midnight; equal start/end means the whole day is peak.
    """
    if moment.date().isoformat() in settings.off_peak_dates:
        return True
    if moment.isoweekday() not in settings.peak_weekdays:
        return True
    current = moment.time()
    if settings.lunch_break_enabled:
        lunch_start = parse_clock(settings.lunch_start)
        lunch_end = parse_clock(settings.lunch_end)
        if lunch_start < lunch_end and lunch_start <= current < lunch_end:
            return True
    start = parse_clock(settings.peak_start)
    end = parse_clock(settings.peak_end)
    if start == end:
        return False
    peak = (
        start <= current < end
        if start < end
        else current >= start or current < end
    )
    return not peak


def estimate_tokens(text: str) -> int:
    """Cheap model-agnostic estimate, used only when the API omits usage."""
    if not text:
        return 0
    cjk = 0
    for char in text:
        code = ord(char)
        if (
            0x3400 <= code <= 0x4DBF
            or 0x4E00 <= code <= 0x9FFF
            or 0xF900 <= code <= 0xFAFF
            or 0x3040 <= code <= 0x30FF
            or 0xAC00 <= code <= 0xD7AF
        ):
            cjk += 1
    other = max(0, len(text) - cjk)
    other_tokens = math.ceil(other / 4) if other else 0
    return cjk + other_tokens


def estimate_usage(prompt: str, completion: str) -> TokenUsage:
    prompt_tokens = estimate_tokens(prompt) + 8
    completion_tokens = estimate_tokens(completion)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        source="estimated",
    )


def usage_from_payload(payload: object) -> TokenUsage | None:
    """Read OpenAI-style ``usage`` from a response or SSE event."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("usage")
    if not isinstance(data, dict):
        return None
    prompt = data.get("prompt_tokens", data.get("input_tokens", 0))
    completion = data.get("completion_tokens", data.get("output_tokens", 0))
    total = data.get("total_tokens", 0)
    try:
        prompt_tokens = max(0, int(prompt or 0))
        completion_tokens = max(0, int(completion or 0))
        total_tokens = max(0, int(total or 0))
    except (TypeError, ValueError):
        return None
    if prompt_tokens == 0 and completion_tokens == 0 and total_tokens == 0:
        return None
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=max(total_tokens, prompt_tokens + completion_tokens),
        source="api",
    )


def snapshot_from_usage(
    usage: TokenUsage,
    *,
    model: str,
    elapsed_sec: float,
    settings: UsageSettings,
    priced_at: datetime | None = None,
) -> UsageSnapshot:
    priced_at = priced_at or datetime.now()
    if settings.off_peak_enabled:
        off_peak = is_off_peak(priced_at, settings)
        input_price = (
            settings.off_peak_input_per_million
            if off_peak
            else settings.input_per_million
        )
        output_price = (
            settings.off_peak_output_per_million
            if off_peak
            else settings.output_per_million
        )
        period = "off_peak" if off_peak else "peak"
    else:
        input_price = settings.input_per_million
        output_price = settings.output_per_million
        period = "flat"
    return UsageSnapshot(
        model=model,
        elapsed_sec=elapsed_sec,
        usage=usage.normalized(),
        input_per_million=input_price,
        output_per_million=output_price,
        currency=settings.currency,
        priced_at=priced_at,
        period=period,
    )


def format_money(value: float) -> str:
    if value <= 0:
        return "0"
    if value >= 1:
        return f"{value:,.4f}"
    if value >= 0.01:
        return f"{value:.5f}"
    return f"{value:.6f}"
