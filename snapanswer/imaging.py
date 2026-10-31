"""Image conversion and preprocessing helpers."""

from __future__ import annotations

import hashlib

import numpy as np
from PIL import Image, ImageOps
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QImage, QPainter

from .config import OcrSettings


def qimage_to_pil(image: QImage) -> Image.Image:
    """Copy a QImage into an independent Pillow RGB image."""
    if image.isNull():
        raise ValueError("图像为空")
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height = converted.width(), converted.height()
    pointer = converted.bits()
    pointer.setsize(converted.sizeInBytes())
    array = np.frombuffer(pointer, dtype=np.uint8)
    array = array.reshape((height, converted.bytesPerLine()))[:, : width * 3]
    array = array.reshape((height, width, 3)).copy()
    return Image.fromarray(array, mode="RGB")


def pil_to_qimage(image: Image.Image) -> QImage:
    rgb = image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    # QImage does not own ``data``; the copy keeps it alive independently.
    return qimage.copy()


def crop_logical_region(image: QImage, screen_rect: QRect, selection: QRect) -> QImage:
    """Crop a logical (Qt) selection out of a physical-pixel screen image.

    Qt screen geometries are expressed in device-independent pixels while
    ``QScreen.grabWindow`` returns a pixmap at the monitor's native resolution.
    Mapping proportionally handles Windows display scaling and mixed-DPI setups
    without relying on global pixel coordinates.
    """
    if image.isNull() or screen_rect.isEmpty():
        return QImage()
    local = selection.translated(-screen_rect.topLeft())
    sx = image.width() / screen_rect.width()
    sy = image.height() / screen_rect.height()
    left = max(0, int(round(local.x() * sx)))
    top = max(0, int(round(local.y() * sy)))
    right = min(image.width(), int(round((local.x() + local.width()) * sx)))
    bottom = min(image.height(), int(round((local.y() + local.height()) * sy)))
    if right - left < 2 or bottom - top < 2:
        return QImage()
    return image.copy(left, top, right - left, bottom - top)


def prepare_for_ocr(image: Image.Image, settings: OcrSettings) -> Image.Image:
    """Pad and optionally upscale a screenshot crop for better OCR accuracy."""
    width, height = image.size
    if max(width, height) > settings.max_side:
        scale = settings.max_side / max(width, height)
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )

    if settings.padding > 0:
        image = ImageOps.expand(image, border=settings.padding, fill=(255, 255, 255))

    width, height = image.size
    scale = 1.0
    if settings.upscale_small:
        # Small UI text is the common failure case; 2x gives RapidOCR a much
        # better chance without making large screenshots expensive.
        if width < 1100 and height < 700:
            scale = 2.0
        elif width < 700:
            scale = 1.6
        scale = min(scale, settings.max_side / max(width, height, 1))
    if scale > 1.02:
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )
    return image


def mask_image_rect(image: QImage, rect: QRect) -> QImage:
    """Fill a rectangle with the crop's median background colour.

    Used when the floating answer window overlaps the locked OCR region.  Hiding
    the window briefly causes a visible flash, so continuous mode keeps it on
    screen and blanks only its rectangle before OCR.
    """
    if image.isNull() or rect.isEmpty():
        return image
    target = rect.intersected(image.rect())
    if target.isEmpty():
        return image

    red: list[int] = []
    green: list[int] = []
    blue: list[int] = []
    step_x = max(1, image.width() // 32)
    step_y = max(1, image.height() // 32)
    for y in range(1, image.height(), step_y):
        for x in range(1, image.width(), step_x):
            if target.adjusted(-2, -2, 2, 2).contains(x, y):
                continue
            color = image.pixelColor(x, y)
            red.append(color.red())
            green.append(color.green())
            blue.append(color.blue())
    if red:
        red.sort()
        green.sort()
        blue.sort()
        middle = len(red) // 2
        fill = QColor(red[middle], green[middle], blue[middle])
    else:
        fill = QColor("#ffffff")

    painter = QPainter(image)
    painter.fillRect(target, fill)
    painter.end()
    return image


def region_fingerprint(image: QImage) -> str:
    """Cheap fingerprint used to skip OCR while a locked region is static."""
    if image.isNull():
        return ""
    small = image.scaled(
        48,
        48,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QImage.Format.Format_Grayscale8)
    width, height = small.width(), small.height()
    pointer = small.bits()
    pointer.setsize(small.sizeInBytes())
    rows = np.frombuffer(pointer, dtype=np.uint8).reshape((height, small.bytesPerLine()))
    digest = hashlib.blake2b(rows[:, :width].tobytes(), digest_size=12).hexdigest()
    return digest
