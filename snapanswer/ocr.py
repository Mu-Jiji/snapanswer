"""Local OCR engine backed by RapidOCR (ONNX Runtime)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

from .config import OcrSettings
from .imaging import prepare_for_ocr
from .ocr_text import OcrLine, lines_to_text

log = logging.getLogger(__name__)


class OcrError(RuntimeError):
    """User-facing OCR failure."""


@dataclass
class OcrResult:
    text: str
    lines: list[OcrLine] = field(default_factory=list)
    elapsed_sec: float = 0.0
    engine: str = "rapidocr"


class RapidOcrEngine:
    """Lazily initialized, reusable RapidOCR wrapper.

    The first call loads ONNX models and may take a few seconds.  Reusing the
    instance keeps subsequent scans fast; the GUI runs it on a worker thread.
    """

    def __init__(self, settings: OcrSettings) -> None:
        self.settings = settings
        self._engine: Any = None

    def _load(self) -> Any:
        if self._engine is not None:
            return self._engine
        if self.settings.engine.lower() not in {"rapidocr", "rapid", "rapidocr_onnxruntime"}:
            raise OcrError(f"不支持的 OCR 引擎：{self.settings.engine}（当前仅支持 rapidocr）")
        try:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError:  # newer package layout
                from rapidocr import RapidOCR
        except ImportError as exc:
            raise OcrError(
                "未安装 RapidOCR。请运行：pip install -r requirements.txt"
            ) from exc
        try:
            self._engine = RapidOCR()
        except Exception as exc:  # pragma: no cover - model/runtime specific
            raise OcrError(f"OCR 引擎初始化失败：{exc}") from exc
        return self._engine

    def warmup(self) -> None:
        self._load()

    def recognize(self, image: Image.Image) -> OcrResult:
        if image.width < 3 or image.height < 3:
            raise OcrError("框选区域太小，请重新框选")
        engine = self._load()
        prepared = prepare_for_ocr(image, self.settings)
        # RapidOCR's documented ndarray input follows OpenCV's BGR convention.
        array = np.asarray(prepared.convert("RGB"))[:, :, ::-1].copy()
        started = time.perf_counter()
        try:
            raw = engine(array)
        except Exception as exc:  # pragma: no cover - runtime/ONNX specific
            log.exception("RapidOCR failed")
            raise OcrError(f"OCR 识别失败：{exc}") from exc
        lines = _parse_output(raw)
        elapsed = time.perf_counter() - started
        text = lines_to_text(lines, self.settings.min_confidence)
        if not text:
            raise OcrError("没有识别到文字，请框选得更精确，或放大题目后再试")
        return OcrResult(
            text=text,
            lines=lines,
            elapsed_sec=elapsed,
            engine="rapidocr",
        )


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _box_bounds(box: Any) -> tuple[float, float, float, float]:
    try:
        points = np.asarray(box, dtype=float).reshape(-1, 2)
        return (
            float(points[:, 0].min()),
            float(points[:, 1].min()),
            float(points[:, 0].max()),
            float(points[:, 1].max()),
        )
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0, 0.0)


def _parse_output(output: Any) -> list[OcrLine]:
    """Handle both RapidOCR 1.x tuple output and 2.x result objects."""
    if output is None:
        return []

    # rapidocr >= 1.4 style object with parallel arrays
    txts = getattr(output, "txts", None)
    if txts is not None:
        scores = getattr(output, "scores", None)
        if scores is None:
            scores = []
        boxes = getattr(output, "boxes", None)
        if boxes is None:
            boxes = []
        parsed: list[OcrLine] = []
        for index, text in enumerate(txts):
            score = _as_float(scores[index]) if index < len(scores) else 1.0
            box = boxes[index] if index < len(boxes) else (0, 0, 0, 0)
            parsed.append(
                OcrLine(
                    text=str(text),
                    confidence=score,
                    box=_box_bounds(box),
                )
            )
        return parsed

    result = output
    if isinstance(output, tuple) and len(output) >= 1:
        result = output[0]
    if result is None:
        return []
    parsed = []
    for item in result:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        box, text = item[0], item[1]
        score = _as_float(item[2]) if len(item) > 2 else 1.0
        parsed.append(
            OcrLine(text=str(text), confidence=score, box=_box_bounds(box))
        )
    return parsed
