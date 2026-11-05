from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.openai_backend_api as backend_module
import services.protocol.conversation as conversation
from api.ai import ImageGenerationRequest
from api.image_inputs import _payload_from_fields
from api.image_tasks import ImageGenerationTaskRequest
from services.account_service import AccountService
from services.config import ConfigStore
from services.openai_backend_api import OpenAIBackendAPI, normalize_codex_image_quality
from services.protocol import openai_v1_image_generations, openai_v1_models
from services.protocol.openai_v1_chat_complete import chat_image_args
from utils.helper import (
    CODEX_IMAGE_26_MODELS,
    DEFAULT_IMAGE_MODEL,
    is_codex_image_model,
    is_supported_image_model,
    split_image_model,
)


class ImageModel26Tests(unittest.TestCase):
    def test_all_aliases_route_to_codex_with_plan_filtering(self):
        for model in CODEX_IMAGE_26_MODELS:
            for plan in (None, "plus", "team", "pro"):
                alias = f"{plan}-{model}" if plan else model
                with self.subTest(alias=alias):
                    self.assertTrue(is_supported_image_model(alias))
                    self.assertTrue(is_codex_image_model(alias))
                    self.assertEqual(split_image_model(alias), (plan, model))
                    self.assertEqual(AccountService._image_route(alias),
                                     (plan, "codex", ("plus", "team", "pro") if not plan else None))

    def test_config_defaults_and_invalid_values_never_reuse_25_model(self):
        config = ConfigStore.__new__(ConfigStore)
        for value, expected in ((None, "gpt-image-2.6-sunburst"),
                                ("gpt-image-2.6-flare", "gpt-image-2.6-flare"),
                                ("gpt-image-2.5-sunburst", "gpt-image-2.6-sunburst")):
            with self.subTest(value=value):
                config.data = {"codex_image_model_26_name": value,
                               "codex_image_model_25_name": "gpt-image-2.5-flare"}
                self.assertEqual(config.codex_image_model_26_name, expected)
                self.assertEqual(config.codex_image_model_25_name, "gpt-image-2.5-flare")

    def test_tool_routing_respects_exact_variants_and_legacy_selection(self):
        config = SimpleNamespace(codex_image_model_26_name="gpt-image-2.6-flare",
                                 codex_image_model_25_name="gpt-image-2.5-sunburst")
        with mock.patch.object(conversation, "config", config):
            for alias in ("codex-gpt-image-2.6", "gpt-image-2.6", "pro-codex-gpt-image-2.6"):
                self.assertEqual(conversation.codex_image_tool_model(alias), "gpt-image-2.6-flare")
            self.assertEqual(conversation.codex_image_tool_model("gpt-image-2.6-sunburst"), "gpt-image-2.6-sunburst")
            self.assertEqual(conversation.codex_image_tool_model("gpt-image-2.6-flare"), "gpt-image-2.6-flare")
            self.assertEqual(conversation.codex_image_tool_model("codex-gpt-image-2.5"), "gpt-image-2.5-sunburst")
            self.assertEqual(conversation.codex_image_tool_model("codex-gpt-image-2"), "gpt-image-2")

    def test_extended_quality_tiers_are_preserved_for_both_variants(self):
        for model in ("gpt-image-2.6-sunburst", "gpt-image-2.6-flare"):
            for quality in ("auto", "low", "medium", "high", "xhigh", "max"):
                with self.subTest(model=model, quality=quality):
                    self.assertEqual(normalize_codex_image_quality(model, quality), quality)
        self.assertEqual(normalize_codex_image_quality("gpt-image-2", "max"), "high")

    def test_models_advertise_26_only_for_codex_paid_accounts(self):
        for source in ("web", "codex"):
            with self.subTest(source=source), mock.patch.object(
                openai_v1_models.model_catalog_service, "list_models", return_value={"data": []}
            ), mock.patch.object(openai_v1_models.account_service, "list_accounts", return_value=[
                {"source_type": source, "type": "Pro", "access_token": "test-token"}
            ]):
                ids = {item["id"] for item in openai_v1_models.list_models()["data"]}
                for model in CODEX_IMAGE_26_MODELS:
                    self.assertEqual(model in ids, source == "codex")
                    self.assertEqual(f"pro-{model}" in ids, source == "codex")
                    self.assertNotIn(f"plus-{model}", ids)

    def test_generation_and_edit_request_payloads_pin_the_requested_model(self):
        backend = OpenAIBackendAPI.__new__(OpenAIBackendAPI)
        backend.access_token = "test-token"
        backend.base_url = "https://chatgpt.com"
        for model in (None, "gpt-image-2.6-sunburst", "gpt-image-2.6-flare"):
            for images, action in (([], "generate"), (["data:image/png;base64,dGVzdA=="], "edit")):
                with self.subTest(model=model, action=action), mock.patch.object(
                    backend, "_ensure_codex_source_account"
                ), mock.patch.object(backend, "_codex_responses_headers", return_value={}), mock.patch.object(
                    backend_module.account_service, "get_account", return_value={}
                ), mock.patch.object(backend_module.account_service, "_decode_jwt_payload", return_value={}), mock.patch.object(
                    backend_module.urllib.request, "urlopen"
                ) as urlopen, mock.patch.object(backend, "_iter_codex_response_events", return_value=iter([])):
                    kwargs = {"image_model": model} if model else {}
                    list(backend.iter_codex_image_response_events("test image", images=images, quality="max", **kwargs))
                    payload = json.loads(urlopen.call_args.args[0].data)
                    self.assertEqual(payload["model"], "gpt-6.1-sol")
                    self.assertEqual(payload["tools"][0]["model"], model or "gpt-image-2.6-sunburst")
                    self.assertEqual(payload["tools"][0]["action"], action)
                    self.assertEqual(payload["tools"][0]["quality"], "max")

    def test_new_requests_default_to_26_and_explicit_25_is_preserved(self):
        self.assertEqual(ImageGenerationRequest(prompt="cat").model, DEFAULT_IMAGE_MODEL)
        self.assertEqual(ImageGenerationTaskRequest(prompt="cat", client_task_id="new").model, DEFAULT_IMAGE_MODEL)
        self.assertEqual(chat_image_args({"prompt": "cat"})[0], DEFAULT_IMAGE_MODEL)
        self.assertEqual(_payload_from_fields({"prompt": "cat"})["model"], DEFAULT_IMAGE_MODEL)
        for model in (None, "gpt-image-2.5", "codex-gpt-image-2.5"):
            body = {"prompt": "cat", "model": model}
            with mock.patch.object(openai_v1_image_generations, "stream_image_outputs_with_pool", return_value=iter([])) as stream:
                openai_v1_image_generations.handle(body)
                self.assertEqual(stream.call_args.args[0].model, model or DEFAULT_IMAGE_MODEL)


if __name__ == "__main__":
    unittest.main()
