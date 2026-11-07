"""Official OpenAI Images API transport, separate from ChatGPT OAuth accounts."""
from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from typing import Any

from fastapi import HTTPException
from PIL import Image

from utils.helper import DEFAULT_IMAGE_MODEL
from utils.image_formats import svg_root
from utils.image_retry import can_retry_with_another_account

OFFICIAL_API_URL = "https://api.openai.com/v1"
OFFICIAL_IMAGE_MODELS = {
    "api-gpt-image-2.6-sunburst": "gpt-image-2.6-sunburst",
    "api-gpt-image-2.6-flare": "gpt-image-2.6-flare",
}


class OfficialAPIError(RuntimeError):
    def __init__(self, message: str, status: int = 502, code: str = "official_api_error", request_id: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code
        self.request_id = request_id


def _safe_error(text: str, key: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_*.-]+", "[redacted]", text.replace(key, "[redacted]"))[:1500]


class OfficialImagesClient:
    def __init__(self, key: str):
        self.key = key

    def request(self, path: str, payload: bytes | None = None, content_type: str = "application/json") -> dict:
        request = urllib.request.Request(OFFICIAL_API_URL + path, data=payload, headers={
            "Authorization": "Bearer " + self.key, "Content-Type": content_type,
        })
        try:
            # Do not forward credentials to redirects, even from a trusted host.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None
            with urllib.request.build_opener(NoRedirect).open(request, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            try:
                detail = json.loads(raw).get("error", {})
            except (ValueError, AttributeError):
                detail = {}
            message = _safe_error(str(detail.get("message") or "Official OpenAI API request failed."), self.key)
            raise OfficialAPIError(message, error.code, str(detail.get("code") or "official_api_error"), error.headers.get("x-request-id", "")) from None
        except (OSError, ValueError):
            raise OfficialAPIError("Could not reach the official OpenAI API.") from None

    def check(self) -> list[str]:
        data = self.request("/models")
        return [str(item.get("id") or "") for item in data.get("data", []) if isinstance(item, dict)]

    def images(self, body: dict, images: list | None = None, masks: list | None = None) -> dict:
        if not images:
            return self.request("/images/generations", json.dumps(body).encode())
        boundary = "aimg-" + uuid.uuid4().hex
        parts = []
        for name, value in body.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        for name, files in (("image[]", images), ("mask", (masks or [])[:1])):
            for index, (data, _, mime) in enumerate(files):
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="image-{index}.png"\r\nContent-Type: {mime}\r\n\r\n'.encode() + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self.request("/images/edits", b"".join(parts), "multipart/form-data; boundary=" + boundary)


def resolve_image_model(model: str | None, output_format: str | None) -> str:
    """Native GIF/SVG always use the official API pool, including omitted models."""
    model = model or DEFAULT_IMAGE_MODEL
    if str(output_format or "png").strip().lower() in {"gif", "svg"} and model not in OFFICIAL_IMAGE_MODELS:
        return "api-gpt-image-2.6-flare" if model.endswith("-flare") else "api-gpt-image-2.6-sunburst"
    return model


def validate_image_options(body: dict, *, editing: bool = False) -> dict[str, Any]:
    """Reject unsupported combinations before acquiring an account or submitting a job."""
    output = str(body.get("output_format") or "png").strip().lower()
    model = resolve_image_model(body.get("model"), output)
    def invalid(message: str, param: str = "output_format"):
        raise HTTPException(400, detail={"error": {"message": message, "type": "invalid_request_error", "code": "unsupported_image_options", "param": param}})
    if output not in {"png", "jpeg", "webp", "gif", "svg"}:
        invalid("Supported output formats are png, jpeg, webp, gif and svg.")
    if output != "png" and model not in OFFICIAL_IMAGE_MODELS:
        invalid("This output format requires an official API model (api-gpt-image-2.6-sunburst or api-gpt-image-2.6-flare). The ChatGPT/Codex channel does not support native GIF output.")
    if editing and output == "svg":
        invalid("The official Images edit endpoint does not support SVG output. Generate SVG from a text prompt.")
    if output == "svg" and int(body.get("n") or 1) != 1:
        invalid("SVG generation requires n=1.", "n")
    if output == "gif" and body.get("mask"):
        invalid("GIF output does not support masks.", "mask")
    options: dict[str, Any] = {"output_format": output}
    if body.get("svg") is not None:
        svg = body["svg"]
        if output != "svg" or not isinstance(svg, dict) or not isinstance(svg.get("model"), str) or not svg["model"].strip():
            invalid("svg requires SVG output and a nonempty svg.model.", "svg")
        options["svg"] = svg
    for name, default, minimum, maximum in (("frame_count", 9, 2, 16), ("frame_duration_ms", 200, 20, 2000)):
        value = body.get(name)
        if output != "gif":
            if value is not None:
                invalid("Animation settings are only valid with GIF output.", name)
            continue
        if value is None:
            value = default
        if isinstance(value, bool) or not str(value).isdigit() or not minimum <= int(value) <= maximum:
            invalid(f"{name} must be an integer between {minimum} and {maximum}.", name)
        options[name] = int(value)
    if model in OFFICIAL_IMAGE_MODELS and body.get("stream") and output != "gif":
        invalid("Streaming is not exposed for official API models by this service.", "stream")
    if output in {"gif", "svg"} and (body.get("stream") or body.get("partial_images") or body.get("output_compression") is not None or body.get("prompt_rewriter") is not None):
        invalid("GIF/SVG output does not support streaming, partial_images, output_compression or prompt_rewriter.")
    return options


def reject_animated_inputs(images: list) -> None:
    for data, _, _ in images:
        if data.lstrip().startswith((b"<", b"\xef\xbb\xbf")):
            raise HTTPException(400, detail={"error": {"message": "SVG is not supported as a raster edit input. Export it as PNG first.", "code": "svg_edit_input_unsupported"}})
        try:
            with Image.open(io.BytesIO(data)) as image:
                if getattr(image, "is_animated", False):
                    raise HTTPException(400, detail={"error": {"message": "Animated image editing is not supported; select a still frame explicitly before editing.", "code": "animated_image_edit_unsupported"}})
        except (OSError, ValueError):
            pass


def official_image_request(body: dict) -> dict:
    from services.account_service import account_service
    from services.protocol.conversation import ImageGenerationError, format_image_result
    body = {**body, "model": resolve_image_model(body.get("model"), body.get("output_format"))}
    options = validate_image_options(body, editing=bool(body.get("images")))
    if body.get("retain_conversation") or body.get("provider_binding_id"):
        raise HTTPException(400, detail={"error": "Official Images API does not support retained ChatGPT conversation bindings."})
    images = body.get("images") or []
    reject_animated_inputs(images)
    payload = {"model": OFFICIAL_IMAGE_MODELS[body["model"]], "prompt": str(body.get("prompt") or ""),
               "n": int(body.get("n") or 1), "quality": str(body.get("quality") or "auto"), **options}
    if body.get("size"):
        payload["size"] = body["size"]
    if options["output_format"] == "gif" and payload.get("size") not in {None, "auto"}:
        match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", str(payload["size"]))
        if not match or any(int(v) % 16 for v in match.groups()):
            raise HTTPException(400, detail={"error": "GIF frame dimensions must be positive multiples of 16."})
    attempted: set[str] = set()
    last_error: OfficialAPIError | None = None
    while True:
        try:
            if callable(body.get("progress_callback")):
                body["progress_callback"]("getting_account")
            account_id = account_service.get_available_access_token(source_type="api", excluded_tokens=attempted)
        except RuntimeError:
            if last_error is not None:
                raise ImageGenerationError(str(last_error), status_code=last_error.status, code=last_error.code) from None
            raise ImageGenerationError("No available official API account. Add an API key in Import accounts.", status_code=400, code="official_api_account_required") from None
        attempted.add(account_id)
        success = False
        try:
            account = account_service.get_account(account_id) or {}
            client = OfficialImagesClient(str(account.get("api_key") or ""))
            try:
                result = client.images(payload, images, body.get("mask"))
            except OfficialAPIError as error:
                # Some projects require author selection; others prohibit it.
                # Retry only this explicit pre-generation parameter rejection.
                if options["output_format"] != "svg" or payload.get("svg") or error.status != 400 or error.code != "missing_required_parameter" or "svg.model" not in str(error):
                    raise
                result = client.images({**payload, "svg": {"model": os.getenv("OPENAI_SVG_AUTHOR_MODEL", "gpt-6.1-sol")}}, images, body.get("mask"))
            items = result.get("data") or []
            if not items or any(not isinstance(item, dict) or not isinstance(item.get("b64_json"), str) for item in items):
                raise OfficialAPIError("The official API returned no image data.")
            # Verify the returned media rather than trusting the requested suffix.
            try:
                for item in items:
                    data = base64.b64decode(item["b64_json"], validate=True)
                    if options["output_format"] == "gif":
                        with Image.open(io.BytesIO(data)) as image:
                            if image.format != "GIF" or getattr(image, "n_frames", 1) < 2:
                                raise OfficialAPIError("The upstream response did not contain an animated GIF.")
                    elif options["output_format"] == "svg":
                        svg_root(data)
            except (ValueError, OSError) as error:
                raise OfficialAPIError("The upstream response contained invalid image data.", code="invalid_upstream_image") from error
            formatted = format_image_result(items, payload["prompt"], str(body.get("response_format") or "b64_json"), body.get("base_url"))
            for field in ("usage", "svg_usage"):
                if isinstance(result.get(field), dict):
                    formatted[field] = result[field]
            success = True
            return formatted
        except OfficialAPIError as error:
            from utils.log import logger
            logger.warning({"event": "official_images_api_error", "status": error.status, "code": error.code, "request_id": error.request_id, "attempt": len(attempted)})
            last_error = error
            if not can_retry_with_another_account(error):
                raise ImageGenerationError(str(error), status_code=error.status, code=error.code) from None
            # Each eligible account is attempted at most once. Never fall back to
            # OAuth accounts for native GIF/SVG, or repeat a depleted API key.
            continue
        finally:
            account_service.mark_image_result(account_id, success)
