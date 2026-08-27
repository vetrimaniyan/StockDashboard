"""Period conventions (SRS 5.1).

Periods are trading sessions, never calendar days. FR-6.1: fixed session
counts keep holiday clusters from distorting period-over-period comparisons.
"""

from __future__ import annotations

from typing import Final

DAY: Final = 1
WEEK: Final = 5
TWO_WEEKS: Final = 10
THREE_WEEKS: Final = 15
MONTH: Final = 21
TWO_MONTHS: Final = 42
QUARTER: Final = 63
HALF_YEAR: Final = 126
NINE_MONTHS: Final = 189
YEAR: Final = 252
WEEKS_52: Final = 252

TRADING_DAYS_PER_YEAR: Final = 252
