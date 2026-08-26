"""HTTP plumbing for NSE public archives.

NSE rejects unadorned programmatic requests: a browser-like User-Agent and a
prior cookie-establishing hit on the main site are both required. This module
is the only place that knows any of that, and the only place that constructs
an NSE URL.
"""

from __future__ import annotations

import threading
from typing import Final

import httpx

from alpha500.config import settings
from alpha500.providers.base import TokenBucket, retry_with_backoff
from alpha500.providers.models import ProviderError

NSE_HOME: Final = "https://www.nseindia.com"
NSE_ARCHIVES: Final = "https://nsearchives.nseindia.com"

_BROWSER_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


class NseSession:
    """Cookie-bearing session against NSE, rate limited and retried."""

    def __init__(self, rate_per_s: float | None = None) -> None:
        self._bucket = TokenBucket(rate_per_s or settings.nse_rate_per_s)
        self._lock = threading.Lock()
        self._client: httpx.Client | None = None

    def _ensure_client(self) -> httpx.Client:
        with self._lock:
            if self._client is None:
                client = httpx.Client(
                    headers=_BROWSER_HEADERS,
                    timeout=settings.http_timeout_s,  # NFR-2.5
                    follow_redirects=True,
                    verify=True,  # NFR-4.3: never a supported config to disable
                )
                # Cookie handshake. Without this the archive returns 403.
                try:
                    client.get(NSE_HOME)
                except httpx.HTTPError as exc:
                    client.close()
                    raise ProviderError(f"NSE cookie handshake failed: {exc}") from exc
                self._client = client
            return self._client

    def get(self, url: str, *, referer: str = NSE_HOME) -> httpx.Response:
        def _do() -> httpx.Response:
            client = self._ensure_client()
            self._bucket.acquire()
            resp = client.get(url, headers={"Referer": referer})
            if resp.status_code in (401, 403):
                # Cookies went stale; drop the client so the next try re-handshakes.
                self.reset()
                resp.raise_for_status()
            resp.raise_for_status()
            return resp

        return retry_with_backoff(
            _do, max_retries=settings.max_retries, label=f"GET {url}"
        )

    def reset(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def close(self) -> None:
        self.reset()
