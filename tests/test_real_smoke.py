import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pilot_harness.models import Action, Task
from pilot_harness.provider import Provider
from pilot_harness.real_smoke import MAX_EPISODES, main, run_real_smoke


class FinishingProvider(Provider):
    @property
    def name(self):
        return "test-real-provider"

    def next_action(self, task, history):
        if not history:
            return Action("write_file", {"path": task.expected_path, "content": task.expected_content})
        return Action("finish", {"claim": "done"})


class FailingProvider(Provider):
    @property
    def name(self):
        return "test-failing-provider"

    def next_action(self, task, history):
        raise RuntimeError("remote unavailable")


class RealSmokeTests(unittest.TestCase):
    tasks = (Task("one", "write", "answer.txt", "ok"),)

    def test_manifest_never_records_key_value(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"PRIVATE_KEY_NAME": "top-secret"}):
            run_real_smoke(
                output=Path(directory), base_url="http://localhost/v1", model="exact-model",
                api_key_env="PRIVATE_KEY_NAME", provider=FinishingProvider(), tasks=self.tasks,
            )
            text = (Path(directory) / "manifest.json").read_text(encoding="utf-8")
            manifest = json.loads(text)
            self.assertTrue(manifest["api_key_present"])
            self.assertFalse(manifest["api_key_value_recorded"])
            self.assertNotIn("top-secret", text)

    def test_missing_key_is_recorded_in_manifest_and_exceptions_are_results(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            summary = run_real_smoke(
                output=Path(directory), base_url="http://localhost/v1", model="m",
                api_key_env="ABSENT_KEY", provider=FailingProvider(), tasks=self.tasks,
            )
            manifest = json.loads((Path(directory) / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["api_key_present"])
            self.assertEqual(summary["exceptions"], 1)
            self.assertEqual(summary["results"][0]["status"], "exception")
            self.assertIn("remote unavailable", summary["results"][0]["reason"])
            events = (Path(directory) / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("episode_exception", events)

    def test_hard_episode_cap_rejects_oversized_plan_before_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "exceeds"):
                run_real_smoke(
                    output=Path(directory), base_url="http://localhost/v1", model="m",
                    api_key_env="K", provider=FinishingProvider(), tasks=self.tasks,
                    repetitions=MAX_EPISODES + 1,
                )

    def test_cli_requires_explicit_endpoint_and_model(self):
        with self.assertRaises(SystemExit) as caught:
            main([])
        self.assertEqual(caught.exception.code, 2)

    def test_base_url_cannot_leak_embedded_credentials_or_query_tokens(self):
        for unsafe in ("https://user:secret@example.test/v1", "https://example.test/v1?key=secret"):
            with self.subTest(unsafe=unsafe), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, "must not contain"):
                    run_real_smoke(
                        output=Path(directory), base_url=unsafe, model="m", api_key_env="K",
                        provider=FinishingProvider(), tasks=self.tasks,
                    )


if __name__ == "__main__":
    unittest.main()
