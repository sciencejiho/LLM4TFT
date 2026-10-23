"""Incremental, bounded JSONL records for reproducible research sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_RECORD_BYTES = 1_048_576
MAX_JOURNAL_BYTES = 64 * MAX_RECORD_BYTES


class DecisionJournal:
    """Flush session metadata and decisions immediately to a bounded file.

    Parameters
    ----------
    path : Path
        Destination; existing files are never overwritten.
    metadata : dict
        Seed, ruleset and other public experiment configuration.
    max_records : int, default 20000
        Maximum rows including metadata and outcome.
    """

    def __init__(self, path: Path, metadata: dict[str, Any], max_records: int = 20000):
        if not 2 <= max_records <= 100_000:
            raise ValueError("Journal record limit must be between 2 and 100000")
        if path.exists():
            raise FileExistsError(f"Recording already exists: {path}")
        self.path = path
        self.max_records = max_records
        self.records = 0
        self.bytes_written = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        self.write({**metadata, "type": "metadata", "schema_version": 1})

    def write(self, record: dict[str, Any]) -> None:
        """Append one JSON row, reserving a row and full byte budget for outcome."""
        terminal = record.get("type") == "outcome"
        reserved_rows = 0 if terminal else 1
        reserved_bytes = 0 if terminal else MAX_RECORD_BYTES
        if self.records + reserved_rows >= self.max_records:
            raise RuntimeError(f"Recording record limit reached: {self.path}")
        payload = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
        size = len(payload.encode("utf-8"))
        if (
            size > MAX_RECORD_BYTES
            or self.bytes_written + size + reserved_bytes > MAX_JOURNAL_BYTES
        ):
            raise RuntimeError(f"Recording byte limit reached: {self.path}")
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(payload)
        self.records += 1
        self.bytes_written += size

    def can_record_decision(self) -> bool:
        """Check room for a maximum-size decision and its terminal outcome."""
        return (
            self.records + 2 <= self.max_records
            and self.bytes_written + 2 * MAX_RECORD_BYTES <= MAX_JOURNAL_BYTES
        )
