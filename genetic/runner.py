"""Main evolution loop - entry point for the genetic trading system."""

from __future__ import annotations

import sys
import time

from genetic.bot import GeneticBot
from genetic.config import (
    CHECKPOINT_INTERVAL_TICKS,
    GENERATION_DURATION_SECONDS,
    INITIAL_BANKROLL,
    POPULATION_SIZE,
    PROGRESS_LOG_INTERVAL_TICKS,
    SETTLEMENT_CHECK_TICKS,
    SETTLEMENT_WAIT_HOURS,
    SETTLEMENT_WAIT_POLL_SECONDS,
    TICK_INTERVAL_SECONDS,
)
from genetic.engine import PaperTradingEngine
from genetic.evolution import evaluate_fitness, evolve
from genetic.feed import MarketDataFeed
from genetic.genome import Genome
from genetic.monitor import (
    compute_generation_stats,
    log_generation_summary,
    log_tick_progress,
    setup_logging,
)
from genetic.persistence import (
    load_latest_state,
    save_checkpoint,
    save_generation_state,
    save_hall_of_fame,
)


def run_evolution():
    """Main entry point: infinite evolution loop."""
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("  GENETIC ALGORITHM TRADING BOT - KALSHI")
    logger.info("=" * 60)
    logger.info(f"Population: {POPULATION_SIZE} | Bankroll: ${INITIAL_BANKROLL}")
    logger.info(f"Generation: {GENERATION_DURATION_SECONDS / 3600:.0f}h | Tick: {TICK_INTERVAL_SECONDS}s")

    # Initialize Kalshi client
    from kalshi_client import KalshiClient

    client = KalshiClient()
    logger.info(f"Connected to Kalshi API: {client.api_base}")

    # Start shared market data feed
    feed = MarketDataFeed(client, poll_interval=TICK_INTERVAL_SECONDS)
    feed.start()
    logger.info("Market data feed started, waiting for initial data...")

    # Wait for first fetch to complete
    wait_start = time.time()
    while not feed.get_open_markets() and (time.time() - wait_start) < 60:
        time.sleep(1)

    known_categories = feed.get_categories()
    feed_stats = feed.get_stats()
    logger.info(
        f"Feed ready: {feed_stats['open_markets']} markets (closing within window), "
        f"{len(known_categories)} categories: {known_categories}"
    )

    if not feed.get_open_markets():
        logger.error("No markets found. Check API credentials and connectivity.")
        feed.stop()
        sys.exit(1)

    # Initialize or resume from saved state
    resumed = load_latest_state()
    if resumed:
        gen_num, genomes = resumed
        gen_num += 1  # Start next generation
        logger.info(f"Resumed from generation {gen_num - 1}, starting gen {gen_num}")
    else:
        gen_num = 0
        genomes = [Genome.random(generation=0) for _ in range(POPULATION_SIZE)]
        logger.info(f"Starting fresh with {POPULATION_SIZE} random genomes")

    # Infinite evolution loop
    try:
        while True:
            genomes, gen_num = _run_generation(
                logger, feed, genomes, gen_num, known_categories
            )

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user. Shutting down...")
        feed.stop()
        logger.info("Done. Resume anytime with: python -m genetic")


