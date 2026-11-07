"""Detect image formats and validate static SVG documents without rewriting bytes."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def svg_root(data: bytes) -> ET.Element:
    text = data.decode("utf-8-sig")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I):
        raise ValueError("SVG document declarations are not supported.")
    if re.search(r"<\?(?!xml(?:\s|\?>))", text, re.I):
        raise ValueError("SVG processing instructions are not supported.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError("Invalid SVG XML.") from error
    if root.tag != "{http://www.w3.org/2000/svg}svg" and root.tag != "svg":
        raise ValueError("Expected an SVG document.")
    # Serve only static vector content. No scripts, embedded raster images,
    # animation, HTML, or references outside this document.
    allowed = set("svg g defs title desc metadata path rect circle ellipse line polyline polygon text tspan textPath use symbol view switch a clipPath mask pattern marker linearGradient radialGradient stop filter feBlend feColorMatrix feComponentTransfer feComposite feConvolveMatrix feDiffuseLighting feDisplacementMap feDistantLight feDropShadow feFlood feFuncA feFuncB feFuncG feFuncR feGaussianBlur feMerge feMergeNode feMorphology feOffset fePointLight feSpecularLighting feSpotLight feTile feTurbulence style".split())
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in allowed or (element.tag.startswith("{") and not element.tag.startswith("{http://www.w3.org/2000/svg}")):
            raise ValueError("SVG must contain static vector content only.")
        values = list(element.attrib.values())
        if tag == "style":
            values.append(element.text or "")
        for name, value in element.attrib.items():
            local_name = name.rsplit("}", 1)[-1].lower()
            if local_name.startswith("on") or local_name == "base":
                raise ValueError("SVG event handlers and base URLs are not supported.")
            if local_name in {"href", "src"} and not value.strip().startswith("#"):
                raise ValueError("SVG external resources are not supported.")
        for value in values:
            # CSS escapes/comments could conceal resource URLs. Generated SVG
            # needs neither; reject them as well as external CSS and fonts.
            if "\\" in value or "/*" in value or "@" in value or re.search(r"(?:https?:|data:|javascript:|expression\s*\()", value, re.I):
                raise ValueError("SVG external or active content is not supported.")
            for url in re.findall(r"url\s*\((.*?)\)", value, re.I | re.S):
                if not url.strip().strip("\"'").startswith("#"):
                    raise ValueError("SVG external resources are not supported.")
    return root


def svg_dimensions(data: bytes) -> tuple[int, int] | None:
    root = svg_root(data)
    try:
        width = float(root.get("width", "").removesuffix("px"))
        height = float(root.get("height", "").removesuffix("px"))
    except ValueError:
        box = root.get("viewBox", "").replace(",", " ").split()
        if len(box) != 4:
            return None
        width, height = map(float, box[2:])
    return (round(width), round(height)) if width > 0 and height > 0 else None


def image_media_type(data: bytes) -> str:
    if re.match(br"(?:\xef\xbb\xbf)?\s*(?:<\?xml[^>]*>\s*)?(?:<!--.*?-->\s*)*<svg(?:\s|>)", data, re.S):
        svg_root(data)
        return "image/svg+xml"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def image_extension(data: bytes) -> str:
    return {"image/svg+xml": ".svg", "image/gif": ".gif", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(image_media_type(data), ".png")


def image_path_media_type(path: str) -> str:
    return {".svg": "image/svg+xml", ".gif": "image/gif", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(Path(path).suffix.lower(), "image/png")
