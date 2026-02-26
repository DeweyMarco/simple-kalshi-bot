"""Centralized market data feed shared across all bots."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from genetic.config import MARKET_CLOSE_WINDOW_HOURS, MARKET_HISTORY_MAX_TICKS

logger = logging.getLogger("evolution")


@dataclass
class MarketSnapshot:
    """Immutable snapshot of a single market's state at a point in time."""

    ticker: str
    event_ticker: str
    status: str  # "open", "closed", "settled"
    result: str  # "yes", "no", "" for unsettled
    yes_ask: float  # In dollars (0.0 - 1.0)
    no_ask: float
    yes_bid: float
    no_bid: float
    last_price: float
    volume_24h: float
    open_interest: float
    close_time: datetime | None
    category: str
    title: str
    fetched_at: datetime


@dataclass
class MarketHistory:
    """Rolling price history for a single market."""

    ticker: str
    yes_ask_history: list[tuple[datetime, float]] = field(default_factory=list)

    def append(self, ts: datetime, yes_ask: float):
        self.yes_ask_history.append((ts, yes_ask))
        if len(self.yes_ask_history) > MARKET_HISTORY_MAX_TICKS:
            self.yes_ask_history = self.yes_ask_history[-MARKET_HISTORY_MAX_TICKS:]


