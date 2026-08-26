"""YahooProvider — bulk historical backfill from a free source.

Chosen for backfill only. One request returns a decade of daily candles for a
symbol, so a 500-symbol cold start costs ~500 requests instead of the ~1 250
session-file downloads the bhavcopy path would need.

Two caveats drive how this is used:

* It is an unofficial endpoint with no stability contract. It is never the
  incremental source, and NseArchiveProvider cross-checks it (validation V9).
* Whether Yahoo's OHLC is already split-adjusted is not contractually stated.
  Per FR-3.2 this module asserts nothing either way: it stores what it
  receives as raw and reports observed splits separately, leaving the
  reconciliation test to establish the truth.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final, Sequence

from alpha500.config import settings
from alpha500.providers.base import MarketDataProvider, TokenBucket, retry_with_backoff
from alpha500.providers.models import (
    ActionType,
    Candle,
    CorporateAction,
    Instrument,
    ProviderError,
)

# Yahoo's ticker for the NIFTY 500 index.
_INDEX_SYMBOLS: Final[dict[str, str]] = {
    "NIFTY500": "^CRSLDX",
    "NIFTY50": "^NSEI",
}


def to_yahoo_symbol(tradingsymbol: str) -> str:
    """NSE trading symbol -> Yahoo ticker."""
    return f"{tradingsymbol.strip().upper()}.NS"


class YahooProvider(MarketDataProvider):
    name = "YAHOO"

    # Established empirically by the FR-3.2 reconciliation test, not assumed:
    # applying our own factor on top produced a +98.97% return on 360ONE's
    # 2023-03-02 ex-date, which is the signature of double adjustment.
    # Yahoo re-adjusts its whole history on every fetch, so a stored row stays
    # correct only for splits up to the date it was fetched.
    prices_are_adjusted = True

    def __init__(self, rate_per_s: float | None = None) -> None:
        self._bucket = TokenBucket(rate_per_s or settings.yahoo_rate_per_s)

    def list_instruments(self) -> Sequence[Instrument]:
        """Yahoo has no NSE universe listing.

        The constituent list is NSE's to publish (FR-1.2), so universe sync
        always goes through NseArchiveProvider.
        """
        raise NotImplementedError(
            "YahooProvider serves prices only; use NseArchiveProvider for the universe"
        )

    def _history(self, symbol: str, start: date, end: date):  # type: ignore[no-untyped-def]
        import yfinance as yf

        def _do():  # type: ignore[no-untyped-def]
            self._bucket.acquire()
            ticker = yf.Ticker(symbol)
            frame = ticker.history(
                start=start.isoformat(),
                # Yahoo's end is exclusive.
                end=(end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,  # FR-3.3: store raw, adjust via adj_factor
                actions=True,
                raise_errors=True,
            )
            return frame

        return retry_with_backoff(
            _do, max_retries=settings.max_retries, label=f"yahoo history {symbol}"
        )

    def get_daily_candles(
        self, instrument: Instrument, start: date, end: date
    ) -> Sequence[Candle]:
        symbol = to_yahoo_symbol(instrument.tradingsymbol)
        try:
            frame = self._history(symbol, start, end)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"yahoo: no candles for {symbol}: {exc}") from exc

        if frame is None or len(frame) == 0:
            return ()
        return _frame_to_candles(frame)

    def get_index_candles(
        self, index_name: str, start: date, end: date
    ) -> Sequence[Candle]:
        symbol = _INDEX_SYMBOLS.get(index_name.upper())
        if symbol is None:
            raise ProviderError(f"yahoo: no ticker mapped for index {index_name}")
        try:
            frame = self._history(symbol, start, end)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"yahoo: no index candles for {symbol}: {exc}") from exc
        if frame is None or len(frame) == 0:
            return ()
        return _frame_to_candles(frame)

    def get_corporate_actions(self, instrument: Instrument) -> Sequence[CorporateAction]:
        """Splits and dividends as reported by Yahoo.

        Bonus issues are reported as splits by Yahoo and are not distinguishable
        here; both adjust price the same way, so the metric layer is unaffected.
        The distinction matters only for display and is an open item (B-2).
        """
        import yfinance as yf

        symbol = to_yahoo_symbol(instrument.tradingsymbol)

        def _do():  # type: ignore[no-untyped-def]
            self._bucket.acquire()
            return yf.Ticker(symbol).actions

        try:
            actions = retry_with_backoff(
                _do, max_retries=settings.max_retries, label=f"yahoo actions {symbol}"
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"yahoo: actions unavailable for {symbol}: {exc}") from exc

        if actions is None or len(actions) == 0:
            return ()

        out: list[CorporateAction] = []
        for idx, row in actions.iterrows():
            ex_date = idx.date() if hasattr(idx, "date") else idx
            split = float(row.get("Stock Splits", 0.0) or 0.0)
            dividend = float(row.get("Dividends", 0.0) or 0.0)
            if split and split != 1.0:
                out.append(
                    CorporateAction(
                        ex_date=ex_date,
                        action_type=ActionType.SPLIT,
                        ratio_from=1.0,
                        ratio_to=split,
                        raw_purpose=f"Yahoo split ratio {split}",
                    )
                )
            if dividend:
                out.append(
                    CorporateAction(
                        ex_date=ex_date,
                        action_type=ActionType.DIVIDEND,
                        amount=dividend,
                        raw_purpose=f"Yahoo dividend {dividend}",
                    )
                )
        return out


def _frame_to_candles(frame) -> tuple[Candle, ...]:  # type: ignore[no-untyped-def]
    candles: list[Candle] = []
    for idx, row in frame.iterrows():
        trade_date = idx.date() if hasattr(idx, "date") else idx
        close = row.get("Close")
        if close is None or close != close:  # NaN guard
            continue
        open_ = row.get("Open")
        high = row.get("High")
        low = row.get("Low")
        volume = row.get("Volume")
        candles.append(
            Candle(
                trade_date=trade_date,
                open=float(open_) if open_ == open_ else float(close),
                high=float(high) if high == high else float(close),
                low=float(low) if low == low else float(close),
                close=float(close),
                volume=int(volume) if volume == volume else 0,
            )
        )
    return tuple(candles)
