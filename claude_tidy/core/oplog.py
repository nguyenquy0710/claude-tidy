from __future__ import annotations

import json
import logging
from typing import Any

from claude_tidy.core.paths import ClaudePaths

log = logging.getLogger(__name__)


def append_record(paths: ClaudePaths, record: dict[str, Any]) -> None:
    paths.app_dir.mkdir(parents=True, exist_ok=True)
    with paths.oplog_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_records(paths: ClaudePaths) -> list[dict[str, Any]]:
    try:
        lines = paths.oplog_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            log.warning("Skipping malformed operation log line")
    return records
