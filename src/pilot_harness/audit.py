from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "pilot-event/1"
GENESIS_HASH = "0" * 64
RESERVED_FIELDS = {"schema_version", "sequence", "previous_hash", "event_hash"}


def canonical_json(value: Any) -> bytes:
    """Return the unique UTF-8 representation used as the hash input."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def event_digest(event_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(event_without_hash)).hexdigest()


def build_event(event: dict[str, Any], sequence: int, previous_hash: str) -> dict[str, Any]:
    collisions = RESERVED_FIELDS.intersection(event)
    if collisions:
        raise ValueError(f"event uses reserved audit fields: {sorted(collisions)}")
    chained = {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "previous_hash": previous_hash,
        **event,
    }
    chained["event_hash"] = event_digest(chained)
    return chained


@dataclass(frozen=True)
class ChainHead:
    sequence: int = -1
    event_hash: str = GENESIS_HASH


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    event_count: int
    final_hash: str
    error: str | None = None


def _head_path(path: Path) -> Path:
    return path.with_name(path.name + ".head.json")


def read_chain_head(path: Path) -> ChainHead:
    """Read and validate the checkpoint when resuming an existing log."""
    if not path.exists() or path.stat().st_size == 0:
        return ChainHead()
    result = verify_chain(path)
    if not result.valid:
        raise ValueError(f"cannot append to invalid audit chain: {result.error}")
    return ChainHead(result.event_count - 1, result.final_hash)


def verify_chain(path: Path, require_head: bool = True) -> VerificationResult:
    previous = GENESIS_HASH
    count = 0
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    raise ValueError(f"line {line_number}: blank line")
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError(f"line {line_number}: event is not an object")
                if event.get("schema_version") != SCHEMA_VERSION:
                    raise ValueError(f"line {line_number}: unsupported schema_version")
                if event.get("sequence") != count:
                    raise ValueError(f"line {line_number}: sequence mismatch")
                if event.get("previous_hash") != previous:
                    raise ValueError(f"line {line_number}: previous_hash mismatch")
                claimed = event.get("event_hash")
                payload = {key: value for key, value in event.items() if key != "event_hash"}
                actual = event_digest(payload)
                if claimed != actual:
                    raise ValueError(f"line {line_number}: event_hash mismatch")
                previous = actual
                count += 1

        if require_head:
            checkpoint = json.loads(_head_path(path).read_text(encoding="utf-8"))
            expected_sequence = count - 1
            if checkpoint.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("checkpoint: unsupported schema_version")
            if checkpoint.get("sequence") != expected_sequence:
                raise ValueError("checkpoint: sequence mismatch (possible truncation)")
            if checkpoint.get("event_hash") != previous:
                raise ValueError("checkpoint: final hash mismatch (possible truncation)")
        return VerificationResult(True, count, previous)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return VerificationResult(False, count, previous, str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a pilot harness JSONL audit chain")
    parser.add_argument("path", type=Path)
    parser.add_argument("--ignore-head", action="store_true", help="skip tail checkpoint verification")
    args = parser.parse_args(argv)
    result = verify_chain(args.path, require_head=not args.ignore_head)
    print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