class MarketDataFeed:
    """
    Centralized market data fetcher. Runs in its own thread.
    All bots read from shared state via the public read methods.
    """

    def __init__(self, client, poll_interval: float = 30.0):
        self.client = client
        self.poll_interval = poll_interval
        self._lock = threading.RLock()

        # Current open markets: ticker -> MarketSnapshot
        self.markets: dict[str, MarketSnapshot] = {}

        # Price history: ticker -> MarketHistory
        self.histories: dict[str, MarketHistory] = {}

        # Recently settled: ticker -> MarketSnapshot (kept for 2 hours)
        self.settled: dict[str, MarketSnapshot] = {}

        # Event category map: event_ticker -> category
        self.event_categories: dict[str, str] = {}

        # All known categories
        self.known_categories: list[str] = []

        self._running = False
        self._thread: threading.Thread | None = None
        self._fetch_count = 0
        self._error_count = 0
        self._last_category_refresh = 0.0

    def start(self):
        """Start the background fetch thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background fetch thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)

    def _run_loop(self):
        # Initial category fetch
        self._fetch_event_categories()

        while self._running:
            try:
                self._fetch_all_markets()
                self._check_settlements()
                self._fetch_count += 1

                # Refresh categories every 5 minutes
                if time.time() - self._last_category_refresh > 300:
                    self._fetch_event_categories()

            except Exception as e:
                self._error_count += 1
                logger.error(f"MarketDataFeed error: {e}")

            time.sleep(self.poll_interval)

    def _fetch_event_categories(self):
        """Fetch all open events to build category map."""
        cursor = None
        all_categories = {}
        try:
            while True:
                resp = self.client.get_events(status="open", limit=200, cursor=cursor)
                for event in resp.get("events", []):
                    eticker = event.get("event_ticker", "")
                    cat = event.get("category", "unknown")
                    all_categories[eticker] = cat
                cursor = resp.get("cursor", "")
                if not cursor:
                    break
                time.sleep(0.1)

            with self._lock:
                self.event_categories.update(all_categories)
                self.known_categories = sorted(set(self.event_categories.values()))

            self._last_category_refresh = time.time()
            logger.debug(
                f"Refreshed categories: {len(all_categories)} events, "
                f"{len(self.known_categories)} categories"
            )
        except Exception as e:
            logger.error(f"Category fetch error: {e}")

    def _fetch_all_markets(self):
        """Fetch open markets closing within the configured time window."""
        cursor = None
        new_markets: dict[str, MarketSnapshot] = {}
        now = datetime.now(timezone.utc)

        now_ts = int(time.time())
        max_close_ts = now_ts + MARKET_CLOSE_WINDOW_HOURS * 3600

        while True:
            params = {
                "status": "open",
                "limit": 1000,
                "min_close_ts": now_ts,
                "max_close_ts": max_close_ts,
            }
            if cursor:
                params["cursor"] = cursor
            resp = self.client._request("GET", "/markets", params=params, timeout=30)

            for m in resp.get("markets", []):
                snap = self._parse_market(m, now)
                if snap:
                    new_markets[snap.ticker] = snap

            cursor = resp.get("cursor", "")
            if not cursor:
                break
            time.sleep(0.05)

        with self._lock:
            self.markets = new_markets
            # Update price histories
            for ticker, snap in new_markets.items():
                if ticker not in self.histories:
                    self.histories[ticker] = MarketHistory(ticker=ticker)
                self.histories[ticker].append(snap.fetched_at, snap.yes_ask)

    def _check_settlements(self):
        """Check for recently settled markets."""
        cutoff_ts = int(time.time()) - 7200  # Last 2 hours
        now = datetime.now(timezone.utc)

        try:
            params = {"status": "settled", "limit": 200}
            resp = self.client._request("GET", "/markets", params=params, timeout=30)

            with self._lock:
                for m in resp.get("markets", []):
                    snap = self._parse_market(m, now)
                    if snap:
                        self.settled[snap.ticker] = snap

                # Prune old settlements (older than 2 hours)
                stale = [
                    t for t, s in self.settled.items()
                    if (now - s.fetched_at).total_seconds() > 7200
                ]
                for t in stale:
                    del self.settled[t]

        except Exception as e:
            logger.error(f"Settlement check error: {e}")

    def _parse_market(self, m: dict, now: datetime) -> MarketSnapshot | None:
        """Parse a market dict from the API into a MarketSnapshot."""
        ticker = m.get("ticker", "")
        if not ticker:
            return None

        event_ticker = m.get("event_ticker", "")
        close_str = m.get("close_time", "")
        close_time = None
        if close_str:
            try:
                close_time = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return MarketSnapshot(
            ticker=ticker,
            event_ticker=event_ticker,
            status=m.get("status", ""),
            result=m.get("result", ""),
            yes_ask=float(m.get("yes_ask", 0)) / 100,
            no_ask=float(m.get("no_ask", 0)) / 100,
            yes_bid=float(m.get("yes_bid", 0)) / 100,
            no_bid=float(m.get("no_bid", 0)) / 100,
            last_price=float(m.get("last_price", 0)) / 100,
            volume_24h=float(m.get("volume_24h", 0)),
            open_interest=float(m.get("open_interest", 0)),
            close_time=close_time,
            category=self.event_categories.get(event_ticker, "unknown"),
            title=m.get("title", ""),
            fetched_at=now,
        )

    # --- Public read API (called by bots) ---

    def get_open_markets(self) -> dict[str, MarketSnapshot]:
        """Return a copy of all open markets."""
        with self._lock:
            return dict(self.markets)

    def get_market(self, ticker: str) -> MarketSnapshot | None:
        """Get a specific market snapshot (open or settled)."""
        with self._lock:
            return self.markets.get(ticker) or self.settled.get(ticker)

    def get_history(self, ticker: str) -> list[tuple[datetime, float]]:
        """Get price history for a market."""
        with self._lock:
            h = self.histories.get(ticker)
            return list(h.yes_ask_history) if h else []

    def get_settlement(self, ticker: str) -> str | None:
        """Return 'yes' or 'no' if settled, else None."""
        with self._lock:
            s = self.settled.get(ticker)
            if s and s.result in ("yes", "no"):
                return s.result
            return None

    def get_categories(self) -> list[str]:
        """Return all known market categories."""
        with self._lock:
            return list(self.known_categories)

    def get_stats(self) -> dict:
        """Return feed statistics."""
        with self._lock:
            return {
                "open_markets": len(self.markets),
                "settled_markets": len(self.settled),
                "categories": len(self.known_categories),
                "fetch_count": self._fetch_count,
                "error_count": self._error_count,
            }
