"""Logging setup and progress monitoring for the evolution loop."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from genetic.config import STATE_DIR, TICK_INTERVAL_SECONDS
from genetic.evolution import evaluate_fitness

if TYPE_CHECKING:
    from genetic.bot import GeneticBot


def setup_logging() -> logging.Logger:
    """Configure dual logging: file + console."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("evolution")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on re-init
    if logger.handlers:
        return logger

    # File handler: full debug log
    fh = logging.FileHandler(STATE_DIR / "evolution.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    # Console handler: info and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def log_tick_progress(
    logger: logging.Logger,
    gen_num: int,
    tick_count: int,
    bots: list[GeneticBot],
):
    """Log periodic progress during a generation."""
    elapsed_hrs = tick_count * TICK_INTERVAL_SECONDS / 3600
    rois = [b.account.roi_pct for b in bots]
    active = sum(1 for b in bots if b.account.total_trades > 0)
    open_pos = sum(b.account.n_open for b in bots)
    total_trades = sum(b.account.total_trades for b in bots)
    total_settled = sum(b.account.n_settled for b in bots)

    best = max(rois) if rois else 0
    median = sorted(rois)[len(rois) // 2] if rois else 0

    logger.info(
        f"[Gen {gen_num} | {elapsed_hrs:.1f}h] "
        f"Active: {active}/{len(bots)} | "
        f"Open: {open_pos} | Trades: {total_trades} | Settled: {total_settled} | "
        f"Best ROI: {best:.1f}% | Med ROI: {median:.1f}%"
    )


def log_generation_summary(
    logger: logging.Logger,
    gen_num: int,
    bots: list[GeneticBot],
    fitness: list[float],
):
    """Log a complete generation summary with leaderboard."""
    ranked = sorted(zip(fitness, bots), key=lambda x: x[0], reverse=True)

    logger.info(f"\n{'=' * 70}")
    logger.info(f"GENERATION {gen_num} RESULTS")
    logger.info(f"{'=' * 70}")
    logger.info(
        f"{'Rank':<5} {'Bot ID':<14} {'ROI%':>8} {'Trades':>7} "
        f"{'Settled':>8} {'WinRate':>8} {'Signal':>15}"
    )
    logger.info("-" * 70)

    for i, (fit, bot) in enumerate(ranked[:20]):
        p = bot.params
        logger.info(
            f"{i + 1:<5} {bot.bot_id:<14} {fit:>7.1f}% "
            f"{bot.account.total_trades:>7} "
            f"{bot.account.n_settled:>8} "
            f"{bot.account.win_rate * 100:>7.1f}% "
            f"{p['signal_type']:>15}"
        )

    # Signal type distribution
    signal_dist: dict[str, int] = {}
    for _, bot in ranked:
        st = bot.params["signal_type"]
        signal_dist[st] = signal_dist.get(st, 0) + 1
    logger.info(f"\nSignal distribution: {signal_dist}")

    # Category preferences of top 10
    top_cats: dict[str, int] = {}
    for _, bot in ranked[:10]:
        for cat in bot.params["categories"]:
            top_cats[cat] = top_cats.get(cat, 0) + 1
    if top_cats:
        sorted_cats = sorted(top_cats.items(), key=lambda x: x[1], reverse=True)[:5]
        logger.info(f"Top-10 category prefs: {dict(sorted_cats)}")


def compute_generation_stats(bots: list[GeneticBot]) -> dict:
    """Compute summary stats for a completed generation."""
    fitness = [evaluate_fitness(b) for b in bots]
    trades = [b.account.total_trades for b in bots]
    win_rates = [b.account.win_rate * 100 for b in bots]
    sorted_fitness = sorted(fitness)

    return {
        "best_roi": sorted_fitness[-1] if sorted_fitness else 0,
        "median_roi": sorted_fitness[len(sorted_fitness) // 2] if sorted_fitness else 0,
        "worst_roi": sorted_fitness[0] if sorted_fitness else 0,
        "mean_roi": sum(fitness) / len(fitness) if fitness else 0,
        "mean_trades": sum(trades) / len(trades) if trades else 0,
        "max_trades": max(trades) if trades else 0,
        "mean_win_rate": sum(win_rates) / len(win_rates) if win_rates else 0,
        "total_settled": sum(b.account.n_settled for b in bots),
        "active_bots": sum(1 for b in bots if b.account.total_trades > 0),
    }
