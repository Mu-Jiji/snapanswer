import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from snapanswer.config import OcrSettings
from snapanswer.ocr import RapidOcrEngine

pytestmark = pytest.mark.integration

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    pytest.skip("No CJK font available for OCR integration test")
    raise AssertionError("unreachable")


@pytest.mark.skipif(
    os.environ.get("SNAPANSWER_RUN_OCR_TESTS") != "1",
    reason="set SNAPANSWER_RUN_OCR_TESTS=1 to run the real OCR model",
)
def test_real_ocr_recognizes_question() -> None:
    image = Image.new("RGB", (900, 220), "white")
    draw = ImageDraw.Draw(image)
    font = _font(44)
    draw.text((30, 30), "1. 下列关于 Python 的说法", fill="black", font=font)
    draw.text((30, 100), "哪一项是正确的？", fill="black", font=font)
    result = RapidOcrEngine(OcrSettings(padding=8)).recognize(image)
    assert "Python" in result.text
    assert "正确" in result.text
    assert result.lines
