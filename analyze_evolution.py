#!/usr/bin/env python3
"""
Analyze evolution progress across all generations.

Usage:
    python analyze_evolution.py
"""

import json
from pathlib import Path

STATE_DIR = Path("data/evolution")


def main():
    gen_files = sorted(STATE_DIR.glob("gen_*.json"))

    if not gen_files:
        print("No generation data found. Run the evolution first: python -m genetic")
        return

    print(f"\n{'=' * 70}")
    print(f"  EVOLUTION PROGRESS ({len(gen_files)} generations)")
    print(f"{'=' * 70}")
    print(
        f"{'Gen':<5} {'Best':>8} {'Median':>8} {'Mean':>8} {'Worst':>8} "
        f"{'Trades':>8} {'WinRate':>8} {'Active':>7}"
    )
    print("-" * 70)

    best_ever_roi = -999
    best_ever_gen = 0

    for gf in gen_files:
        with open(gf) as f:
            state = json.load(f)

        s = state.get("stats", {})
        gen = state["generation"]

        best = s.get("best_roi", 0)
        if best > best_ever_roi:
            best_ever_roi = best
            best_ever_gen = gen

        print(
            f"{gen:<5} "
            f"{s.get('best_roi', 0):>7.1f}% "
            f"{s.get('median_roi', 0):>7.1f}% "
            f"{s.get('mean_roi', 0):>7.1f}% "
            f"{s.get('worst_roi', 0):>7.1f}% "
            f"{s.get('mean_trades', 0):>8.1f} "
            f"{s.get('mean_win_rate', 0):>7.1f}% "
            f"{s.get('active_bots', 0):>4}/{100}"
        )

    print(f"\nBest ever: {best_ever_roi:.1f}% ROI in generation {best_ever_gen}")

    # Show hall of fame if available
    hof_path = STATE_DIR / "hall_of_fame.json"
    if hof_path.exists():
        with open(hof_path) as f:
            hof = json.load(f)

        entries = hof.get("entries", [])
        if entries:
            print(f"\n{'=' * 70}")
            print(f"  TOP 10 ALL-TIME")
            print(f"{'=' * 70}")
            print(
                f"{'Rank':<5} {'Genome':<10} {'Gen':<5} {'ROI%':>8} "
                f"{'Trades':>7} {'WinRate':>8} {'Signal':>15}"
            )
            print("-" * 70)
            for i, e in enumerate(entries[:10]):
                print(
                    f"{i + 1:<5} {e['genome']['id']:<10} "
                    f"{e['generation']:<5} "
                    f"{e['fitness_roi_pct']:>7.1f}% "
                    f"{e.get('settled_trades', 0):>7} "
                    f"{e.get('win_rate', 0) * 100:>7.1f}% "
                    f"{e.get('signal_type', '?'):>15}"
                )

    print(f"\nTo export the best bot: python -m genetic.export")


if __name__ == "__main__":
    main()
