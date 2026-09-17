import tempfile
import unittest
from pathlib import Path

from services.log_service import LogService


class LogServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "logs.jsonl"
        self.service = LogService(self.log_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_clear_all_logs(self) -> None:
        self.service.add("call", "call log 1")
        self.service.add("call", "call log 2")
        self.service.add("account", "account log 1")

        result = self.service.clear()

        self.assertEqual(result["removed"], 3)
        self.assertEqual(self.service.list(), [])
        self.assertEqual(self.log_path.read_text(encoding="utf-8"), "")

    def test_clear_by_type_preserves_other_and_malformed_lines(self) -> None:
        self.service.add("call", "call log 1")
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write("malformed\n")
        self.service.add("account", "account log 1")

        result = self.service.clear(type="call")

        self.assertEqual(result["removed"], 1)
        remaining = self.service.list()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["type"], "account")
        self.assertIn("malformed", self.log_path.read_text(encoding="utf-8"))

    def test_clear_missing_file_is_noop(self) -> None:
        self.assertEqual(self.service.clear(type="call"), {"removed": 0})


if __name__ == "__main__":
    unittest.main()
