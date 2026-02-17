#!/usr/bin/env python3
"""Analyze mock trades data to calculate strategy performance metrics."""

import csv
from collections import defaultdict
from pathlib import Path


def load_trades(filepath: str) -> list[dict]:
    """Load trades from CSV file."""
    trades = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)
    return trades


def analyze_strategies(trades: list[dict]) -> dict:
    """Calculate performance metrics for each strategy."""
    stats = defaultdict(lambda: {
        "wins": 0,
        "losses": 0,
        "total_profit": 0.0,
        "total_staked": 0.0,
        "trades": [],
    })

    for trade in trades:
        strategy = trade["strategy"]
        outcome = trade["outcome"].strip()

        # Skip trades without outcomes (pending)
        if not outcome:
            continue

        profit = float(trade["profit_usd"]) if trade["profit_usd"] else 0.0
        stake = float(trade["stake_usd"]) if trade["stake_usd"] else 0.0

        stats[strategy]["total_profit"] += profit
        stats[strategy]["total_staked"] += stake
        stats[strategy]["trades"].append(trade)

        if outcome == "WIN":
            stats[strategy]["wins"] += 1
        elif outcome == "LOSS":
            stats[strategy]["losses"] += 1

    # Calculate derived metrics
    for strategy, data in stats.items():
        total = data["wins"] + data["losses"]
        data["total_trades"] = total
        data["win_rate"] = (data["wins"] / total * 100) if total > 0 else 0
        data["roi"] = (data["total_profit"] / data["total_staked"] * 100) if data["total_staked"] > 0 else 0

    return dict(stats)


def print_results(stats: dict) -> None:
    """Print analysis results in a formatted table."""
    print("\n" + "=" * 70)
    print("STRATEGY PERFORMANCE ANALYSIS")
    print("=" * 70)

    # Sort by win rate descending
    sorted_strategies = sorted(stats.items(), key=lambda x: x[1]["win_rate"], reverse=True)

    # Header
    print(f"\n{'Strategy':<12} {'Wins':>6} {'Losses':>7} {'Total':>6} {'Win Rate':>10} {'Profit':>12} {'ROI':>10}")
    print("-" * 70)

    for strategy, data in sorted_strategies:
        print(
            f"{strategy:<12} "
            f"{data['wins']:>6} "
            f"{data['losses']:>7} "
            f"{data['total_trades']:>6} "
            f"{data['win_rate']:>9.1f}% "
            f"${data['total_profit']:>10.2f} "
            f"{data['roi']:>9.1f}%"
        )

    print("-" * 70)

    # Summary
    total_profit = sum(d["total_profit"] for d in stats.values())
    total_staked = sum(d["total_staked"] for d in stats.values())
    total_trades = sum(d["total_trades"] for d in stats.values())
    total_wins = sum(d["wins"] for d in stats.values())

    print(f"\n{'TOTALS':<12} {total_wins:>6} {total_trades - total_wins:>7} {total_trades:>6} "
          f"{(total_wins/total_trades*100) if total_trades else 0:>9.1f}% "
          f"${total_profit:>10.2f} "
          f"{(total_profit/total_staked*100) if total_staked else 0:>9.1f}%")

    # Best strategy
    best = sorted_strategies[0]
    print(f"\nBest Strategy by Win Rate: {best[0]} ({best[1]['win_rate']:.1f}%)")

    # Best by profit
    best_profit = max(stats.items(), key=lambda x: x[1]["total_profit"])
    print(f"Best Strategy by Profit: {best_profit[0]} (${best_profit[1]['total_profit']:.2f})")

    # Best by ROI
    best_roi = max(stats.items(), key=lambda x: x[1]["roi"])
    print(f"Best Strategy by ROI: {best_roi[0]} ({best_roi[1]['roi']:.1f}%)")

    print("\n" + "=" * 70)


def print_detailed_breakdown(stats: dict) -> None:
    """Print detailed breakdown for each strategy."""
    print("\nDETAILED BREAKDOWN")
    print("-" * 70)

    for strategy, data in sorted(stats.items()):
        print(f"\n{strategy}:")
        print(f"  Total Trades: {data['total_trades']}")
        print(f"  Wins: {data['wins']}, Losses: {data['losses']}")
        print(f"  Win Rate: {data['win_rate']:.2f}%")
        print(f"  Total Staked: ${data['total_staked']:.2f}")
        print(f"  Total Profit: ${data['total_profit']:.2f}")
        print(f"  ROI: {data['roi']:.2f}%")

        if data['total_trades'] > 0:
            avg_profit_per_trade = data['total_profit'] / data['total_trades']
            print(f"  Avg Profit/Trade: ${avg_profit_per_trade:.2f}")


def main():
    data_path = Path(__file__).parent / "data" / "mock_trades.csv"

    if not data_path.exists():
        print(f"Error: Could not find {data_path}")
        return 1

    trades = load_trades(data_path)
    print(f"Loaded {len(trades)} trades from {data_path}")

    # Count pending trades
    pending = sum(1 for t in trades if not t["outcome"].strip())
    if pending:
        print(f"Note: {pending} trades are pending (no outcome yet)")

    stats = analyze_strategies(trades)
    print_results(stats)
    print_detailed_breakdown(stats)

    return 0


if __name__ == "__main__":
    exit(main())
