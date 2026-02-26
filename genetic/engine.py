"""Paper trading engine that simulates fills using real market data."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from genetic.feed import MarketDataFeed


@dataclass
class PaperPosition:
    """A single open or settled paper position."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    bot_id: str = ""
    market_ticker: str = ""
    side: str = ""  # "yes" or "no"
    contracts: int = 0
    entry_price: float = 0.0  # Per contract, in dollars
    cost: float = 0.0  # contracts * entry_price
    entry_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    close_time: datetime | None = None  # Market close time (for settlement scheduling)

    # Filled on settlement
    settled: bool = False
    result: str = ""  # "yes" or "no" -- market outcome
    payout: float = 0.0  # contracts if won, else 0
    profit: float = 0.0  # payout - cost
    settle_time: datetime | None = None


@dataclass
class BotAccount:
    """Paper trading account for one bot."""

    bot_id: str
    initial_bankroll: float = 100.0
    cash: float = 100.0
    open_positions: dict[str, PaperPosition] = field(default_factory=dict)
    closed_positions: list[PaperPosition] = field(default_factory=list)
    total_trades: int = 0
    trades_today: int = 0
    daily_pnl: float = 0.0
    last_trade_date: str = ""  # YYYY-MM-DD for daily reset

    @property
    def equity(self) -> float:
        """Total account value: cash + cost of open positions."""
        open_value = sum(p.cost for p in self.open_positions.values())
        return self.cash + open_value

    @property
    def realized_pnl(self) -> float:
        return sum(p.profit for p in self.closed_positions)

    @property
    def roi_pct(self) -> float:
        if self.initial_bankroll <= 0:
            return 0.0
        return (self.realized_pnl / self.initial_bankroll) * 100

    @property
    def win_rate(self) -> float:
        settled = [p for p in self.closed_positions if p.settled]
        if not settled:
            return 0.0
        wins = sum(1 for p in settled if p.profit > 0)
        return wins / len(settled)

    @property
    def n_settled(self) -> int:
        return len([p for p in self.closed_positions if p.settled])

    @property
    def n_open(self) -> int:
        return len(self.open_positions)

    def unrealized_pnl(self, feed: MarketDataFeed) -> float:
        """Estimate PnL of open positions using current bid prices."""
        pnl = 0.0
        for ticker, pos in self.open_positions.items():
            snap = feed.get_market(ticker)
            if not snap:
                continue
            if pos.side == "yes":
                current_value = pos.contracts * snap.yes_bid
            else:
                current_value = pos.contracts * snap.no_bid
            pnl += current_value - pos.cost
        return pnl

    def total_pnl(self, feed: MarketDataFeed) -> float:
        """Realized + unrealized PnL."""
        return self.realized_pnl + self.unrealized_pnl(feed)

    def total_roi_pct(self, feed: MarketDataFeed) -> float:
        """ROI including unrealized positions."""
        if self.initial_bankroll <= 0:
            return 0.0
        return (self.total_pnl(feed) / self.initial_bankroll) * 100


