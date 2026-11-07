from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import api.accounts as accounts_api
import services.official_image_service as official
from services.account_service import AccountService
from services.storage.json_storage import JSONStorageBackend
from services.protocol import openai_v1_image_generations as generations, openai_v1_image_edit as edits, openai_v1_models as models
from services.image_storage_service import ImageStorageService
from services.image_task_service import _request_hash

KEY = "sk-proj-fake-test-key-000000000000"
MODEL = "api-gpt-image-2.6-sunburst"


def encoded_image(animated=True):
    out = io.BytesIO()
    image = Image.new("RGB", (32, 32), "red")
    if animated:
        image.save(out, format="GIF", save_all=True, append_images=[Image.new("RGB", (32, 32), "blue")], duration=[100, 200], loop=0)
    else:
        image.save(out, format="PNG")
    return out.getvalue()


class OfficialImagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.accounts = AccountService(JSONStorageBackend(self.root / "accounts.json"))
        self.api_id = "api:test-account"
        self.accounts.add_account_items([{"access_token": self.api_id, "api_key": KEY, "type": "API", "source_type": "api", "quota": 0}])

    def test_import_requires_admin_and_never_echoes_the_secret(self):
        app = FastAPI(); app.include_router(accounts_api.create_router())
        client = TestClient(app)
        with mock.patch.object(accounts_api, "account_service", self.accounts), mock.patch.object(accounts_api, "require_admin", side_effect=HTTPException(403)):
            self.assertEqual(client.post("/api/accounts/official-api", json={"name": "Test", "api_key": KEY}).status_code, 403)
        with mock.patch.object(accounts_api, "account_service", self.accounts), mock.patch.object(accounts_api, "require_admin"):
            result = client.post("/api/accounts/official-api", json={"name": "Test", "api_key": KEY})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotIn(KEY, result.text)
        self.assertTrue(result.json()["items"][-1]["access_token"].startswith("api:"))
        restored = AccountService(JSONStorageBackend(self.root / "accounts.json"))
        self.assertNotIn(KEY, json.dumps(restored.list_accounts()))
        self.assertEqual(restored.get_account(self.api_id)["api_key"], KEY)

    def test_api_accounts_do_not_use_chatgpt_quota_or_refresh(self):
        with mock.patch("services.openai_backend_api.OpenAIBackendAPI") as backend:
            token = self.accounts.get_available_access_token(source_type="api")
        backend.assert_not_called()
        self.accounts.mark_image_result(token, True)
        account = self.accounts.get_account(token)
        self.assertEqual(account["quota"], 0)
        self.assertEqual(account["status"], "正常")
        self.assertEqual(account["image_inflight"] if "image_inflight" in account else 0, 0)
        with self.assertRaises(RuntimeError):
            self.accounts.get_available_access_token()

    def test_model_catalog_contains_explicit_api_models(self):
        with mock.patch.object(models.model_catalog_service, "list_models", return_value={"data": []}), mock.patch.object(models, "account_service", self.accounts):
            ids = {item["id"] for item in models.list_models()["data"]}
        self.assertIn(MODEL, ids)
        self.assertNotIn("codex-gpt-image-2.6", ids)

    def test_invalid_animation_options_are_rejected_before_network(self):
        invalid = [
            {"model": MODEL, "output_format": "gif", "frame_count": 1},
            {"model": MODEL, "output_format": "gif", "frame_count": 17},
            {"model": MODEL, "output_format": "gif", "frame_duration_ms": 19},
            {"model": MODEL, "output_format": "gif", "stream": True},
            {"model": MODEL, "output_format": "gif", "output_compression": 80},
            {"model": MODEL, "output_format": "png", "frame_count": 9},
        ]
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(HTTPException):official.validate_image_options(body)
        with self.assertRaises(HTTPException):official.validate_image_options({"model": MODEL, "output_format": "svg"}, editing=True)
        self.assertEqual(official.validate_image_options({"model": MODEL, "output_format": "gif"})["frame_count"], 9)

    def test_animation_is_not_silently_flattened_for_editing(self):
        with mock.patch.object(official.OfficialImagesClient, "images") as upstream:
            with self.assertRaises(HTTPException):
                edits.handle({"model": MODEL, "prompt": "edit", "images": [(encoded_image(), "test.gif", "image/gif")]})
        upstream.assert_not_called()

    def test_gif_generation_preserves_bytes_and_native_parameters(self):
        data = encoded_image(); captured = {}
        def response(client, body, images, masks):
            captured.update(body)
            return {"data": [{"b64_json": base64.b64encode(data).decode()}], "usage": {"total_tokens": 123}}
        with mock.patch("services.account_service.account_service", self.accounts), mock.patch.object(official.OfficialImagesClient, "images", response), mock.patch("services.protocol.conversation.save_image_bytes", return_value="https://test/image.gif"):
            result = generations.handle({"model": MODEL, "prompt": "bounce", "output_format": "gif", "frame_count": 8, "frame_duration_ms": 160, "size": "512x512"})
        self.assertEqual(captured["model"], "gpt-image-2.6-sunburst")
        self.assertEqual(captured["output_format"], "gif")
        self.assertEqual(captured["frame_count"], 8)
        self.assertEqual(captured["frame_duration_ms"], 160)
        self.assertEqual(base64.b64decode(result["data"][0]["b64_json"]), data)
        self.assertEqual(result["data"][0]["mime_type"], "image/gif")
        self.assertEqual(result["usage"], {"total_tokens": 123})
        self.assertEqual(self.accounts.list_accounts()[0]["success"], 1)

    def test_upstream_static_response_is_not_reported_as_a_gif_success(self):
        response = {"data": [{"b64_json": base64.b64encode(encoded_image(False)).decode()}]}
        with mock.patch("services.account_service.account_service", self.accounts), mock.patch.object(official.OfficialImagesClient, "images", return_value=response):
            from services.protocol.conversation import ImageGenerationError
            with self.assertRaises(ImageGenerationError):generations.handle({"model": MODEL, "prompt": "bounce", "output_format": "gif"})
        self.assertEqual(self.accounts.list_accounts()[0]["fail"], 1)
        self.assertEqual(self.accounts.list_accounts()[0]["image_inflight"], 0)

    def test_quota_errors_are_not_retried_and_slots_are_released(self):
        from services.protocol.conversation import ImageGenerationError
        with mock.patch("services.account_service.account_service", self.accounts), mock.patch.object(official.OfficialImagesClient, "images", side_effect=official.OfficialAPIError("Quota exceeded", 429, "insufficient_quota")) as upstream:
            with self.assertRaises(ImageGenerationError) as error:generations.handle({"model": MODEL, "prompt": "test"})
        self.assertEqual(error.exception.code, "insufficient_quota")
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(self.accounts.list_accounts()[0]["image_inflight"], 0)

    def test_animation_settings_change_task_identity(self):
        base = {"model": MODEL, "prompt": "test", "output_format": "gif", "frame_count": 9}
        self.assertNotEqual(_request_hash("generate", base), _request_hash("generate", {**base, "frame_count": 10}))

    def test_gif_storage_keeps_all_frames_and_uses_gif_suffix(self):
        data = encoded_image()
        with mock.patch("services.image_storage_service.config") as config:
            config.images_dir = self.root / "images"
            config.base_url = "https://test"
            config.get_image_storage_settings.return_value = {"mode": "local"}
            storage = ImageStorageService(self.root / "index.json")
            saved = storage.save(data)
            self.assertTrue(saved.rel.endswith(".gif"))
            self.assertEqual(storage.get_bytes(saved.rel), data)
            self.assertEqual(storage.list_items("https://test")[0]["name"], Path(saved.rel).name)
            with Image.open(io.BytesIO(storage.get_bytes(saved.rel))) as image:
                self.assertEqual(image.n_frames, 2)

    def test_chat_and_responses_do_not_silently_ignore_gif_requests(self):
        from services.protocol.openai_v1_chat_complete import chat_image_args
        from services.protocol.openai_v1_response import response_events
        with self.assertRaises(HTTPException):
            chat_image_args({"model": MODEL, "prompt": "bounce", "output_format": "gif"})
        with self.assertRaises(HTTPException):
            list(response_events({"model": MODEL, "input": "bounce", "tools": [{"type": "image_generation", "output_format": "gif"}]}))

    def test_transport_redacts_keys_in_upstream_errors(self):
        message = official._safe_error("Incorrect key: " + KEY, KEY)
        self.assertNotIn(KEY, message)
        self.assertNotIn("sk-proj", message)


if __name__ == "__main__":unittest.main()
