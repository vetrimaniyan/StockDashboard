"""Fingerprint of the metric engine's source.

AR-4 requires metric output to be reproducible from stored price data. That
guarantee is only meaningful if the served metrics were produced by the code
currently in the tree — and nothing otherwise notices when they were not.

Editing the engine without re-running the computation leaves `metrics_daily`
holding numbers no version of the code would now produce. Everything still
renders; the rankings are simply wrong in a way no check catches. This turns
that into a visible staleness reason (FR-8.9), the same treatment stale prices
already get.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

_DIR: Final = Path(__file__).parent

# Every module whose edit can change a metric value.
_SOURCES: Final[tuple[str, ...]] = (
    "kernels.py",
    "series.py",
    "cross_section.py",
    "engine.py",
    "periods.py",
)


def engine_fingerprint() -> str:
    """Short, stable digest of the metric engine source."""
    digest = hashlib.blake2b(digest_size=8)
    for name in _SOURCES:
        path = _DIR / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes() if path.exists() else b"")
    return digest.hexdigest()