class PaperTradingEngine:
    """
    Simulates fills locally using real market data from MarketDataFeed.
    No API calls for order placement.
    """

    def __init__(self, feed: MarketDataFeed):
        self.feed = feed
        self.accounts: dict[str, BotAccount] = {}

    def create_account(self, bot_id: str, bankroll: float = 100.0) -> BotAccount:
        """Create a new paper trading account for a bot."""
        acct = BotAccount(
            bot_id=bot_id, initial_bankroll=bankroll, cash=bankroll
        )
        self.accounts[bot_id] = acct
        return acct

    def try_buy(
        self, bot_id: str, market_ticker: str, side: str, usd_amount: float
    ) -> PaperPosition | None:
        """
        Attempt to paper-buy a position.
        Returns the position if successful, None if rejected.

        Fill logic: fills at displayed ask price, integer contracts only.
        """
        acct = self.accounts.get(bot_id)
        if not acct:
            return None

        # Reset daily counters if new day
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if acct.last_trade_date != today:
            acct.trades_today = 0
            acct.daily_pnl = 0.0
            acct.last_trade_date = today

        # Get current market data
        snap = self.feed.get_market(market_ticker)
        if not snap or snap.status not in ("open", "active"):
            return None

        # Determine fill price
        if side == "yes":
            fill_price = snap.yes_ask
        elif side == "no":
            fill_price = snap.no_ask
        else:
            return None

        if fill_price <= 0 or fill_price >= 1.0:
            return None

        # Calculate contracts (integer only, like real Kalshi)
        contracts = int(usd_amount / fill_price)
        if contracts < 1:
            return None

        cost = contracts * fill_price

        # Check available cash
        if cost > acct.cash:
            contracts = int(acct.cash / fill_price)
            if contracts < 1:
                return None
            cost = contracts * fill_price

        # Don't allow duplicate positions in same market
        if market_ticker in acct.open_positions:
            return None

        # Execute paper fill
        pos = PaperPosition(
            bot_id=bot_id,
            market_ticker=market_ticker,
            side=side,
            contracts=contracts,
            entry_price=fill_price,
            cost=cost,
            close_time=snap.close_time,
        )
        acct.cash -= cost
        acct.open_positions[market_ticker] = pos
        acct.total_trades += 1
        acct.trades_today += 1
        return pos

    def get_open_tickers(self) -> set[str]:
        """Get all unique tickers with open positions across all accounts."""
        tickers: set[str] = set()
        for acct in self.accounts.values():
            tickers.update(acct.open_positions.keys())
        return tickers

    def get_closeable_tickers(self) -> set[str]:
        """Get open tickers whose markets have passed their close time."""
        now = datetime.now(timezone.utc)
        tickers: set[str] = set()
        for acct in self.accounts.values():
            for ticker, pos in acct.open_positions.items():
                if pos.close_time and pos.close_time <= now:
                    tickers.add(ticker)
        return tickers

    def total_open_positions(self) -> int:
        """Total open positions across all accounts."""
        return sum(len(a.open_positions) for a in self.accounts.values())

    def total_settled(self) -> int:
        """Total settled positions across all accounts."""
        return sum(a.n_settled for a in self.accounts.values())

    def settle_markets(self):
        """
        Check all open positions against settled market data (cached).
        Called each tick by the main loop.
        """
        self._apply_settlements()

    def settle_with_targeted_check(self):
        """
        Check specific tickers we hold via the API, then settle.
        Only checks markets that have passed their close time.
        """
        closeable = self.get_closeable_tickers()
        if closeable:
            self.feed.check_specific_tickers(closeable)
        self._apply_settlements()

    def _apply_settlements(self):
        """Apply any cached settlement data to open positions."""
        for bot_id, acct in self.accounts.items():
            to_close: list[str] = []
            for ticker, pos in acct.open_positions.items():
                result = self.feed.get_settlement(ticker)
                if result is None:
                    continue

                won = result == pos.side
                pos.settled = True
                pos.result = result
                pos.payout = float(pos.contracts) if won else 0.0
                pos.profit = pos.payout - pos.cost
                pos.settle_time = datetime.now(timezone.utc)

                acct.cash += pos.payout
                acct.daily_pnl += pos.profit
                acct.closed_positions.append(pos)
                to_close.append(ticker)

            for ticker in to_close:
                del acct.open_positions[ticker]

    def force_close_remaining(self):
        """
        Force-close all remaining open positions as total losses.
        Called after settlement timeout so fitness reflects the risk of unsettled trades.
        """
        now = datetime.now(timezone.utc)
        for acct in self.accounts.values():
            for ticker, pos in list(acct.open_positions.items()):
                pos.settled = True
                pos.result = "timeout"
                pos.payout = 0.0
                pos.profit = -pos.cost
                pos.settle_time = now

                acct.cash += pos.payout
                acct.daily_pnl += pos.profit
                acct.closed_positions.append(pos)

            acct.open_positions.clear()
