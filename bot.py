import csv
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES_TICKER = "KXBTC15M"
POLL_SECONDS = 5
STAKE_USD = 5.0
TRADES_CSV = Path("data/mock_trades.csv")

# Momentum strategy: track last 60 seconds of BTC prices
MOMENTUM_WINDOW_SECONDS = 60


def get_btc_price():
    """Get current BTC price from Coinbase."""
    resp = requests.get(
        "https://api.coinbase.com/v2/prices/BTC-USD/spot",
        timeout=10
    )
    resp.raise_for_status()
    return float(resp.json()["data"]["amount"])


def get_open_market():
    """Get the next expiring open KXBTC15M market."""
    params = {"series_ticker": SERIES_TICKER, "status": "open", "limit": 50}
    resp = requests.get(f"{API_BASE}/markets", params=params, timeout=20)
    resp.raise_for_status()

    now = datetime.now(timezone.utc)
    candidates = []

    for market in resp.json().get("markets", []):
        close_time = market.get("close_time")
        if not close_time:
            continue

        exp = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        if exp > now:
            candidates.append((exp, market))

    if not candidates:
        return None

    _, best = min(candidates, key=lambda x: x[0])
    return best


def get_market(ticker):
    """Get a specific market by ticker."""
    resp = requests.get(f"{API_BASE}/markets/{ticker}", timeout=20)
    resp.raise_for_status()
    return resp.json().get("market", {})


def get_settled_side(market):
    """Return 'yes' or 'no' if market is settled, else None."""
    result = market.get("result")
    if result in ("yes", "no"):
        return result
    return None


def load_trades():
    """Load all trades from CSV."""
    if not TRADES_CSV.exists():
        return []
    with TRADES_CSV.open() as f:
        return list(csv.DictReader(f))


def save_trades(trades):
    """Save all trades to CSV."""
    if not trades:
        return
    TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "time", "strategy", "previous_ticker", "previous_result", "buy_ticker", "buy_side",
        "stake_usd", "price_usd", "contracts", "outcome", "payout_usd", "profit_usd"
    ]
    with TRADES_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trades)


def calc_stats(trades, strategy=None):
    """Calculate stats from trades, optionally filtered by strategy."""
    total_staked = 0.0
    total_profit = 0.0
    wins = 0
    losses = 0
    pending = 0

    for t in trades:
        if strategy and t.get("strategy") != strategy:
            continue
        total_staked += float(t.get("stake_usd", 0))
        profit = t.get("profit_usd", "")
        if profit != "":
            p = float(profit)
            total_profit += p
            if p > 0:
                wins += 1
            else:
                losses += 1
        else:
            pending += 1

    return {
        "total_staked": total_staked,
        "total_profit": total_profit,
        "wins": wins,
        "losses": losses,
        "pending": pending,
    }


