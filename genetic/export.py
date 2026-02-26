#!/usr/bin/env python3
"""
Export a trained genome into a standalone real trading bot.

Usage:
    # Export the best bot ever trained:
    python -m genetic.export

    # Export from a specific generation:
    python -m genetic.export --generation 5

    # Export a specific genome by ID:
    python -m genetic.export --genome-id a1b2c3d4

    # Just inspect the hall of fame (no export):
    python -m genetic.export --show
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from genetic.config import STATE_DIR
from genetic.genome import Genome, SIGNAL_TYPES, decode_genome
from genetic.persistence import load_hall_of_fame, load_generation


def show_hall_of_fame():
    """Print the hall of fame leaderboard."""
    hof = load_hall_of_fame()
    if not hof:
        print("No hall of fame found. Run the evolution first: python -m genetic")
        return

    print(f"\n{'=' * 75}")
    print(f"  HALL OF FAME  (updated: {hof['updated_at'][:19]})")
    print(f"  Latest generation: {hof['latest_generation']}")
    print(f"{'=' * 75}")
    print(
        f"{'Rank':<5} {'Genome':<10} {'Gen':<5} {'ROI%':>8} "
        f"{'Trades':>7} {'WinRate':>8} {'PnL':>8} {'Signal':>15}"
    )
    print("-" * 75)

    for i, entry in enumerate(hof["entries"]):
        print(
            f"{i + 1:<5} {entry['genome']['id']:<10} "
            f"{entry['generation']:<5} "
            f"{entry['fitness_roi_pct']:>7.1f}% "
            f"{entry['settled_trades']:>7} "
            f"{entry['win_rate'] * 100:>7.1f}% "
            f"${entry['realized_pnl']:>7.2f} "
            f"{entry['signal_type']:>15}"
        )

    print()
    best = hof["best_ever"]
    if best:
        print(f"Best ever: genome {best['genome']['id']} "
              f"({best['fitness_roi_pct']:.1f}% ROI, gen {best['generation']})")
        print(f"\nTo export as a real bot:")
        print(f"  python -m genetic.export --genome-id {best['genome']['id']}")


def get_genome_from_hof(genome_id: str | None = None) -> tuple[dict, dict] | None:
    """Get a genome entry from the hall of fame."""
    hof = load_hall_of_fame()
    if not hof or not hof["entries"]:
        return None

    if genome_id:
        for entry in hof["entries"]:
            if entry["genome"]["id"] == genome_id:
                return entry, entry["genome"]
        return None

    # Default: best ever
    best = hof["best_ever"]
    return best, best["genome"]


def get_genome_from_generation(generation: int, genome_id: str | None = None) -> tuple[dict, dict] | None:
    """Get a genome from a specific generation file."""
    state = load_generation(generation)
    if not state:
        print(f"Generation {generation} not found.")
        return None

    genomes = state["genomes"]
    fitness = state.get("fitness_scores", [])

    if genome_id:
        for i, g in enumerate(genomes):
            if g["id"] == genome_id:
                fit = fitness[i] if i < len(fitness) else 0
                return {"genome": g, "fitness_roi_pct": fit, "generation": generation}, g
        print(f"Genome {genome_id} not found in generation {generation}.")
        return None

    # Default: best in this generation
    if fitness:
        best_idx = max(range(len(fitness)), key=lambda i: fitness[i])
        g = genomes[best_idx]
        return {"genome": g, "fitness_roi_pct": fitness[best_idx], "generation": generation}, g

    return {"genome": genomes[0], "fitness_roi_pct": 0, "generation": generation}, genomes[0]


def export_genome(entry: dict, genome_dict: dict):
    """Export a genome as a standalone real trading bot."""
    genome = Genome.from_dict(genome_dict)

    # We need categories to decode -- use a placeholder list.
    # The real bot will discover categories at runtime.
    # For the export, we show decoded params with a representative category list.
    placeholder_cats = entry.get("params", {}).get("categories", ["unknown"])
    params = decode_genome(genome, placeholder_cats)

    genome_id = genome.id
    output_dir = Path("data/evolution/exports")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save the genome JSON
    genome_json_path = output_dir / f"genome_{genome_id}.json"
    with open(genome_json_path, "w") as f:
        json.dump({
            "genome": genome.to_dict(),
            "decoded_params": {k: v for k, v in params.items() if k != "categories"},
            "categories": params["categories"],
            "source": entry,
        }, f, indent=2, default=str)

    # Generate the standalone bot
    bot_path = output_dir / f"bot_{genome_id}.py"
    bot_code = _generate_bot_code(genome, params, entry)
    with open(bot_path, "w") as f:
        f.write(bot_code)

    print(f"\nExported genome {genome_id}:")
    print(f"  Genome JSON: {genome_json_path}")
    print(f"  Trading bot: {bot_path}")
    print(f"\n  Decoded strategy:")
    print(f"    Signal type:      {params['signal_type']}")
    print(f"    Categories:       {params['categories']}")
    print(f"    Bankroll frac:    {params['bankroll_fraction']:.3f}")
    print(f"    Max concurrent:   {params['max_concurrent']}")
    print(f"    Max trades/day:   {params['max_trades_per_day']}")
    print(f"    Price range:      ${params['min_price']:.2f} - ${params['max_price']:.2f}")
    print(f"    Daily loss limit: {params['daily_loss_limit_pct']:.1%}")
    print(f"\n  To paper trade (dry run):")
    print(f"    DRY_RUN=true python {bot_path}")
    print(f"\n  To trade for real (CAREFUL):")
    print(f"    DRY_RUN=false python {bot_path}")


def _generate_bot_code(genome: Genome, params: dict, entry: dict) -> str:
    """Generate a standalone trading bot Python file from a genome."""
    # Serialize the gene values as hardcoded constants
    gene_lines = []
    for name in Genome.gene_names():
        val = getattr(genome, name)
        gene_lines.append(f"    {name}={val!r},")

    genes_str = "\n".join(gene_lines)

    roi = entry.get("fitness_roi_pct", 0)
    gen = entry.get("generation", "?")
    signal = params["signal_type"]

    return f'''#!/usr/bin/env python3
"""
Auto-generated trading bot from genetic evolution.

