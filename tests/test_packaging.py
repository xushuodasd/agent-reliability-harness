from pathlib import Path
import unittest

from pilot_harness import runtime_schema
from pilot_harness.runtime_schema import SchemaRegistry


class PackagingTests(unittest.TestCase):
    def test_runtime_schemas_are_packaged_with_the_module(self):
        package_root = Path(runtime_schema.__file__).parent
        schema_dir = package_root / "schemas"
        self.assertTrue(schema_dir.is_dir())
        registry = SchemaRegistry(schema_dir)
        self.assertIn("event.schema.json", registry.schemas)
        self.assertIn("acceptance-report.schema.json", registry.schemas)
        source_schema_dir = Path(__file__).parents[1] / "schemas"
        self.assertEqual(
            {item.name: item.read_bytes() for item in source_schema_dir.glob("*.json")},
            {item.name: item.read_bytes() for item in schema_dir.glob("*.json")},
        )


if __name__ == "__main__":
    unittest.main()
