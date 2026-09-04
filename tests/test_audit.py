import json
import tempfile
import unittest
from pathlib import Path

from pilot_harness.audit import SCHEMA_VERSION, verify_chain
from pilot_harness.logging import JsonlLogger


class AuditChainTests(unittest.TestCase):
    def make_log(self, directory: str) -> Path:
        path = Path(directory) / "events.jsonl"
        logger = JsonlLogger(path)
        logger.write({"event": "first", "value": "可靠"})
        logger.write({"event": "second", "value": 2})
        logger.write({"event": "third", "value": 3})
        return path

    def test_valid_versioned_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_log(directory)
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            result = verify_chain(path)
            self.assertTrue(result.valid, result.error)
            self.assertEqual(result.event_count, 3)
            self.assertEqual(events[0]["schema_version"], SCHEMA_VERSION)
            self.assertEqual(events[1]["previous_hash"], events[0]["event_hash"])

    def test_many_checkpoint_replacements_remain_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            logger = JsonlLogger(path)
            for index in range(1000):
                logger.write({"event": "stress", "index": index})
            result = verify_chain(path)
            self.assertTrue(result.valid, result.error)
            self.assertEqual(result.event_count, 1000)

    def test_detects_content_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_log(directory)
            text = path.read_text(encoding="utf-8").replace('"value": 2', '"value": 9')
            path.write_text(text, encoding="utf-8")
            result = verify_chain(path)
            self.assertFalse(result.valid)
            self.assertIn("event_hash mismatch", result.error)

    def test_detects_reordering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_log(directory)
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[0], lines[1] = lines[1], lines[0]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = verify_chain(path)
            self.assertFalse(result.valid)
            self.assertIn("sequence mismatch", result.error)

    def test_detects_tail_truncation_against_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_log(directory)
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
            result = verify_chain(path)
            self.assertFalse(result.valid)
            self.assertIn("possible truncation", result.error)


if __name__ == "__main__":
    unittest.main()