def _run_generation(
    logger,
    feed: MarketDataFeed,
    genomes: list[Genome],
    gen_num: int,
    known_categories: list[str],
) -> tuple[list[Genome], int]:
    """
    Run a single generation: create bots, trade, evaluate, evolve.
    Returns (next_genomes, next_gen_num).
    """
    logger.info(f"\n{'=' * 60}")
    logger.info(f"GENERATION {gen_num}")
    logger.info(f"{'=' * 60}")

    # Refresh categories in case new ones appeared
    fresh_cats = feed.get_categories()
    if fresh_cats:
        known_categories.clear()
        known_categories.extend(fresh_cats)

    # Create fresh engine and bots
    engine = PaperTradingEngine(feed)
    bots: list[GeneticBot] = []
    for genome in genomes:
        bot = GeneticBot(genome, feed, engine, known_categories, bankroll=INITIAL_BANKROLL)
        bots.append(bot)

    logger.info(f"Created {len(bots)} bots, starting trading period...")

    # Trading loop
    gen_start = time.time()
    tick_count = 0

    while (time.time() - gen_start) < GENERATION_DURATION_SECONDS:
        try:
            # Settle completed markets (targeted check every N ticks)
            if tick_count > 0 and tick_count % SETTLEMENT_CHECK_TICKS == 0:
                engine.settle_with_targeted_check()
            else:
                engine.settle_markets()

            # Each bot evaluates and trades
            for bot in bots:
                bot.tick()

            tick_count += 1

            # Periodic progress log
            if tick_count % PROGRESS_LOG_INTERVAL_TICKS == 0:
                log_tick_progress(logger, gen_num, tick_count, bots, feed)

            # Periodic checkpoint
            if tick_count % CHECKPOINT_INTERVAL_TICKS == 0:
                save_checkpoint(gen_num, bots, tick_count)

            time.sleep(TICK_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("Interrupted during generation. Saving state...")
            _save_and_log(logger, gen_num, bots, tick_count)
            raise

        except Exception as e:
            logger.error(f"Tick error: {e}", exc_info=True)
            time.sleep(TICK_INTERVAL_SECONDS)

    # Trading period complete
    logger.info(f"Generation {gen_num} trading period complete ({tick_count} ticks)")
    engine.settle_with_targeted_check()

    # Settlement wait: keep checking until positions settle or timeout
    remaining = engine.total_open_positions()
    if remaining > 0:
        logger.info(
            f"Waiting up to {SETTLEMENT_WAIT_HOURS}h for {remaining} "
            f"open positions to settle..."
        )
        wait_start = time.time()
        max_wait = SETTLEMENT_WAIT_HOURS * 3600

        try:
            while (time.time() - wait_start) < max_wait:
                engine.settle_with_targeted_check()
                settled = engine.total_settled()
                remaining = engine.total_open_positions()
                elapsed_min = (time.time() - wait_start) / 60

                logger.info(
                    f"[Settlement wait {elapsed_min:.0f}m] "
                    f"Settled: {settled} | Remaining: {remaining}"
                )

                if remaining == 0:
                    logger.info("All positions settled!")
                    break

                time.sleep(SETTLEMENT_WAIT_POLL_SECONDS)
        except KeyboardInterrupt:
            logger.info("Interrupted during settlement wait. Saving state...")
            engine.force_close_remaining()
            _save_and_log(logger, gen_num, bots, tick_count)
            raise

        if remaining > 0:
            logger.info(
                f"Settlement timeout: {remaining} positions still open, "
                f"force-closing as losses"
            )
            engine.force_close_remaining()

    _save_and_log(logger, gen_num, bots, tick_count)

    # Evolve
    next_genomes = evolve(bots)
    logger.info(f"Evolved {len(next_genomes)} genomes for generation {gen_num + 1}")
    return next_genomes, gen_num + 1


def _save_and_log(logger, gen_num: int, bots: list[GeneticBot], tick_count: int):
    """Evaluate fitness, save state, update hall of fame, log results."""
    fitness = [evaluate_fitness(b) for b in bots]
    stats = compute_generation_stats(bots)

    # Log results
    log_generation_summary(logger, gen_num, bots, fitness)
    logger.info(f"\nGeneration {gen_num} stats:")
    logger.info(f"  Best ROI:    {stats['best_roi']:.2f}%")
    logger.info(f"  Median ROI:  {stats['median_roi']:.2f}%")
    logger.info(f"  Mean trades: {stats['mean_trades']:.1f}")
    logger.info(f"  Active bots: {stats['active_bots']}/{len(bots)}")

    # Save generation state (all genomes + fitness)
    all_genomes = [b.genome for b in bots]
    save_generation_state(gen_num, all_genomes, fitness, stats)

    # Save hall of fame (top performers across all generations)
    ranked = sorted(zip(fitness, bots), key=lambda x: x[0], reverse=True)
    top_entries = []
    for fit, bot in ranked[:10]:
        top_entries.append({
            "genome": bot.genome.to_dict(),
            "fitness_roi_pct": fit,
            "total_trades": bot.account.total_trades,
            "settled_trades": bot.account.n_settled,
            "win_rate": bot.account.win_rate,
            "realized_pnl": bot.account.realized_pnl,
            "generation": gen_num,
            "signal_type": bot.params["signal_type"],
            "params": bot.params,
        })
    save_hall_of_fame(gen_num, top_entries)


def main():
    """CLI entry point."""
    run_evolution()


if __name__ == "__main__":
    main()
