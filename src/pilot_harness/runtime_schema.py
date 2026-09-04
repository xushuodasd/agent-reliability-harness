"""Dependency-free runtime validation for the harness' frozen JSON contracts."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class SchemaViolation(ValueError):
    pass


class SchemaRegistry:
    def __init__(self, schema_dir: Path):
        self.schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in schema_dir.glob("*.json")}

    def validate(self, instance: Any, schema_name: str) -> None:
        if schema_name not in self.schemas:
            raise SchemaViolation(f"unknown schema: {schema_name}")
        self._validate(instance, self.schemas[schema_name], "$")

    def _validate(self, value: Any, schema: dict[str, Any], path: str) -> None:
        if "$ref" in schema:
            target = schema["$ref"]
            if target not in self.schemas:
                raise SchemaViolation(f"{path}: unresolved schema reference {target}")
            self._validate(value, self.schemas[target], path)
            return
        if "const" in schema and value != schema["const"]:
            raise SchemaViolation(f"{path}: expected {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            raise SchemaViolation(f"{path}: value not in enum")
        kind = schema.get("type")
        checks = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
                  "string": lambda x: isinstance(x, str),
                  "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
                  "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
                  "boolean": lambda x: isinstance(x, bool), "null": lambda x: x is None}
        if kind and not checks[kind](value):
            raise SchemaViolation(f"{path}: expected {kind}")
        if isinstance(value, dict):
            missing = set(schema.get("required", ())) - set(value)
            if missing:
                raise SchemaViolation(f"{path}: missing {sorted(missing)}")
            props = schema.get("properties", {})
            if schema.get("additionalProperties") is False and set(value) - set(props):
                raise SchemaViolation(f"{path}: unexpected {sorted(set(value) - set(props))}")
            for key, item in value.items():
                if key in props:
                    self._validate(item, props[key], f"{path}.{key}")
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                raise SchemaViolation(f"{path}: too few items")
            for index, item in enumerate(value):
                self._validate(item, schema.get("items", {}), f"{path}[{index}]")
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                raise SchemaViolation(f"{path}: too short")
            if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
                raise SchemaViolation(f"{path}: pattern mismatch")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                raise SchemaViolation(f"{path}: below minimum")
            if "maximum" in schema and value > schema["maximum"]:
                raise SchemaViolation(f"{path}: above maximum")