Genome: {genome.id}
Generation: {gen}
Training ROI: {roi:.1f}%
Signal type: {signal}

Usage:
    DRY_RUN=true python {f"bot_{genome.id}.py"}   # Paper trade
    DRY_RUN=false python {f"bot_{genome.id}.py"}  # Real trading (CAREFUL)
"""

import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kalshi_client import KalshiClient
from genetic.genome import Genome, decode_genome
from genetic.feed import MarketDataFeed
from genetic.engine import PaperTradingEngine
from genetic.bot import GeneticBot
from genetic.config import TICK_INTERVAL_SECONDS

# --- Hardcoded genome from evolution ---
GENOME = Genome(
    id="{genome.id}",
    generation={genome.generation},
{genes_str}
)

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
BANKROLL = float(os.getenv("BANKROLL_USD", "100"))


def main():
    mode = "PAPER TRADE" if DRY_RUN else "REAL TRADING"
    print(f"=== Genome {{GENOME.id}} | {{mode}} | ${{BANKROLL}} bankroll ===")

    client = KalshiClient()
    feed = MarketDataFeed(client, poll_interval=TICK_INTERVAL_SECONDS)
    feed.start()

    print("Waiting for market data...")
    wait_start = time.time()
    while not feed.get_open_markets() and (time.time() - wait_start) < 120:
        time.sleep(2)

    categories = feed.get_categories()
    print(f"Ready: {{len(feed.get_open_markets())}} markets, {{len(categories)}} categories")

    engine = PaperTradingEngine(feed)
    params = decode_genome(GENOME, categories)
    print(f"Strategy: {{params['signal_type']}}")
    print(f"Categories: {{params['categories']}}")
    print(f"Price range: ${{params['min_price']:.2f}} - ${{params['max_price']:.2f}}")
    print()

    if DRY_RUN:
        # Paper trading mode - simulate locally
        bot = GeneticBot(GENOME, feed, engine, categories, bankroll=BANKROLL)
        print("Paper trading started (Ctrl+C to stop)...")
        tick = 0
        try:
            while True:
                engine.settle_markets()
                bot.tick()
                tick += 1
                if tick % 60 == 0:
                    acct = bot.account
                    print(
                        f"[tick {{tick}}] Trades: {{acct.total_trades}} | "
                        f"Open: {{acct.n_open}} | Settled: {{acct.n_settled}} | "
                        f"PnL: ${{acct.realized_pnl:.2f}} | "
                        f"ROI: {{acct.roi_pct:.1f}}% | "
                        f"Win: {{acct.win_rate * 100:.0f}}%"
                    )
                time.sleep(TICK_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            acct = bot.account
            print(f"\\nFinal: {{acct.total_trades}} trades, "
                  f"${{acct.realized_pnl:.2f}} PnL, {{acct.roi_pct:.1f}}% ROI")
    else:
        # Real trading mode - place actual orders via Kalshi API
        print("REAL TRADING MODE - placing actual orders!")
        print("Press Ctrl+C to stop.\\n")
        _run_real(client, feed, params)

    feed.stop()


def _run_real(client: KalshiClient, feed: MarketDataFeed, params: dict):
    """Place real orders based on the genome's strategy."""
    import statistics
    from datetime import datetime, timezone

    traded_tickers: set[str] = set()
    trades_today = 0
    daily_pnl = 0.0
    last_date = ""

    try:
        while True:
            now = datetime.now(timezone.utc)
            today = now.strftime("%Y-%m-%d")
            if today != last_date:
                trades_today = 0
                daily_pnl = 0.0
                last_date = today

            if trades_today >= params["max_trades_per_day"]:
                time.sleep(TICK_INTERVAL_SECONDS)
                continue

            markets = feed.get_open_markets()
            for ticker, snap in markets.items():
                if ticker in traded_tickers:
                    continue
                if trades_today >= params["max_trades_per_day"]:
                    break

                # Market filter
                if snap.category not in params["categories"]:
                    continue
                if snap.volume_24h < params["min_volume_24h"]:
                    continue

                # Price filter
                yes_ok = params["min_price"] <= snap.yes_ask <= params["max_price"]
                no_ok = params["min_price"] <= snap.no_ask <= params["max_price"]
                if not yes_ok and not no_ok:
                    continue

                # Time to expiry
                if snap.close_time:
                    tte_hrs = (snap.close_time - now).total_seconds() / 3600
                    if tte_hrs < params["min_time_to_expiry_hrs"]:
                        continue
                    if tte_hrs > params["max_time_to_expiry_hrs"]:
                        continue

                # Signal
                signal = _generate_signal(params, snap, feed)
                if not signal:
                    continue

                side, _conf = signal

                # Position sizing
                stake = BANKROLL * params["bankroll_fraction"]
                price = snap.yes_ask if side == "yes" else snap.no_ask
                if price <= 0 or price >= 1.0:
                    continue
                contracts = int(stake / price)
                if contracts < 1:
                    continue

                price_cents = int(price * 100)
                print(f"ORDER: {{side.upper()}} {{contracts}}x {{ticker}} @ ${{price:.2f}}")
                try:
                    resp = client.place_order(ticker, side, contracts, price_cents)
                    order_id = resp.get("order", {{}}).get("order_id", "?")
                    print(f"  -> Placed: {{order_id}}")
                    traded_tickers.add(ticker)
                    trades_today += 1
                except Exception as e:
                    print(f"  -> FAILED: {{e}}")

            time.sleep(TICK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print(f"\\nStopped. Placed {{trades_today}} orders today.")


def _generate_signal(params, snap, feed):
    """Generate signal based on the genome's strategy type."""
    import statistics as stats_mod

    st = params["signal_type"]

    if st == "price_level":
        lo, hi = params["price_threshold_low"], params["price_threshold_high"]
        if lo <= snap.yes_ask <= hi:
            return ("yes", snap.yes_ask)
        if lo <= snap.no_ask <= hi:
            return ("no", snap.no_ask)

    elif st == "momentum":
        history = feed.get_history(snap.ticker)
        lookback = params["momentum_lookback_ticks"]
        if len(history) >= lookback + 1:
            old = history[-(lookback + 1)][1]
            cur = history[-1][1]
            if old > 0:
                pct = (cur - old) / old
                trigger = params["momentum_trigger_pct"]
                if pct > trigger:
                    return ("yes", abs(pct))
                elif pct < -trigger:
                    return ("no", abs(pct))

    elif st == "mean_reversion":
        history = feed.get_history(snap.ticker)
        if len(history) >= 10:
            prices = [h[1] for h in history]
            mean = stats_mod.mean(prices)
            stdev = stats_mod.stdev(prices) if len(prices) > 1 else 0.001
            if stdev >= 0.001:
                z = (prices[-1] - mean) / stdev
                threshold = params["mean_rev_zscore"]
                if z > threshold:
                    return ("no", abs(z))
                elif z < -threshold:
                    return ("yes", abs(z))

    elif st == "value":
        edge_min = params["value_edge_min"]
        yes_edge = 0.50 - snap.yes_ask
        no_edge = 0.50 - snap.no_ask
        if yes_edge > edge_min:
            return ("yes", yes_edge)
        if no_edge > edge_min:
            return ("no", no_edge)

    elif st == "contrarian":
        threshold = params["contrarian_threshold"]
        if snap.yes_ask > threshold:
            return ("no", snap.yes_ask - threshold)
        if snap.no_ask > threshold:
            return ("yes", snap.no_ask - threshold)

    return None


if __name__ == "__main__":
    main()
'''


def main():
    parser = argparse.ArgumentParser(description="Export trained genomes into real trading bots")
    parser.add_argument("--show", action="store_true", help="Show the hall of fame leaderboard")
    parser.add_argument("--generation", "-g", type=int, help="Export from a specific generation")
    parser.add_argument("--genome-id", "-id", type=str, help="Export a specific genome by ID")
    args = parser.parse_args()

    if args.show:
        show_hall_of_fame()
        return

    # Find the genome to export
    if args.generation is not None:
        result = get_genome_from_generation(args.generation, args.genome_id)
    else:
        result = get_genome_from_hof(args.genome_id)

    if not result:
        print("Genome not found. Use --show to see available genomes.")
        sys.exit(1)

    entry, genome_dict = result
    export_genome(entry, genome_dict)


if __name__ == "__main__":
    main()
