"""FR-18.1 — the tracked sectoral and thematic index universe.

A versioned list, not a runtime derivation. NSE publishes well over a hundred
indices; which of them this product tracks is a product decision, and deriving
it from whatever the archive happens to serve would let an upstream addition
silently change what the dashboard ranks.

Membership was established by probe on 2026-09-07 (B-10): these are the indices
whose NSE constituent list resolves. Nifty Capital Markets is deliberately
absent — its archive slug did not resolve against any candidate tried, and an
entry that cannot be fetched is worse than an entry that is missing.

Strategy and factor indices (Alpha, Quality, Low Volatility, Equal Weight) are
excluded by FR-18.1. They measure a factor applied across sectors rather than a
sector, and ranking them beside sectoral indices invites a rotation conclusion
the data does not support.

``documented_inception`` is deliberately hand-maintained and currently unknown
for every index. No source this system can reach states an index's launch date,
and FR-18.2 reads this field to decide whether a peak may be called an all-time
high. ``None`` means "not established", which resolves to the conservative
answer: the peak is a period high. Filling one in is a deliberate act with a
citation behind it, which is the point.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

Category = Literal["SECTORAL", "THEMATIC"]


@dataclass(frozen=True, slots=True)
class TrackedIndex:
    """One index this product tracks.

    ``name`` is the display name and the key everything else joins on. It is
    also the name NSE uses in ``ind_close_all``, which is what makes the
    close-only fallback in FR-18.2 a lookup rather than a mapping table.
    """

    name: str
    category: Category
    documented_inception: date | None = None

    @property
    def is_sectoral(self) -> bool:
        return self.category == "SECTORAL"


TRACKED: Final[tuple[TrackedIndex, ...]] = (
    # --- sectoral ---------------------------------------------------------
    TrackedIndex("Nifty Bank", "SECTORAL"),
    TrackedIndex("Nifty IT", "SECTORAL"),
    TrackedIndex("Nifty Auto", "SECTORAL"),
    TrackedIndex("Nifty Pharma", "SECTORAL"),
    TrackedIndex("Nifty FMCG", "SECTORAL"),
    TrackedIndex("Nifty Metal", "SECTORAL"),
    TrackedIndex("Nifty Realty", "SECTORAL"),
    TrackedIndex("Nifty Media", "SECTORAL"),
    TrackedIndex("Nifty PSU Bank", "SECTORAL"),
    TrackedIndex("Nifty Private Bank", "SECTORAL"),
    TrackedIndex("Nifty Financial Services", "SECTORAL"),
    TrackedIndex("Nifty Healthcare Index", "SECTORAL"),
    TrackedIndex("Nifty Consumer Durables", "SECTORAL"),
    TrackedIndex("Nifty Oil & Gas", "SECTORAL"),
    # --- thematic ---------------------------------------------------------
    TrackedIndex("Nifty Energy", "THEMATIC"),
    TrackedIndex("Nifty Infrastructure", "THEMATIC"),
    TrackedIndex("Nifty Commodities", "THEMATIC"),
    TrackedIndex("Nifty India Consumption", "THEMATIC"),
    TrackedIndex("Nifty CPSE", "THEMATIC"),
    TrackedIndex("Nifty PSE", "THEMATIC"),
    TrackedIndex("Nifty MNC", "THEMATIC"),
    TrackedIndex("Nifty Services Sector", "THEMATIC"),
    TrackedIndex("Nifty India Defence", "THEMATIC"),
    TrackedIndex("Nifty India Manufacturing", "THEMATIC"),
)

BY_NAME: Final[dict[str, TrackedIndex]] = {i.name: i for i in TRACKED}


def tracked_names() -> tuple[str, ...]:
    return tuple(i.name for i in TRACKED)
