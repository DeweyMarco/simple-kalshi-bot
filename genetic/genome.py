"""Genome definition for genetic trading bots."""

from __future__ import annotations

import copy
import random
import uuid
from dataclasses import dataclass, field


@dataclass
class Genome:
    """
    Complete strategy genome. All gene values are in [0.0, 1.0].
    Interpretation into actual parameter ranges happens in decode_genome().
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    generation: int = 0
    parent_ids: list[str] = field(default_factory=list)

    # --- Market Selection Genes (5) ---
    min_volume_24h: float = 0.5
    min_open_interest: float = 0.5
    min_time_to_expiry_hrs: float = 0.3
    max_time_to_expiry_hrs: float = 0.7
    category_mask: float = 0.5

    # --- Entry Signal Genes (8) ---
    signal_type: float = 0.5
    price_threshold_low: float = 0.3
    price_threshold_high: float = 0.7
    momentum_lookback: float = 0.5
    momentum_trigger: float = 0.5
    mean_rev_zscore: float = 0.5
    value_edge_min: float = 0.5
    contrarian_threshold: float = 0.5

    # --- Side Selection Genes (2) ---
    side_bias: float = 0.5
    side_flip_prob: float = 0.0

    # --- Position Sizing Genes (3) ---
    bankroll_fraction: float = 0.02
    max_concurrent_positions: float = 0.3
    max_single_market_pct: float = 0.5

    # --- Risk Management Genes (4) ---
    daily_loss_limit_pct: float = 0.5
    max_trades_per_day: float = 0.5
    min_price: float = 0.1
    max_price: float = 0.9

    _gene_names_cache: list[str] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    @classmethod
    def gene_names(cls) -> list[str]:
        """Return the list of evolvable gene field names."""
        skip = {"id", "generation", "parent_ids", "_gene_names_cache"}
        return [
            name
            for name in cls.__dataclass_fields__
            if name not in skip
        ]

    @classmethod
    def random(cls, generation: int = 0) -> Genome:
        """Create a genome with all genes randomized uniformly in [0, 1]."""
        g = cls(generation=generation)
        for name in cls.gene_names():
            setattr(g, name, random.random())
        return g

    def clone(self) -> Genome:
        """Deep copy this genome with a new ID."""
        g = copy.deepcopy(self)
        g.id = uuid.uuid4().hex[:8]
        return g

    def to_dict(self) -> dict:
        """Serialize genome to dict for JSON persistence."""
        skip = {"_gene_names_cache"}
        return {k: getattr(self, k) for k in self.__dataclass_fields__ if k not in skip}

    @classmethod
    def from_dict(cls, d: dict) -> Genome:
        """Deserialize genome from dict."""
        valid = {k for k in cls.__dataclass_fields__ if k != "_gene_names_cache"}
        return cls(**{k: v for k, v in d.items() if k in valid})


# Signal type names, indexed by discretized signal_type gene
SIGNAL_TYPES = ["price_level", "momentum", "mean_reversion", "value", "contrarian"]


def decode_genome(genome: Genome, known_categories: list[str]) -> dict:
    """
    Decode [0,1] gene values into actual trading parameters.

    Args:
        genome: The genome to decode
        known_categories: List of market categories discovered at runtime
    """
    n_cats = max(len(known_categories), 1)

    # Signal type: discretize into buckets
    signal_idx = min(int(genome.signal_type * len(SIGNAL_TYPES)), len(SIGNAL_TYPES) - 1)

    # Category mask: treat as a bit pattern
    cat_bits = int(genome.category_mask * (2**n_cats - 1))
    selected_cats = [
        known_categories[i]
        for i in range(n_cats)
        if cat_bits & (1 << i)
    ] or list(known_categories)  # If nothing selected, trade all

    # Time to expiry: ensure min < max (range 0-24h to match feed window)
    raw_min_tte = genome.min_time_to_expiry_hrs * 24
    raw_max_tte = genome.max_time_to_expiry_hrs * 24
    min_tte = min(raw_min_tte, raw_max_tte)
    max_tte = max(raw_min_tte, raw_max_tte, min_tte + 1)  # At least 1hr range

    # Price bounds: ensure min < max
    raw_min_price = 0.01 + genome.min_price * 0.49
    raw_max_price = 0.50 + genome.max_price * 0.49
    min_price = min(raw_min_price, raw_max_price)
    max_price = max(raw_min_price, raw_max_price)

    return {
        # Market selection
        "min_volume_24h": genome.min_volume_24h * 5_000,
        "min_open_interest": genome.min_open_interest * 2_000,
        "min_time_to_expiry_hrs": min_tte,
        "max_time_to_expiry_hrs": max_tte,
        "categories": selected_cats,

        # Entry signal
        "signal_type": SIGNAL_TYPES[signal_idx],
        "price_threshold_low": 0.01 + genome.price_threshold_low * 0.49,
        "price_threshold_high": 0.50 + genome.price_threshold_high * 0.49,
        "momentum_lookback_ticks": max(1, int(genome.momentum_lookback * 60)),
        "momentum_trigger_pct": -0.10 + genome.momentum_trigger * 0.20,
        "mean_rev_zscore": 0.5 + genome.mean_rev_zscore * 2.5,
        "value_edge_min": 0.01 + genome.value_edge_min * 0.29,
        "contrarian_threshold": 0.60 + genome.contrarian_threshold * 0.35,

        # Side selection
        "side_bias": genome.side_bias,
        "side_flip_prob": genome.side_flip_prob * 0.5,

        # Position sizing
        "bankroll_fraction": 0.005 + genome.bankroll_fraction * 0.095,
        "max_concurrent": max(1, int(genome.max_concurrent_positions * 20)),
        "max_single_market_pct": 0.01 + genome.max_single_market_pct * 0.24,

        # Risk management
        "daily_loss_limit_pct": 0.02 + genome.daily_loss_limit_pct * 0.28,
        "max_trades_per_day": max(1, int(genome.max_trades_per_day * 100)),
        "min_price": min_price,
        "max_price": max_price,
    }
