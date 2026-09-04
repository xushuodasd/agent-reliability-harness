from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .audit import SCHEMA_VERSION, build_event, read_chain_head


class JsonlLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        head = read_chain_head(path)
        self._sequence = head.sequence + 1
        self._previous_hash = head.event_hash

    def write(self, event: dict[str, Any]) -> None:
        """Append one versioned, hash-chained event and update its tail checkpoint."""
        with self._lock:
            chained = build_event(event, self._sequence, self._previous_hash)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(chained, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._write_head(chained)
            self._previous_hash = chained["event_hash"]
            self._sequence += 1

    def _write_head(self, event: dict[str, Any]) -> None:
        head_path = self.path.with_name(self.path.name + ".head.json")
        checkpoint = {
            "schema_version": SCHEMA_VERSION,
            "sequence": event["sequence"],
            "event_hash": event["event_hash"],
        }
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=head_path.parent, prefix=head_path.name + ".",
            suffix=".tmp", delete=False,
        ) as stream:
            stream.write(json.dumps(checkpoint, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        try:
            for attempt in range(6):
                try:
                    os.replace(temporary, head_path)
                    return
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.01 * (attempt + 1))
        finally:
            if temporary.exists():
                temporary.unlink()
