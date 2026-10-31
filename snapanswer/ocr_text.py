"""OCR text cleanup and ordering utilities (kept UI-independent for tests)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

_WHITESPACE = re.compile(r"[ \t\u00a0\u3000]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float = 1.0
    #: Box as (left, top, right, bottom) in image pixels.
    box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    @property
    def center_y(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def center_x(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def height(self) -> float:
        return max(1.0, self.box[3] - self.box[1])


def normalize_text(text: str) -> str:
    """Normalize OCR whitespace while preserving line structure."""
    text = unicodedata.normalize("NFC", text)
    text = _ZERO_WIDTH.sub("", text)
    text = _CONTROL.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = _WHITESPACE.sub(" ", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def compact_text(text: str) -> str:
    """Return a whitespace-free comparison form."""
    return re.sub(r"\s+", "", normalize_text(text))


def lines_to_text(lines: list[OcrLine], min_confidence: float = 0.0) -> str:
    """Filter, de-duplicate and read OCR fragments in natural reading order."""
    accepted = [
        line
        for line in lines
        if line.text.strip() and line.confidence >= min_confidence
    ]
    if not accepted:
        return ""

    accepted.sort(key=lambda line: (line.center_y, line.center_x))
    rows: list[list[OcrLine]] = []
    row_centers: list[float] = []
    for line in accepted:
        tolerance = max(8.0, line.height * 0.55)
        if rows and abs(line.center_y - row_centers[-1]) <= tolerance:
            rows[-1].append(line)
            row_centers[-1] = sum(item.center_y for item in rows[-1]) / len(rows[-1])
        else:
            rows.append([line])
            row_centers.append(line.center_y)

    output: list[str] = []
    seen: set[str] = set()
    for row in rows:
        row.sort(key=lambda line: line.box[0])
        pieces: list[str] = []
        for line in row:
            piece = line.text.strip()
            key = compact_text(piece)
            if not key or key in seen:
                continue
            seen.add(key)
            pieces.append(piece)
        if pieces:
            output.append(" ".join(pieces))
    return normalize_text("\n".join(output))


def similarity(left: str, right: str) -> float:
    """Similarity ratio in [0, 1], ignoring whitespace and letter case."""
    a = compact_text(left).lower()
    b = compact_text(right).lower()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Bound the work for very long OCR results.
    if len(a) * len(b) > 4_000_000:
        a, b = a[:2000], b[:2000]
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def is_new_question(
    candidate: str,
    previous: str,
    *,
    threshold: float = 0.86,
) -> bool:
    """Whether OCR text looks like a different question than the last solved one."""
    normalized = normalize_text(candidate)
    if len(compact_text(normalized)) < 4:
        return False
    if not previous:
        return True
    return similarity(normalized, previous) < threshold


def should_reanswer(
    previous: str,
    current: str,
    *,
    threshold: float = 0.95,
) -> bool:
    """Whether a fresh OCR pass differs enough from the answered question.

    ``threshold=1.0`` requests a new answer on any normalized difference;
    lower values tolerate minor OCR noise.
    """
    normalized = normalize_text(current)
    if len(compact_text(normalized)) < 4:
        return False
    if not normalize_text(previous):
        return True
    return similarity(normalized, previous) < threshold
