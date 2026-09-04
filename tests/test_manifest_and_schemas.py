import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from pilot_harness.audit import build_event, GENESIS_HASH
from pilot_harness.faults import FaultInjector
from pilot_harness.manifests import build_manifest, verify_manifest, write_manifest
from pilot_harness.tasks import TASK_SLICES


ROOT = Path(__file__).parents[1]
SCHEMAS = ROOT / "schemas"


def validate_minimal(instance, schema, schemas):
    """Small dependency-free validator for the schema keywords used here."""
    if "$ref" in schema:
        return validate_minimal(instance, schemas[schema["$ref"]], schemas)
    if "const" in schema and instance != schema["const"]:
        raise AssertionError(f"expected constant {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise AssertionError(f"value {instance!r} is not in enum")
    kind = schema.get("type")
    matches = {
        "object": isinstance(instance, dict),
        "array": isinstance(instance, list),
        "string": isinstance(instance, str),
        "integer": isinstance(instance, int) and not isinstance(instance, bool),
        "number": isinstance(instance, (int, float)) and not isinstance(instance, bool),
        "boolean": isinstance(instance, bool),
    }
    if kind and not matches[kind]:
        raise AssertionError(f"expected {kind}, got {type(instance).__name__}")
    if isinstance(instance, dict):
        missing = set(schema.get("required", [])) - set(instance)
        if missing:
            raise AssertionError(f"missing required fields: {sorted(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise AssertionError(f"unexpected fields: {sorted(extra)}")
        for key, value in instance.items():
            if key in properties:
                validate_minimal(value, properties[key], schemas)
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            raise AssertionError("too few items")
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in instance}) != len(instance):
            raise AssertionError("items are not unique")
        for value in instance:
            validate_minimal(value, schema.get("items", {}), schemas)
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            raise AssertionError("string is too short")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], instance):
            raise AssertionError("string does not match pattern")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise AssertionError("number is below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise AssertionError("number is above maximum")


class SchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in SCHEMAS.glob("*.json")}

    def test_all_schema_documents_are_json_schema_2020_12(self):
        self.assertGreaterEqual(len(self.schemas), 4)
        for schema in self.schemas.values():
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(schema["type"], "object")

    def test_runtime_contract_examples_validate(self):
        event = build_event({"event": "episode_start", "episode_id": "ep-1"}, 0, GENESIS_HASH)
        validate_minimal(event, self.schemas["event.schema.json"], self.schemas)
        for task in TASK_SLICES:
            validate_minimal(task.to_dict(), self.schemas["task.schema.json"], self.schemas)
        for mode in ("none", "timeout_once"):
            receipt = FaultInjector(mode).receipt().to_dict()
            validate_minimal(receipt, self.schemas["injection-receipt.schema.json"], self.schemas)
        summary = {
            "episodes": 1, "successes": 1, "success_rate": 1.0,
            "results": [{"episode_id": "ep-1", "task_id": "t-1", "success": True,
                         "reason": "verified", "steps": 1, "duration_ms": 2}],
        }
        validate_minimal(summary, self.schemas["summary.schema.json"], self.schemas)

    def test_contract_rejects_missing_required_field(self):
        with self.assertRaisesRegex(AssertionError, "missing required"):
            validate_minimal({"schema_version": "pilot-event/1"}, self.schemas["event.schema.json"], self.schemas)


class ManifestTests(unittest.TestCase):
    def test_manifest_hashes_artifacts_and_detects_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run-001"
            run_dir.mkdir()
            artifact = run_dir / "summary.json"
            artifact.write_text('{"episodes": 0}\n', encoding="utf-8")
            path = write_manifest(run_dir, metadata={"study": "smoke"})
            manifest = json.loads(path.read_text(encoding="utf-8"))
            expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
            self.assertEqual(manifest["artifacts"][0]["sha256"], expected)
            self.assertEqual(manifest["metadata"], {"study": "smoke"})
            self.assertEqual(verify_manifest(path), (True, []))
            artifact.write_text('{"episodes": 1}\n', encoding="utf-8")
            valid, errors = verify_manifest(path)
            self.assertFalse(valid)
            self.assertTrue(any("sha256 mismatch" in error for error in errors))

    def test_manifest_is_sorted_and_rejects_external_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "run-002"
            run_dir.mkdir()
            (run_dir / "z.txt").write_text("z", encoding="utf-8")
            (run_dir / "a.txt").write_text("a", encoding="utf-8")
            manifest = build_manifest(run_dir)
            self.assertEqual([item["path"] for item in manifest["artifacts"]], ["a.txt", "z.txt"])
            outside = root / "outside.txt"
            outside.write_text("no", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside run directory"):
                build_manifest(run_dir, [outside])


if __name__ == "__main__":
    unittest.main()
