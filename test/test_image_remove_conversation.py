import threading
import unittest
from itertools import product
from unittest import mock

from services.config import config
from services.openai_backend_api import OpenAIBackendAPI
from services.protocol import conversation
from services.protocol.conversation import _remove_image_conversation_later


class FakeBackend:
    def __init__(self) -> None:
        self.called = threading.Event()

    def delete_conversation(self, conversation_id: str) -> dict:
        self.called.set()
        return {}


class RemoveImageConversationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(config.data)

    def tearDown(self) -> None:
        config.data = self._saved

    def _removed(self, *, after_result: bool, always: bool, success: bool) -> bool:
        config.data = dict(
            self._saved,
            image_remove_conversation_after_result=after_result,
            image_remove_conversation_always=always,
        )
        backend = FakeBackend()
        _remove_image_conversation_later(backend, "conv-1", success=success)
        return backend.called.wait(2.0)

    def test_both_off_never_removes(self) -> None:
        self.assertFalse(self._removed(after_result=False, always=False, success=True))
        self.assertFalse(self._removed(after_result=False, always=False, success=False))

    def test_after_result_only_removes_on_success(self) -> None:
        self.assertTrue(self._removed(after_result=True, always=False, success=True))
        self.assertFalse(self._removed(after_result=True, always=False, success=False))

    def test_always_removes_regardless_of_success(self) -> None:
        self.assertTrue(self._removed(after_result=False, always=True, success=True))
        self.assertTrue(self._removed(after_result=False, always=True, success=False))

    def test_empty_conversation_id_is_noop(self) -> None:
        config.data = dict(self._saved, image_remove_conversation_always=True)
        backend = FakeBackend()
        _remove_image_conversation_later(backend, "", success=False)
        self.assertFalse(backend.called.wait(0.2))

    def test_retained_workbench_conversation_is_never_removed(self) -> None:
        config.data = dict(self._saved, image_remove_conversation_always=True)
        backend = FakeBackend()
        _remove_image_conversation_later(
            backend,
            "conv-1",
            success=True,
            retain_conversation=True,
        )
        self.assertFalse(backend.called.wait(0.2))


class ImageResultCleanupRegressionTests(unittest.TestCase):
    def test_successful_images_are_returned_from_all_cleanup_paths(self) -> None:
        for path, remove_after_result, retain in product(("direct", "text_retry", "fallback"), (False, True), (False, True)):
            with self.subTest(path=path, remove_after_result=remove_after_result, retain=retain):
                backend = mock.Mock(spec=OpenAIBackendAPI)
                removed = threading.Event()
                backend.delete_conversation.side_effect = lambda _id: removed.set()
                image_urls = ["https://files.test/result.png"]
                backend.resolve_conversation_image_urls.side_effect = (
                    [image_urls] if path == "direct" else [[], image_urls]
                )
                backend._poll_image_results.return_value = (["file-1"], [])
                backend.download_image_bytes.return_value = [b"test-image"]
                event = {
                    "conversation_id": "conv-1",
                    "file_ids": ["file-1"] if path == "direct" else [],
                    "text": "generation started" if path == "text_retry" else "",
                    "turn_use_case": "image gen",
                }
                data = [{"b64_json": "dGVzdC1pbWFnZQ=="}]
                request = conversation.ConversationRequest(
                    model="gpt-image-2",
                    prompt="test image",
                    response_format="b64_json",
                    retain_conversation=retain,
                )
                with (
                    mock.patch.dict(config.data, {
                        "image_remove_conversation_after_result": remove_after_result,
                        "image_remove_conversation_always": False,
                    }),
                    mock.patch.object(conversation, "conversation_events", return_value=iter([event])),
                    mock.patch.object(conversation, "_get_detailed_error_from_tasks", return_value=""),
                    mock.patch.object(conversation, "is_model_text_reply_instead_of_image", return_value=path == "text_retry"),
                    mock.patch.object(conversation, "format_image_result", return_value={"data": data}),
                    mock.patch.object(conversation.time, "sleep"),
                    mock.patch.object(conversation, "_remove_image_conversation_later", wraps=_remove_image_conversation_later) as cleanup,
                ):
                    outputs = list(conversation.stream_image_outputs(backend, request))
                    self.assertEqual(len(outputs), 1)
                    self.assertEqual(outputs[0].kind, "result")
                    self.assertEqual(outputs[0].data, data)
                    backend.download_image_bytes.assert_called_once_with(image_urls)
                    cleanup.assert_called_once_with(backend, "conv-1", success=True, retain_conversation=retain)
                    if remove_after_result and not retain:
                        self.assertTrue(removed.wait(1.0))
                    else:
                        self.assertFalse(removed.is_set())


if __name__ == "__main__":
    unittest.main()
