"""CsvFileProvider — offline replay from checked-in fixtures.

Backs the provider contract tests (NFR-5.3) and the golden-dataset regression
(NFR-5.2). Touches no network, so the whole metric layer can be exercised
with no credentials and no upstream availability.

Layout::

    <root>/instruments.csv     tradingsymbol,name,isin,series,industry,sector
    <root>/candles/<SYMBOL>.csv  trade_date,open,high,low,close,volume[,...]
    <root>/actions/<SYMBOL>.csv  ex_date,action_type,ratio_from,ratio_to,amount
    <root>/index/<NAME>.csv      trade_date,open,high,low,close,volume
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from alpha500.providers.base import MarketDataProvider
from alpha500.providers.models import (
    ActionType,
    Candle,
    CorporateAction,
    Instrument,
    ProviderError,
    stable_token,
)


def _d(text: str) -> date:
    return datetime.strptime(text.strip()[:10], "%Y-%m-%d").date()


def _f(text: str | None) -> float | None:
    if text is None or not text.strip():
        return None
    return float(text)


class CsvFileProvider(MarketDataProvider):
    name = "CSV_FIXTURE"

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        if not self.root.exists():
            raise ProviderError(f"fixture root does not exist: {self.root}")

    def list_instruments(self) -> Sequence[Instrument]:
        path = self.root / "instruments.csv"
        if not path.exists():
            raise ProviderError(f"missing {path}")
        out: list[Instrument] = []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                symbol = (row.get("tradingsymbol") or "").strip()
                if not symbol:
                    continue
                isin = (row.get("isin") or "").strip() or None
                out.append(
                    Instrument(
                        instrument_token=stable_token(isin, symbol),
                        tradingsymbol=symbol,
                        name=(row.get("name") or "").strip() or None,
                        isin=isin,
                        series=(row.get("series") or "EQ").strip(),
                        industry=(row.get("industry") or "").strip() or None,
                        sector=(row.get("sector") or "").strip() or None,
                    )
                )
        return out

    def _read_candles(self, path: Path, start: date, end: date) -> tuple[Candle, ...]:
        if not path.exists():
            return ()
        out: list[Candle] = []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                trade_date = _d(row["trade_date"])
                if trade_date < start or trade_date > end:
                    continue
                close = float(row["close"])
                out.append(
                    Candle(
                        trade_date=trade_date,
                        open=float(row.get("open") or close),
                        high=float(row.get("high") or close),
                        low=float(row.get("low") or close),
                        close=close,
                        volume=int(float(row.get("volume") or 0)),
                        traded_value=_f(row.get("traded_value")),
                        vwap=_f(row.get("vwap")),
                        delivery_qty=int(float(row["delivery_qty"]))
                        if row.get("delivery_qty")
                        else None,
                        delivery_pct=_f(row.get("delivery_pct")),
                    )
                )
        return tuple(sorted(out, key=lambda c: c.trade_date))

    def get_daily_candles(
        self, instrument: Instrument, start: date, end: date
    ) -> Sequence[Candle]:
        return self._read_candles(
            self.root / "candles" / f"{instrument.tradingsymbol}.csv", start, end
        )

    def get_index_candles(
        self, index_name: str, start: date, end: date
    ) -> Sequence[Candle]:
        return self._read_candles(self.root / "index" / f"{index_name}.csv", start, end)

    def get_corporate_actions(self, instrument: Instrument) -> Sequence[CorporateAction]:
        path = self.root / "actions" / f"{instrument.tradingsymbol}.csv"
        if not path.exists():
            return ()
        out: list[CorporateAction] = []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                out.append(
                    CorporateAction(
                        ex_date=_d(row["ex_date"]),
                        action_type=ActionType(row["action_type"].strip().upper()),
                        ratio_from=_f(row.get("ratio_from")),
                        ratio_to=_f(row.get("ratio_to")),
                        amount=_f(row.get("amount")),
                        raw_purpose=(row.get("raw_purpose") or "").strip() or None,
                    )
                )
        return tuple(out)

    def supports_delivery_data(self) -> bool:
        return True
