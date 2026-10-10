"""Scoped execution records. This module has no process-management behavior."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


@contextmanager
def execution(directory: Path, purpose: str):
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    record = {
        "started_utc": now.isoformat(),
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "command": [sys.executable, *sys.argv],
        "cwd": str(Path.cwd()),
        "purpose": purpose,
        "intentional_stop_requests": [],
        "status": "running",
    }
    filename = directory / f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}_{os.getpid()}.json"
    try:
        yield record
        record["status"] = "complete"
    except BaseException as error:
        record["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        record["error"] = f"{type(error).__name__}: {error}"
        if isinstance(error, KeyboardInterrupt):
            record["intentional_stop_requests"].append("KeyboardInterrupt in this owned process")
        raise
    finally:
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        filename.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8")
