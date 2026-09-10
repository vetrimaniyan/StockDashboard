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
    """Short, stable digest of the metric engine source.

    Line endings are normalised before hashing. They have to be: this repo
    sets ``eol=lf`` while Windows checkouts run with ``core.autocrlf=true``, so
    a plain ``git checkout`` can rewrite every one of these files without
    changing a single statement. Hashing the raw bytes made that look exactly
    like an engine change, and on 2026-09-10 it did - a branch switch after a
    merge put the dashboard into a staleness warning telling the operator the
    served rankings were not reproducible, when the code that produced them was
    byte-for-byte the code installed.

    A false staleness warning is worse than none. This project treats a stale
    number that reads as fresh as its most dangerous failure, so the signal
    that says so has to be trustworthy in both directions; one that cries wolf
    after an ordinary checkout teaches people to ignore it.
    """
    digest = hashlib.blake2b(digest_size=8)
    for name in _SOURCES:
        path = _DIR / name
        digest.update(name.encode("utf-8"))
        raw = path.read_bytes() if path.exists() else b""
        normalised = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(normalised)
    return digest.hexdigest()
