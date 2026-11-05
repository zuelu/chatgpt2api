"""Detect raster formats without changing encoded image or animation bytes."""
from pathlib import Path


def image_media_type(data: bytes) -> str:
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def image_extension(data: bytes) -> str:
    return {"image/gif": ".gif", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(image_media_type(data), ".png")


def image_path_media_type(path: str) -> str:
    return {".gif": "image/gif", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(Path(path).suffix.lower(), "image/png")
