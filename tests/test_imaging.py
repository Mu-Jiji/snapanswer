from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QImage

from snapanswer.config import OcrSettings
from snapanswer.imaging import (
    crop_logical_region,
    mask_image_rect,
    prepare_for_ocr,
    qimage_to_pil,
    region_fingerprint,
)


def make_image(width: int = 400, height: int = 200) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    return image


def test_crop_maps_logical_selection_to_physical_pixels() -> None:
    image = make_image(1920, 1080)
    screen = QRect(0, 0, 1280, 720)
    selection = QRect(320, 180, 640, 360)
    crop = crop_logical_region(image, screen, selection)
    assert (crop.width(), crop.height()) == (960, 540)


def test_crop_with_negative_screen_origin() -> None:
    image = make_image(800, 600)
    screen = QRect(-800, 0, 800, 600)
    selection = QRect(-400, 100, 200, 100)
    crop = crop_logical_region(image, screen, selection)
    assert (crop.width(), crop.height()) == (200, 100)


def test_crop_rejects_degenerate_selection() -> None:
    image = make_image()
    assert crop_logical_region(image, QRect(0, 0, 400, 200), QRect(10, 10, 1, 1)).isNull()


def test_qimage_to_pil_is_independent() -> None:
    image = make_image(10, 10)
    pil = qimage_to_pil(image)
    assert pil.size == (10, 10)
    image.fill(QColor("#000000"))
    assert pil.getpixel((0, 0)) == (255, 255, 255)


def test_prepare_upscales_small_and_caps_large() -> None:
    settings = OcrSettings(padding=0, upscale_small=True, max_side=1000)
    small = prepare_for_ocr(qimage_to_pil(make_image(200, 100)), settings)
    assert small.size == (400, 200)

    large = prepare_for_ocr(qimage_to_pil(make_image(2000, 1200)), settings)
    assert max(large.size) == 1000


def test_fingerprint_changes_with_content() -> None:
    first = make_image(400, 200)
    second = make_image(400, 200)
    second.fill(QColor("#000000"))
    assert region_fingerprint(first) != region_fingerprint(second)
    assert region_fingerprint(first) == region_fingerprint(first)


def test_mask_image_rect_uses_surrounding_colour() -> None:
    image = make_image(100, 100)
    for y in range(40, 60):
        for x in range(40, 60):
            image.setPixelColor(x, y, QColor("#000000"))
    mask_image_rect(image, QRect(40, 40, 20, 20))
    assert image.pixelColor(50, 50) == QColor("#ffffff")
    assert image.pixelColor(10, 10) == QColor("#ffffff")


def test_mask_image_rect_ignores_outside_rect() -> None:
    image = make_image(30, 30)
    mask_image_rect(image, QRect(-20, -20, 10, 10))
    assert image.pixelColor(0, 0) == QColor("#ffffff")
