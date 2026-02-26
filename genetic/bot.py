"""GeneticBot - individual bot that uses a genome to make trading decisions."""

from __future__ import annotations

import random
import statistics
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from genetic.genome import Genome, decode_genome

if TYPE_CHECKING:
    from genetic.engine import BotAccount, PaperTradingEngine
    from genetic.feed import MarketDataFeed, MarketSnapshot


class GeneticBot:
    """
    A single bot in the population. Holds a genome, decodes it into
    parameters, and makes trading decisions based on shared market data.
    """

    def __init__(
        self,
        genome: Genome,
        feed: MarketDataFeed,
        engine: PaperTradingEngine,
        known_categories: list[str],
        bankroll: float = 100.0,
    ):
        self.genome = genome
        self.feed = feed
        self.engine = engine
        self.params = decode_genome(genome, known_categories)
        self.bot_id = f"bot_{genome.id}"

        # Create paper account
        self.account: BotAccount = engine.create_account(self.bot_id, bankroll)

    def tick(self):
        """Called every data cycle. Evaluate all markets, maybe trade."""
        acct = self.account
        params = self.params

        # Check daily limits
        if acct.trades_today >= params["max_trades_per_day"]:
            return
        if acct.daily_pnl <= -(acct.equity * params["daily_loss_limit_pct"]):
            return
        if acct.n_open >= params["max_concurrent"]:
            return

        # Get all open markets
        markets = self.feed.get_open_markets()

        for ticker, snap in markets.items():
            # Already have position?
            if ticker in acct.open_positions:
                continue

            # Market filter
            if not self._passes_market_filter(snap):
                continue

            # Generate signal
            signal = self._generate_signal(snap)
            if signal is None:
                continue

            side, _confidence = signal

            # Apply side bias
            side = self._apply_side_bias(side)

            # Position sizing
            alloc = acct.equity * params["bankroll_fraction"]
            max_alloc = acct.equity * params["max_single_market_pct"]
            alloc = min(alloc, max_alloc, acct.cash)

            if alloc < 0.01:
                continue

            # Execute
            self.engine.try_buy(self.bot_id, ticker, side, alloc)

            # Re-check limits after each trade
            if acct.trades_today >= params["max_trades_per_day"]:
                break
            if acct.n_open >= params["max_concurrent"]:
                break

    def _passes_market_filter(self, snap: MarketSnapshot) -> bool:
        """Check if a market passes this bot's filter criteria."""
        p = self.params

        # Note: volume_24h and open_interest are often 0 in the API response,
        # so we only filter on them when they're actually populated
        if snap.volume_24h > 0 and snap.volume_24h < p["min_volume_24h"]:
            return False
        if snap.open_interest > 0 and snap.open_interest < p["min_open_interest"]:
            return False
        if snap.category not in p["categories"]:
            return False

        # Time to expiry
        if snap.close_time:
            now = datetime.now(timezone.utc)
            tte_hrs = (snap.close_time - now).total_seconds() / 3600
            if tte_hrs < p["min_time_to_expiry_hrs"]:
                return False
            if tte_hrs > p["max_time_to_expiry_hrs"]:
                return False

        # Price filter: at least one side must be in range
        yes_in = p["min_price"] <= snap.yes_ask <= p["max_price"]
        no_in = p["min_price"] <= snap.no_ask <= p["max_price"]
        if not yes_in and not no_in:
            return False

        return True

    def _generate_signal(self, snap: MarketSnapshot) -> tuple[str, float] | None:
        """
        Generate a trading signal for a market.
        Returns (side, confidence) or None if no signal.
        """
        signal_type = self.params["signal_type"]

        if signal_type == "price_level":
            return self._signal_price_level(snap)
        elif signal_type == "momentum":
            return self._signal_momentum(snap)
        elif signal_type == "mean_reversion":
            return self._signal_mean_reversion(snap)
        elif signal_type == "value":
            return self._signal_value(snap)
        elif signal_type == "contrarian":
            return self._signal_contrarian(snap)
        return None

    def _signal_price_level(self, snap: MarketSnapshot) -> tuple[str, float] | None:
        """Buy when ask is in a specific price range."""
        p = self.params
        lo, hi = p["price_threshold_low"], p["price_threshold_high"]
        if lo <= snap.yes_ask <= hi:
            return ("yes", snap.yes_ask)
        if lo <= snap.no_ask <= hi:
            return ("no", snap.no_ask)
        return None

    def _signal_momentum(self, snap: MarketSnapshot) -> tuple[str, float] | None:
        """Buy based on price direction over lookback window."""
        p = self.params
        history = self.feed.get_history(snap.ticker)
        lookback = p["momentum_lookback_ticks"]
        if len(history) < lookback + 1:
            return None
        old_price = history[-(lookback + 1)][1]
        cur_price = history[-1][1]
        if old_price == 0:
            return None
        pct_change = (cur_price - old_price) / old_price
        trigger = p["momentum_trigger_pct"]
        if pct_change > trigger:
            return ("yes", abs(pct_change))
        elif pct_change < -trigger:
            return ("no", abs(pct_change))
        return None

    def _signal_mean_reversion(self, snap: MarketSnapshot) -> tuple[str, float] | None:
        """Buy when price deviates from rolling mean by z-score threshold."""
        p = self.params
        history = self.feed.get_history(snap.ticker)
        if len(history) < 10:
            return None
        prices = [h[1] for h in history]
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices) if len(prices) > 1 else 0.001
        if stdev < 0.001:
            return None
        z = (prices[-1] - mean) / stdev
        threshold = p["mean_rev_zscore"]
        if z > threshold:  # Price way above mean -> expect drop
            return ("no", abs(z))
        elif z < -threshold:  # Price way below mean -> expect rise
            return ("yes", abs(z))
        return None

    def _signal_value(self, snap: MarketSnapshot) -> tuple[str, float] | None:
        """Buy whichever side is cheapest (edge vs 50/50 fair value)."""
        p = self.params
        edge_min = p["value_edge_min"]
        yes_edge = 0.50 - snap.yes_ask  # Positive if yes is cheap
        no_edge = 0.50 - snap.no_ask  # Positive if no is cheap
        if yes_edge > edge_min:
            return ("yes", yes_edge)
        if no_edge > edge_min:
            return ("no", no_edge)
        return None

    def _signal_contrarian(self, snap: MarketSnapshot) -> tuple[str, float] | None:
        """Bet against the crowd when market is very confident."""
        p = self.params
        threshold = p["contrarian_threshold"]
        if snap.yes_ask > threshold:
            return ("no", snap.yes_ask - threshold)
        if snap.no_ask > threshold:
            return ("yes", snap.no_ask - threshold)
        return None

    def _apply_side_bias(self, signal_side: str) -> str:
        """Apply genome-encoded side bias to the signal."""
        p = self.params
        bias = p["side_bias"]
        if bias < 0.2:
            return "no"
        elif bias > 0.8:
            return "yes"
        # Middle range: follow signal with possible flip
        if random.random() < p["side_flip_prob"]:
            return "no" if signal_side == "yes" else "yes"
        return signal_side
