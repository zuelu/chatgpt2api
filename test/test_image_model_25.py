from __future__ import annotations

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.openai_backend_api as openai_backend_api
import services.protocol.conversation as conversation_module
from services.openai_backend_api import OpenAIBackendAPI, normalize_codex_image_quality
from services.protocol.conversation import codex_image_tool_model
from utils.helper import is_codex_image_model, is_supported_image_model


class FakeImageConfig:
    def __init__(
        self,
        default: str = "gpt-5-5",
        default_25: str = "",
        codex_25: str = "gpt-image-2.5-flare",
        thinking: str = "auto",
    ) -> None:
        self.default_upstream_model_name = default
        self.default_upstream_model_name_25 = default_25
        self.codex_image_model_25_name = codex_25
        self.default_thinking_effort = thinking


class ImageModel25SettingTests(unittest.TestCase):
    def test_image_model_settings_for_gpt_image_2_5_uses_dedicated_upstream_model(self) -> None:
        with mock.patch.object(
            openai_backend_api,
            "config",
            FakeImageConfig(default_25="gpt-5.6-luna-extended"),
        ):
            backend = OpenAIBackendAPI()
            self.assertEqual(
                backend._image_model_settings("gpt-image-2.5"),
                ("gpt-5.6-luna", "extended"),
            )

    def test_image_model_settings_for_gpt_image_2_5_falls_back_to_default(self) -> None:
        with mock.patch.object(openai_backend_api, "config", FakeImageConfig(default_25="")):
            backend = OpenAIBackendAPI()
            self.assertEqual(
                backend._image_model_settings("gpt-image-2.5"),
                ("gpt-5-5", ""),
            )

    def test_image_model_settings_keeps_existing_mappings(self) -> None:
        with mock.patch.object(openai_backend_api, "config", FakeImageConfig()):
            backend = OpenAIBackendAPI()
            self.assertEqual(backend._image_model_settings("gpt-image-2"), ("gpt-5-5", ""))
            self.assertEqual(
                backend._image_model_settings("codex-gpt-image-2"),
                ("codex-gpt-image-2", ""),
            )
            self.assertEqual(
                backend._image_model_settings("codex-gpt-image-2.5"),
                ("codex-gpt-image-2.5", ""),
            )
            self.assertEqual(backend._image_model_settings("unknown-model"), ("auto", ""))


class CodexImageQualityTests(unittest.TestCase):
    def test_quality_tiers_for_legacy_tool_model(self) -> None:
        self.assertEqual(normalize_codex_image_quality("gpt-image-2", "auto"), "auto")
        self.assertEqual(normalize_codex_image_quality("gpt-image-2", "high"), "high")
        self.assertEqual(normalize_codex_image_quality("gpt-image-2", "xhigh"), "high")
        self.assertEqual(normalize_codex_image_quality("gpt-image-2", "max"), "high")
        # 未识别档位保持透传，不改变既有行为
        self.assertEqual(normalize_codex_image_quality("gpt-image-2", "hd"), "hd")
        self.assertEqual(normalize_codex_image_quality("gpt-image-2", ""), "auto")

    def test_quality_tiers_for_25_tool_models(self) -> None:
        for tool_model in ("gpt-image-2.5-flare", "gpt-image-2.5-sunburst"):
            self.assertEqual(normalize_codex_image_quality(tool_model, "xhigh"), "xhigh")
            self.assertEqual(normalize_codex_image_quality(tool_model, "max"), "max")
            self.assertEqual(normalize_codex_image_quality(tool_model, "high"), "high")
            self.assertEqual(normalize_codex_image_quality(tool_model, ""), "auto")


class CodexImageToolModelTests(unittest.TestCase):
    def test_codex_image_tool_model_maps_25_alias_to_configured_tool_model(self) -> None:
        with mock.patch.object(
            conversation_module,
            "config",
            FakeImageConfig(codex_25="gpt-image-2.5-sunburst"),
        ):
            self.assertEqual(codex_image_tool_model("codex-gpt-image-2.5"), "gpt-image-2.5-sunburst")
            self.assertEqual(codex_image_tool_model("plus-codex-gpt-image-2.5"), "gpt-image-2.5-sunburst")

    def test_codex_image_tool_model_keeps_default_for_other_models(self) -> None:
        with mock.patch.object(conversation_module, "config", FakeImageConfig()):
            self.assertEqual(codex_image_tool_model("codex-gpt-image-2"), "gpt-image-2")
            self.assertEqual(codex_image_tool_model("gpt-image-2.5"), "gpt-image-2")
            self.assertEqual(codex_image_tool_model("gpt-image-2"), "gpt-image-2")


class CodexImageRequestTests(unittest.TestCase):
    def test_image_requests_use_supported_main_model_and_preserve_tool_action(self) -> None:
        backend = OpenAIBackendAPI.__new__(OpenAIBackendAPI)
        backend.access_token = "test-token"
        backend.base_url = "https://chatgpt.com"
        event = {"type": "response.completed"}

        for images, action in (([], "generate"), (["data:image/png;base64,dGVzdA=="], "edit")):
            with self.subTest(action=action), mock.patch.object(
                openai_backend_api.account_service, "get_account", return_value={"source_type": "codex"}
            ), mock.patch.object(
                openai_backend_api.account_service, "_decode_jwt_payload", return_value={}
            ), mock.patch.object(
                openai_backend_api.urllib.request, "urlopen"
            ) as urlopen, mock.patch.object(
                backend, "_iter_codex_response_events", return_value=iter([event])
            ):
                self.assertEqual(
                    list(backend.iter_codex_image_response_events("test image", images=images, image_model="gpt-image-2.5-sunburst")),
                    [event],
                )
                urlopen.assert_called_once()
                request = urlopen.call_args.args[0]
                payload = json.loads(request.data)
                self.assertEqual(request.full_url, "https://chatgpt.com/backend-api/codex/responses")
                self.assertEqual(payload["model"], "gpt-6.1-sol")
                self.assertEqual(payload["tools"][0]["model"], "gpt-image-2.5-sunburst")
                self.assertEqual(payload["tools"][0]["action"], action)
                self.assertEqual(payload["tool_choice"], {"type": "image_generation"})
                self.assertFalse(payload["store"])


class ImageModel25HelperTests(unittest.TestCase):
    def test_new_models_are_supported_and_classified(self) -> None:
        self.assertTrue(is_supported_image_model("gpt-image-2.5"))
        self.assertTrue(is_supported_image_model("codex-gpt-image-2.5"))
        self.assertTrue(is_codex_image_model("codex-gpt-image-2"))
        self.assertTrue(is_codex_image_model("codex-gpt-image-2.5"))
        self.assertTrue(is_codex_image_model("pro-codex-gpt-image-2.5"))
        self.assertFalse(is_codex_image_model("gpt-image-2.5"))
        self.assertFalse(is_codex_image_model("gpt-image-2"))
        self.assertFalse(is_supported_image_model("unknown-image-model"))


if __name__ == "__main__":
    unittest.main()
