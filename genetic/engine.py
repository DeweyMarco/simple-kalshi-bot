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
        )
        acct.cash -= cost
        acct.open_positions[market_ticker] = pos
        acct.total_trades += 1
        acct.trades_today += 1
        return pos

    def settle_markets(self):
        """
        Check all open positions against settled market data.
        Called each tick by the main loop.
        """
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
