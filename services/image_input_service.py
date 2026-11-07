"""Prepare raster reference images for still-image generation and editing."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from utils.log import logger

ImageInput = tuple[bytes, str, str]


def prepare_image_references(images: Iterable[ImageInput]) -> tuple[list[ImageInput], list[dict]]:
    """Use a multi-frame reference's first frame without changing output format.

    The caller keeps the original upload. GIF, animated WebP/APNG and other
    Pillow-readable formats are converted into an upstream-compatible PNG.
    Conversion details are returned for responses, logs and user notices.
    """
    prepared: list[ImageInput] = []
    adjustments: list[dict] = []
    for index, (data, filename, mime) in enumerate(images):
        if data.lstrip().startswith((b"<", b"\xef\xbb\xbf")):
            raise HTTPException(400, detail={"error": {"message": "SVG is not supported as a raster edit input. Export it as PNG first.", "code": "svg_edit_input_unsupported"}})
        try:
            with Image.open(io.BytesIO(data)) as image:
                source_format = str(image.format or "").upper()
                frames = int(getattr(image, "n_frames", 1))
                if frames == 1 and source_format in {"PNG", "JPEG", "WEBP"}:
                    prepared.append((data, filename, Image.MIME.get(source_format, mime)))
                    continue
                image.seek(0)
                frame = ImageOps.exif_transpose(image).convert("RGBA")
                buffer = io.BytesIO()
                frame.save(buffer, format="PNG")
                prepared.append((buffer.getvalue(), Path(filename or "reference").stem + ".png", "image/png"))
                adjustments.append({
                    "index": index,
                    "code": "reference_first_frame" if frames > 1 else "reference_png",
                    "source_format": source_format.lower(),
                    "source_frames": frames,
                    "selected_frame": 0,
                    "output_format": "png",
                })
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(400, detail={"error": {
                "message": "Could not read the reference image. Please upload a valid image again.",
                "code": "invalid_reference_image", "param": f"images[{index}]",
            }}) from None
    if adjustments:
        logger.info({"event": "image_reference_prepared", "input_adjustments": adjustments})
    return prepared, adjustments
