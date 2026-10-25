"""Structured JSON-line telemetry (the API — telemetry skeleton).

One JSON object per line on stdout, picked up by Railway logs as-is.
Field reference lives in docs/ops/telemetry.md — keep the two in sync.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

_logger = logging.getLogger("everquill.telemetry")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def emit(kind: str, **fields: Any) -> None:
    """Emit one telemetry line: {"ts": ..., "kind": kind, **fields}."""
    record: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        "kind": kind,
    }
    record.update(fields)
    _logger.info(json.dumps(record, sort_keys=True, separators=(",", ":"), default=str))
