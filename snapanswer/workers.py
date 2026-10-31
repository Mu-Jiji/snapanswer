"""Background workers for OCR and model requests."""

from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from .config import LlmSettings
from .imaging import qimage_to_pil
from .llm import LlmClient, LlmError
from .ocr import OcrError, RapidOcrEngine

log = logging.getLogger(__name__)


class OcrWorker(QThread):
    completed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, image: QImage, engine: RapidOcrEngine, parent=None) -> None:
        super().__init__(parent)
        self._image = image
        self._engine = engine
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:  # noqa: D401
        try:
            if self._cancelled.is_set():
                return
            result = self._engine.recognize(qimage_to_pil(self._image))
        except OcrError as exc:
            if not self._cancelled.is_set():
                self.failed.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover
            log.exception("Unexpected OCR worker failure")
            if not self._cancelled.is_set():
                self.failed.emit(f"OCR 出现异常：{exc}")
            return
        if not self._cancelled.is_set():
            self.completed.emit(result.text)


class SolveWorker(QThread):
    ocr_done = pyqtSignal(str)
    ocr_failed = pyqtSignal(str)
    delta = pyqtSignal(str)
    answer_ready = pyqtSignal(str, float, str, object)
    failed = pyqtSignal(str, str)
    cancelled = pyqtSignal(str)

    def __init__(
        self,
        *,
        llm_settings: LlmSettings,
        api_key: str,
        question: str = "",
        image: QImage | None = None,
        ocr_engine: RapidOcrEngine | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._llm_settings = llm_settings
        self._api_key = api_key
        self.question = question
        self._image = image
        self._ocr_engine = ocr_engine
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:  # noqa: D401
        if self._image is not None:
            if self._ocr_engine is None:
                self.ocr_failed.emit("OCR 引擎未初始化")
                return
            try:
                result = self._ocr_engine.recognize(qimage_to_pil(self._image))
            except OcrError as exc:
                self.ocr_failed.emit(str(exc))
                return
            except Exception as exc:  # pragma: no cover
                log.exception("Unexpected OCR failure")
                self.ocr_failed.emit(f"OCR 出现异常：{exc}")
                return
            self.question = result.text
            self.ocr_done.emit(result.text)

        if self._cancel_event.is_set():
            self.cancelled.emit("")
            return
        if not self.question.strip():
            self.failed.emit("没有可发送给模型的题目文本", "")
            return

        client = LlmClient(self._llm_settings, self._api_key)
        try:
            result = client.complete(
                self.question,
                on_delta=self.delta.emit,
                cancel_event=self._cancel_event,
            )
        except LlmError as exc:
            if self._cancel_event.is_set() and not exc.partial:
                self.cancelled.emit("")
            elif self._cancel_event.is_set():
                self.cancelled.emit(exc.partial)
            else:
                self.failed.emit(str(exc), exc.partial)
            return
        except Exception as exc:  # pragma: no cover
            log.exception("Unexpected model failure")
            self.failed.emit(f"模型请求出现异常：{exc}", "")
            return
        if self._cancel_event.is_set():
            self.cancelled.emit(result.text)
            return
        self.answer_ready.emit(
            result.text,
            result.elapsed_sec,
            result.model,
            result.usage,
        )