def main():
    load_dotenv()

    print(f"Watching KXBTC15M markets with 3 strategies:")
    print(f"  1. PREVIOUS:  Buy same side as previous market result")
    print(f"  2. MOMENTUM:  Buy based on BTC price direction in last {MOMENTUM_WINDOW_SECONDS}s")
    print(f"  3. CONSENSUS: Buy only when PREVIOUS and MOMENTUM agree")
    print(f"Stake: ${STAKE_USD} per trade | Polling: {POLL_SECONDS}s | CSV: {TRADES_CSV}")

    current_ticker = None
    pending_previous = None
    trades = load_trades()

    # Track which (strategy, buy_ticker) combos we've already traded
    traded_keys = {
        (t.get("strategy", ""), t.get("buy_ticker", ""))
        for t in trades if t.get("buy_ticker")
    }

    # BTC price history: deque of (timestamp, price)
    btc_prices = deque(maxlen=100)

    # Track signals per market for consensus
    # signals[ticker] = {"PREVIOUS": "yes"/"no"/None, "MOMENTUM": "yes"/"no"/None}
    signals = {}

    # Print initial stats
    prev_stats = calc_stats(trades, "PREVIOUS")
    mom_stats = calc_stats(trades, "MOMENTUM")
    cons_stats = calc_stats(trades, "CONSENSUS")
    print(f"Loaded {len(trades)} trades")
    print(f"  PREVIOUS:  ${prev_stats['total_profit']:+.2f} ({prev_stats['wins']}W/{prev_stats['losses']}L)")
    print(f"  MOMENTUM:  ${mom_stats['total_profit']:+.2f} ({mom_stats['wins']}W/{mom_stats['losses']}L)")
    print(f"  CONSENSUS: ${cons_stats['total_profit']:+.2f} ({cons_stats['wins']}W/{cons_stats['losses']}L)")

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Get BTC price
            try:
                btc_price = get_btc_price()
                btc_prices.append((now, btc_price))
            except Exception as e:
                btc_price = None
                print(f"  [BTC price error: {e}]")

            market = get_open_market()

            if not market:
                print(f"[{now.isoformat()}] No open KXBTC15M market found")
                time.sleep(POLL_SECONDS)
                continue

            ticker = market["ticker"]
            yes_ask = market.get("yes_ask", 0) / 100
            no_ask = market.get("no_ask", 0) / 100

            close_time_str = market.get("close_time", "")
            close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00")) if close_time_str else None
            time_to_close = (close_time - now).total_seconds() if close_time else None

            # Initialize signals for this ticker
            if ticker not in signals:
                signals[ticker] = {"PREVIOUS": None, "MOMENTUM": None}

            # Detect market change
            if current_ticker is None:
                current_ticker = ticker
            elif ticker != current_ticker:
                pending_previous = current_ticker
                current_ticker = ticker

            # Check pending trades for settlement
            updated = False
            for trade in trades:
                if trade.get("outcome"):
                    continue

                buy_ticker = trade.get("buy_ticker")
                if not buy_ticker:
                    continue

                try:
                    m = get_market(buy_ticker)
                    result = get_settled_side(m)
                    if result:
                        buy_side = trade.get("buy_side")
                        contracts = float(trade.get("contracts", 0))
                        stake = float(trade.get("stake_usd", 0))

                        won = (result == buy_side)
                        payout = contracts if won else 0
                        profit = payout - stake

                        trade["outcome"] = "WIN" if won else "LOSS"
                        trade["payout_usd"] = round(payout, 4)
                        trade["profit_usd"] = round(profit, 4)
                        updated = True

                        strat = trade.get("strategy", "?")
                        print(f"  ** [{strat}] SETTLED {buy_ticker}: {trade['outcome']} ${profit:+.2f}")
                except Exception:
                    pass

            if updated:
                save_trades(trades)

            # Print status
            prev_stats = calc_stats(trades, "PREVIOUS")
            mom_stats = calc_stats(trades, "MOMENTUM")
            cons_stats = calc_stats(trades, "CONSENSUS")
            btc_str = f"BTC=${btc_price:,.0f}" if btc_price else "BTC=?"
            time_str = f"{time_to_close:.0f}s" if time_to_close else "?"
            print(
                f"[{now.strftime('%H:%M:%S')}] {ticker} ({time_str}) | yes=${yes_ask:.2f} no=${no_ask:.2f} | {btc_str} | "
                f"P:${prev_stats['total_profit']:+.2f} M:${mom_stats['total_profit']:+.2f} C:${cons_stats['total_profit']:+.2f}"
            )

            # === STRATEGY 1: PREVIOUS RESULT ===
            if pending_previous and ("PREVIOUS", ticker) not in traded_keys:
                prev_market = get_market(pending_previous)
                settled = get_settled_side(prev_market)

                if settled:
                    # Record signal
                    signals[ticker]["PREVIOUS"] = settled

                    price = yes_ask if settled == "yes" else no_ask
                    contracts = STAKE_USD / price if price > 0 else 0

                    trade = {
                        "time": now.isoformat(),
                        "strategy": "PREVIOUS",
                        "previous_ticker": pending_previous,
                        "previous_result": settled,
                        "buy_ticker": ticker,
                        "buy_side": settled,
                        "stake_usd": STAKE_USD,
                        "price_usd": round(price, 4),
                        "contracts": round(contracts, 4),
                        "outcome": "",
                        "payout_usd": "",
                        "profit_usd": "",
                    }
                    trades.append(trade)
                    save_trades(trades)
                    traded_keys.add(("PREVIOUS", ticker))

                    print(f"  -> [PREVIOUS] BUY {settled} ${STAKE_USD} @ ${price:.4f}")
                else:
                    print(f"  -> [PREVIOUS] Waiting for {pending_previous} to settle...")

            # === STRATEGY 2: MOMENTUM ===
            # Buy in new market when previous settles, based on BTC price direction
            if (
                pending_previous
                and ("MOMENTUM", ticker) not in traded_keys
                and len(btc_prices) >= 2
            ):
                # Get price from ~60 seconds ago
                cutoff = now - timedelta(seconds=MOMENTUM_WINDOW_SECONDS)
                old_prices = [(t, p) for t, p in btc_prices if t <= cutoff]

                if old_prices:
                    _, old_price = old_prices[-1]
                    _, current_price = btc_prices[-1]

                    if current_price > old_price:
                        side = "yes"  # Price rising, bet UP
                    else:
                        side = "no"   # Price falling, bet DOWN

                    # Record signal
                    signals[ticker]["MOMENTUM"] = side

                    price = yes_ask if side == "yes" else no_ask
                    contracts = STAKE_USD / price if price > 0 else 0
                    pct_change = ((current_price - old_price) / old_price) * 100

                    trade = {
                        "time": now.isoformat(),
                        "strategy": "MOMENTUM",
                        "previous_ticker": pending_previous,
                        "previous_result": f"BTC {pct_change:+.3f}%",
                        "buy_ticker": ticker,
                        "buy_side": side,
                        "stake_usd": STAKE_USD,
                        "price_usd": round(price, 4),
                        "contracts": round(contracts, 4),
                        "outcome": "",
                        "payout_usd": "",
                        "profit_usd": "",
                    }
                    trades.append(trade)
                    save_trades(trades)
                    traded_keys.add(("MOMENTUM", ticker))

                    direction = "UP" if side == "yes" else "DOWN"
                    print(f"  -> [MOMENTUM] BTC {pct_change:+.3f}% -> BUY {side} ({direction}) ${STAKE_USD} @ ${price:.4f}")

            # === STRATEGY 3: CONSENSUS ===
            # Only bet if both PREVIOUS and MOMENTUM agree, and we haven't traded yet
            if ("CONSENSUS", ticker) not in traded_keys:
                prev_signal = signals[ticker].get("PREVIOUS")
                mom_signal = signals[ticker].get("MOMENTUM")

                if prev_signal and mom_signal and prev_signal == mom_signal:
                    side = prev_signal  # Both agree

                    price = yes_ask if side == "yes" else no_ask
                    contracts = STAKE_USD / price if price > 0 else 0

                    trade = {
                        "time": now.isoformat(),
                        "strategy": "CONSENSUS",
                        "previous_ticker": "",
                        "previous_result": f"PREV={prev_signal} MOM={mom_signal}",
                        "buy_ticker": ticker,
                        "buy_side": side,
                        "stake_usd": STAKE_USD,
                        "price_usd": round(price, 4),
                        "contracts": round(contracts, 4),
                        "outcome": "",
                        "payout_usd": "",
                        "profit_usd": "",
                    }
                    trades.append(trade)
                    save_trades(trades)
                    traded_keys.add(("CONSENSUS", ticker))

                    direction = "UP" if side == "yes" else "DOWN"
                    print(f"  -> [CONSENSUS] Both agree {side} ({direction}) -> BUY ${STAKE_USD} @ ${price:.4f}")
                elif prev_signal and mom_signal and prev_signal != mom_signal:
                    # They disagree, mark as checked so we don't keep printing
                    traded_keys.add(("CONSENSUS", ticker))
                    print(f"  -> [CONSENSUS] No bet - signals disagree (PREV={prev_signal}, MOM={mom_signal})")

            # Clear pending_previous after both PREVIOUS and MOMENTUM have traded
            if pending_previous and ("PREVIOUS", ticker) in traded_keys and ("MOMENTUM", ticker) in traded_keys:
                pending_previous = None

            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            print("\nStopped.")
            prev_stats = calc_stats(trades, "PREVIOUS")
            mom_stats = calc_stats(trades, "MOMENTUM")
            cons_stats = calc_stats(trades, "CONSENSUS")
            total_stats = calc_stats(trades)
            print(f"=== FINAL STATS ===")
            print(f"PREVIOUS:  ${prev_stats['total_profit']:+.2f} | {prev_stats['wins']}W/{prev_stats['losses']}L | {prev_stats['pending']} pending")
            print(f"MOMENTUM:  ${mom_stats['total_profit']:+.2f} | {mom_stats['wins']}W/{mom_stats['losses']}L | {mom_stats['pending']} pending")
            print(f"CONSENSUS: ${cons_stats['total_profit']:+.2f} | {cons_stats['wins']}W/{cons_stats['losses']}L | {cons_stats['pending']} pending")
            print(f"TOTAL:     ${total_stats['total_profit']:+.2f} | {total_stats['wins']}W/{total_stats['losses']}L")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
