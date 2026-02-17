import csv
import os
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
MOMENTUM_15_WINDOW_SECONDS = 15 * 60
DEAL_MAX_PRICE = 0.45
ARBITRAGE_MAX_BET_USD = 10.0

# Consensus risk and execution controls
INITIAL_BANKROLL_USD = float(os.getenv("INITIAL_BANKROLL_USD", "500"))
CONSENSUS_RISK_PCT = float(os.getenv("CONSENSUS_RISK_PCT", "0.01"))
CONSENSUS_MAX_RISK_PCT = float(os.getenv("CONSENSUS_MAX_RISK_PCT", "0.02"))
CONSENSUS_MAX_PRICE = float(os.getenv("CONSENSUS_MAX_PRICE", "0.55"))
CONSENSUS_FEE_PCT = float(os.getenv("CONSENSUS_FEE_PCT", "0.0"))
CONSENSUS_ROLLING_WINDOW = int(os.getenv("CONSENSUS_ROLLING_WINDOW", "30"))
CONSENSUS_DAILY_LOSS_CAP_R = float(os.getenv("CONSENSUS_DAILY_LOSS_CAP_R", "3"))
CONSENSUS_WEEKLY_LOSS_CAP_R = float(os.getenv("CONSENSUS_WEEKLY_LOSS_CAP_R", "8"))


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
        "stake_usd", "price_usd", "contracts", "fee_usd", "gross_profit_usd",
        "outcome", "payout_usd", "profit_usd"
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


def parse_trade_time(value):
    """Parse ISO trade timestamp."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def settled_consensus(trades):
    """Return settled consensus trades in insertion order."""
    return [
        t for t in trades
        if t.get("strategy") in ("CONSENSUS", "CONSENSUS_2") and t.get("outcome")
    ]


def consensus_bankroll(trades):
    """Current consensus bankroll from realized P&L."""
    realized = sum(
        float(t.get("profit_usd", 0))
        for t in settled_consensus(trades)
    )
    return INITIAL_BANKROLL_USD + realized


def consensus_period_pnl(trades, now):
    """Return today's and this ISO week's realized consensus P&L."""
    daily = 0.0
    weekly = 0.0
    now_date = now.date()
    now_year, now_week, _ = now.isocalendar()

    for t in settled_consensus(trades):
        ts = parse_trade_time(t.get("time", ""))
        if not ts:
            continue
        profit = float(t.get("profit_usd", 0))
        if ts.date() == now_date:
            daily += profit
        year, week, _ = ts.isocalendar()
        if year == now_year and week == now_week:
            weekly += profit

    return daily, weekly


def rolling_consensus_metrics(trades):
    """Return rolling consensus performance and break-even win rate."""
    settled = settled_consensus(trades)
    if not settled:
        return {
            "sample_size": 0,
            "win_rate": 0.0,
            "break_even_win_rate": 1.0,
        }

    window = settled[-CONSENSUS_ROLLING_WINDOW:]
    profits = [float(t.get("profit_usd", 0)) for t in window]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]
    sample_size = len(window)
    win_rate = len(wins) / sample_size if sample_size else 0.0

    if wins and losses:
        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))
        break_even = avg_loss / (avg_win + avg_loss) if (avg_win + avg_loss) else 1.0
    elif wins and not losses:
        break_even = 0.0
    else:
        break_even = 1.0

    return {
        "sample_size": sample_size,
        "win_rate": win_rate,
        "break_even_win_rate": break_even,
    }


def main():
    load_dotenv()

    print(f"Watching KXBTC15M markets with 7 strategies:")
    print(f"  1. PREVIOUS:  Buy same side as previous market result")
    print(f"  2. MOMENTUM:  Buy based on BTC price direction in last {MOMENTUM_WINDOW_SECONDS}s")
    print(f"  3. CONSENSUS: Buy only when PREVIOUS and MOMENTUM agree")
    print(f"  4. MOMENTUM_15: Buy based on BTC direction over {MOMENTUM_15_WINDOW_SECONDS}s")
    print(f"  5. PREVIOUS_2: Wait for PREVIOUS side at <= ${DEAL_MAX_PRICE:.2f}")
    print(f"  6. CONSENSUS_2: Wait for CONSENSUS side at <= ${DEAL_MAX_PRICE:.2f}")
    print(f"  7. ARBITRAGE: Buy immediately, then hedge opposite side if profitable (< ${ARBITRAGE_MAX_BET_USD:.2f})")
    print(f"Stake: ${STAKE_USD} per trade | Polling: {POLL_SECONDS}s | CSV: {TRADES_CSV}")
    print(
        f"CONSENSUS controls: price<=${CONSENSUS_MAX_PRICE:.2f}, "
        f"risk={CONSENSUS_RISK_PCT*100:.1f}% max={CONSENSUS_MAX_RISK_PCT*100:.1f}%"
    )
    print(
        f"Loss caps: daily={CONSENSUS_DAILY_LOSS_CAP_R:.1f}R weekly={CONSENSUS_WEEKLY_LOSS_CAP_R:.1f}R | "
        f"rolling window={CONSENSUS_ROLLING_WINDOW} | fee={CONSENSUS_FEE_PCT*100:.2f}%"
    )

    current_ticker = None
    pending_previous = None
    trades = load_trades()

    # Track which (strategy, buy_ticker) combos we've already traded
    traded_keys = {
        (t.get("strategy", ""), t.get("buy_ticker", ""))
        for t in trades if t.get("buy_ticker")
    }

    # BTC price history: enough for the longest momentum window
    btc_history_len = max(100, int(MOMENTUM_15_WINDOW_SECONDS / max(POLL_SECONDS, 1)) + 20)
    btc_prices = deque(maxlen=btc_history_len)

    # Track signals per market for consensus
    # signals[ticker] = {
    #   "PREVIOUS": "yes"/"no"/None,
    #   "MOMENTUM": "yes"/"no"/None,
    #   "MOMENTUM_15": "yes"/"no"/None,
    # }
    signals = {}
    arb_positions = {}

    # Print initial stats
    prev_stats = calc_stats(trades, "PREVIOUS")
    mom_stats = calc_stats(trades, "MOMENTUM")
    cons_stats = calc_stats(trades, "CONSENSUS")
    mom15_stats = calc_stats(trades, "MOMENTUM_15")
    prev2_stats = calc_stats(trades, "PREVIOUS_2")
    cons2_stats = calc_stats(trades, "CONSENSUS_2")
    arb_stats = calc_stats(trades, "ARBITRAGE")
    arb_hedge_stats = calc_stats(trades, "ARBITRAGE_HEDGE")
    print(f"Loaded {len(trades)} trades")
    print(f"  PREVIOUS:  ${prev_stats['total_profit']:+.2f} ({prev_stats['wins']}W/{prev_stats['losses']}L)")
    print(f"  MOMENTUM:  ${mom_stats['total_profit']:+.2f} ({mom_stats['wins']}W/{mom_stats['losses']}L)")
    print(f"  CONSENSUS: ${cons_stats['total_profit']:+.2f} ({cons_stats['wins']}W/{cons_stats['losses']}L)")
    print(f"  MOMENTUM_15: ${mom15_stats['total_profit']:+.2f} ({mom15_stats['wins']}W/{mom15_stats['losses']}L)")
    print(f"  PREVIOUS_2:  ${prev2_stats['total_profit']:+.2f} ({prev2_stats['wins']}W/{prev2_stats['losses']}L)")
    print(f"  CONSENSUS_2: ${cons2_stats['total_profit']:+.2f} ({cons2_stats['wins']}W/{cons2_stats['losses']}L)")
    print(f"  ARBITRAGE:   ${(arb_stats['total_profit'] + arb_hedge_stats['total_profit']):+.2f} "
          f"({arb_stats['wins'] + arb_hedge_stats['wins']}W/{arb_stats['losses'] + arb_hedge_stats['losses']}L)")

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
                signals[ticker] = {"PREVIOUS": None, "MOMENTUM": None, "MOMENTUM_15": None}

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
                        gross_profit = payout - stake
                        fee = stake * CONSENSUS_FEE_PCT if trade.get("strategy") in ("CONSENSUS", "CONSENSUS_2") else 0.0
                        profit = gross_profit - fee

                        trade["outcome"] = "WIN" if won else "LOSS"
                        trade["payout_usd"] = round(payout, 4)
                        trade["gross_profit_usd"] = round(gross_profit, 4)
                        trade["fee_usd"] = round(fee, 4)
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
            mom15_stats = calc_stats(trades, "MOMENTUM_15")
            prev2_stats = calc_stats(trades, "PREVIOUS_2")
            cons2_stats = calc_stats(trades, "CONSENSUS_2")
            arb_stats = calc_stats(trades, "ARBITRAGE")
            arb_hedge_stats = calc_stats(trades, "ARBITRAGE_HEDGE")
            cons_bankroll = consensus_bankroll(trades)
            btc_str = f"BTC=${btc_price:,.0f}" if btc_price else "BTC=?"
            time_str = f"{time_to_close:.0f}s" if time_to_close else "?"
            print(
                f"[{now.strftime('%H:%M:%S')}] {ticker} ({time_str}) | yes=${yes_ask:.2f} no=${no_ask:.2f} | {btc_str} | "
                f"P:${prev_stats['total_profit']:+.2f} M:${mom_stats['total_profit']:+.2f} "
                f"C:${cons_stats['total_profit']:+.2f} M15:${mom15_stats['total_profit']:+.2f} "
                f"P2:${prev2_stats['total_profit']:+.2f} C2:${cons2_stats['total_profit']:+.2f} "
                f"A:${(arb_stats['total_profit'] + arb_hedge_stats['total_profit']):+.2f} "
                f"CB:${cons_bankroll:.2f}"
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

            # === STRATEGY 2B: MOMENTUM_15 ===
            if (
                pending_previous
                and ("MOMENTUM_15", ticker) not in traded_keys
                and len(btc_prices) >= 2
            ):
                cutoff = now - timedelta(seconds=MOMENTUM_15_WINDOW_SECONDS)
                old_prices = [(t, p) for t, p in btc_prices if t <= cutoff]

                if old_prices:
                    _, old_price = old_prices[-1]
                    _, current_price = btc_prices[-1]
                    side = "yes" if current_price > old_price else "no"

                    signals[ticker]["MOMENTUM_15"] = side

                    price = yes_ask if side == "yes" else no_ask
                    contracts = STAKE_USD / price if price > 0 else 0
                    pct_change = ((current_price - old_price) / old_price) * 100

                    trade = {
                        "time": now.isoformat(),
                        "strategy": "MOMENTUM_15",
                        "previous_ticker": pending_previous,
                        "previous_result": f"BTC15 {pct_change:+.3f}%",
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
                    traded_keys.add(("MOMENTUM_15", ticker))
                    direction = "UP" if side == "yes" else "DOWN"
                    print(f"  -> [MOMENTUM_15] BTC {pct_change:+.3f}% -> BUY {side} ({direction}) ${STAKE_USD} @ ${price:.4f}")

            # === STRATEGY 3: CONSENSUS ===
            # Only bet if both PREVIOUS and MOMENTUM agree, and we haven't traded yet
            if ("CONSENSUS", ticker) not in traded_keys:
                prev_signal = signals[ticker].get("PREVIOUS")
                mom_signal = signals[ticker].get("MOMENTUM")

                if prev_signal and mom_signal and prev_signal == mom_signal:
                    side = prev_signal  # Both agree

                    price = yes_ask if side == "yes" else no_ask
                    if price <= 0:
                        traded_keys.add(("CONSENSUS", ticker))
                        print(f"  -> [CONSENSUS] Skip - invalid price ({price})")
                        time.sleep(POLL_SECONDS)
                        continue

                    if price > CONSENSUS_MAX_PRICE:
                        traded_keys.add(("CONSENSUS", ticker))
                        print(
                            f"  -> [CONSENSUS] Skip - ask ${price:.4f} > max ${CONSENSUS_MAX_PRICE:.2f}"
                        )
                        time.sleep(POLL_SECONDS)
                        continue

                    bankroll = consensus_bankroll(trades)
                    if bankroll <= 0:
                        traded_keys.add(("CONSENSUS", ticker))
                        print("  -> [CONSENSUS] Skip - bankroll depleted")
                        time.sleep(POLL_SECONDS)
                        continue

                    r_value = max(bankroll * CONSENSUS_RISK_PCT, 0.01)
                    daily_cap = CONSENSUS_DAILY_LOSS_CAP_R * r_value
                    weekly_cap = CONSENSUS_WEEKLY_LOSS_CAP_R * r_value
                    day_pnl, week_pnl = consensus_period_pnl(trades, now)
                    if day_pnl <= -daily_cap:
                        traded_keys.add(("CONSENSUS", ticker))
                        print(
                            f"  -> [CONSENSUS] Skip - daily loss cap hit ({day_pnl:+.2f} <= -{daily_cap:.2f})"
                        )
                        time.sleep(POLL_SECONDS)
                        continue
                    if week_pnl <= -weekly_cap:
                        traded_keys.add(("CONSENSUS", ticker))
                        print(
                            f"  -> [CONSENSUS] Skip - weekly loss cap hit ({week_pnl:+.2f} <= -{weekly_cap:.2f})"
                        )
                        time.sleep(POLL_SECONDS)
                        continue

                    rolling = rolling_consensus_metrics(trades)
                    if (
                        rolling["sample_size"] >= CONSENSUS_ROLLING_WINDOW
                        and rolling["win_rate"] < rolling["break_even_win_rate"]
                    ):
                        traded_keys.add(("CONSENSUS", ticker))
                        print(
                            "  -> [CONSENSUS] Skip - rolling win rate below break-even "
                            f"({rolling['win_rate']*100:.1f}% < {rolling['break_even_win_rate']*100:.1f}%)"
                        )
                        time.sleep(POLL_SECONDS)
                        continue

                    target_stake = bankroll * CONSENSUS_RISK_PCT
                    max_stake = bankroll * CONSENSUS_MAX_RISK_PCT
                    stake = min(max(target_stake, 0.01), max_stake, bankroll)
                    contracts = int(stake / price)
                    if contracts < 1:
                        traded_keys.add(("CONSENSUS", ticker))
                        print(
                            f"  -> [CONSENSUS] Skip - stake ${stake:.2f} too small for ask ${price:.4f}"
                        )
                        time.sleep(POLL_SECONDS)
                        continue

                    max_contracts = int(max_stake / price)
                    contracts = min(contracts, max_contracts)
                    if contracts < 1:
                        traded_keys.add(("CONSENSUS", ticker))
                        print("  -> [CONSENSUS] Skip - exceeds max risk per trade")
                        time.sleep(POLL_SECONDS)
                        continue

                    stake = contracts * price

                    trade = {
                        "time": now.isoformat(),
                        "strategy": "CONSENSUS",
                        "previous_ticker": "",
                        "previous_result": f"PREV={prev_signal} MOM={mom_signal}",
                        "buy_ticker": ticker,
                        "buy_side": side,
                        "stake_usd": round(stake, 4),
                        "price_usd": round(price, 4),
                        "contracts": contracts,
                        "fee_usd": "",
                        "gross_profit_usd": "",
                        "outcome": "",
                        "payout_usd": "",
                        "profit_usd": "",
                    }
                    trades.append(trade)
                    save_trades(trades)
                    traded_keys.add(("CONSENSUS", ticker))

                    direction = "UP" if side == "yes" else "DOWN"
                    print(
                        f"  -> [CONSENSUS] Both agree {side} ({direction}) -> "
                        f"BUY {contracts} (${stake:.2f}) @ ${price:.4f}"
                    )
                elif prev_signal and mom_signal and prev_signal != mom_signal:
                    # They disagree, mark as checked so we don't keep printing
                    traded_keys.add(("CONSENSUS", ticker))
                    print(f"  -> [CONSENSUS] No bet - signals disagree (PREV={prev_signal}, MOM={mom_signal})")

            # === STRATEGY 4: PREVIOUS_2 ===
            if ("PREVIOUS_2", ticker) not in traded_keys:
                prev_signal = signals[ticker].get("PREVIOUS")
                if prev_signal:
                    price = yes_ask if prev_signal == "yes" else no_ask
                    if 0 < price <= DEAL_MAX_PRICE:
                        contracts = STAKE_USD / price
                        trade = {
                            "time": now.isoformat(),
                            "strategy": "PREVIOUS_2",
                            "previous_ticker": pending_previous or "",
                            "previous_result": prev_signal,
                            "buy_ticker": ticker,
                            "buy_side": prev_signal,
                            "stake_usd": STAKE_USD,
                            "price_usd": round(price, 4),
                            "contracts": round(contracts, 4),
                            "outcome": "",
                            "payout_usd": "",
                            "profit_usd": "",
                        }
                        trades.append(trade)
                        save_trades(trades)
                        traded_keys.add(("PREVIOUS_2", ticker))
                        print(f"  -> [PREVIOUS_2] BUY {prev_signal} ${STAKE_USD} @ ${price:.4f}")

            # === STRATEGY 5: CONSENSUS_2 ===
            if ("CONSENSUS_2", ticker) not in traded_keys:
                prev_signal = signals[ticker].get("PREVIOUS")
                mom_signal = signals[ticker].get("MOMENTUM")
                if prev_signal and mom_signal and prev_signal == mom_signal:
                    side = prev_signal
                    price = yes_ask if side == "yes" else no_ask
                    if 0 < price <= DEAL_MAX_PRICE:
                        bankroll = consensus_bankroll(trades)
                        if bankroll > 0:
                            r_value = max(bankroll * CONSENSUS_RISK_PCT, 0.01)
                            daily_cap = CONSENSUS_DAILY_LOSS_CAP_R * r_value
                            weekly_cap = CONSENSUS_WEEKLY_LOSS_CAP_R * r_value
                            day_pnl, week_pnl = consensus_period_pnl(trades, now)
                            if day_pnl <= -daily_cap:
                                print(
                                    f"  -> [CONSENSUS_2] Waiting - daily loss cap hit ({day_pnl:+.2f} <= -{daily_cap:.2f})"
                                )
                                time.sleep(POLL_SECONDS)
                                continue
                            if week_pnl <= -weekly_cap:
                                print(
                                    f"  -> [CONSENSUS_2] Waiting - weekly loss cap hit ({week_pnl:+.2f} <= -{weekly_cap:.2f})"
                                )
                                time.sleep(POLL_SECONDS)
                                continue

                            rolling = rolling_consensus_metrics(trades)
                            if (
                                rolling["sample_size"] >= CONSENSUS_ROLLING_WINDOW
                                and rolling["win_rate"] < rolling["break_even_win_rate"]
                            ):
                                print(
                                    "  -> [CONSENSUS_2] Waiting - rolling win rate below break-even "
                                    f"({rolling['win_rate']*100:.1f}% < {rolling['break_even_win_rate']*100:.1f}%)"
                                )
                                time.sleep(POLL_SECONDS)
                                continue

                            target_stake = bankroll * CONSENSUS_RISK_PCT
                            max_stake = bankroll * CONSENSUS_MAX_RISK_PCT
                            stake = min(max(target_stake, 0.01), max_stake, bankroll)
                            contracts = int(stake / price)
                            max_contracts = int(max_stake / price) if max_stake > 0 else 0
                            contracts = min(contracts, max_contracts) if max_contracts > 0 else contracts
                            if contracts >= 1:
                                stake = contracts * price
                                trade = {
                                    "time": now.isoformat(),
                                    "strategy": "CONSENSUS_2",
                                    "previous_ticker": "",
                                    "previous_result": f"PREV={prev_signal} MOM={mom_signal}",
                                    "buy_ticker": ticker,
                                    "buy_side": side,
                                    "stake_usd": round(stake, 4),
                                    "price_usd": round(price, 4),
                                    "contracts": contracts,
                                    "fee_usd": "",
                                    "gross_profit_usd": "",
                                    "outcome": "",
                                    "payout_usd": "",
                                    "profit_usd": "",
                                }
                                trades.append(trade)
                                save_trades(trades)
                                traded_keys.add(("CONSENSUS_2", ticker))
                                print(
                                    f"  -> [CONSENSUS_2] Both agree {side} -> BUY {contracts} (${stake:.2f}) @ ${price:.4f}"
                                )
                elif prev_signal and mom_signal and prev_signal != mom_signal:
                    traded_keys.add(("CONSENSUS_2", ticker))
                    print(f"  -> [CONSENSUS_2] No bet - signals disagree (PREV={prev_signal}, MOM={mom_signal})")

            # === STRATEGY 6: ARBITRAGE ===
            if ("ARBITRAGE", ticker) not in traded_keys:
                if yes_ask > 0 and no_ask > 0:
                    first_side = "yes" if yes_ask <= no_ask else "no"
                    first_price = yes_ask if first_side == "yes" else no_ask
                    contracts = STAKE_USD / first_price if first_price > 0 else 0
                    trade = {
                        "time": now.isoformat(),
                        "strategy": "ARBITRAGE",
                        "previous_ticker": "",
                        "previous_result": "first_leg",
                        "buy_ticker": ticker,
                        "buy_side": first_side,
                        "stake_usd": STAKE_USD,
                        "price_usd": round(first_price, 4),
                        "contracts": round(contracts, 4),
                        "outcome": "",
                        "payout_usd": "",
                        "profit_usd": "",
                    }
                    trades.append(trade)
                    save_trades(trades)
                    traded_keys.add(("ARBITRAGE", ticker))
                    arb_positions[ticker] = {
                        "side": first_side,
                        "price": first_price,
                        "contracts": contracts,
                        "hedged": False,
                    }
                    print(f"  -> [ARBITRAGE] First leg BUY {first_side} ${STAKE_USD} @ ${first_price:.4f}")

            # ARBITRAGE hedge leg: buy opposite side when it creates an arbitrage and bet < $10
            if ("ARBITRAGE_HEDGE", ticker) not in traded_keys and ticker in arb_positions:
                pos = arb_positions[ticker]
                if not pos["hedged"]:
                    opposite_side = "no" if pos["side"] == "yes" else "yes"
                    opposite_price = no_ask if opposite_side == "no" else yes_ask
                    edge = 1.0 - (pos["price"] + opposite_price)
                    if opposite_price > 0 and edge > 0:
                        max_contracts_by_bet = int((ARBITRAGE_MAX_BET_USD - 0.0001) / opposite_price)
                        hedge_contracts = min(int(pos["contracts"]), max_contracts_by_bet)
                        if hedge_contracts >= 1:
                            hedge_stake = hedge_contracts * opposite_price
                            trade = {
                                "time": now.isoformat(),
                                "strategy": "ARBITRAGE_HEDGE",
                                "previous_ticker": "",
                                "previous_result": f"hedge_of={pos['side']} edge={edge:.4f}",
                                "buy_ticker": ticker,
                                "buy_side": opposite_side,
                                "stake_usd": round(hedge_stake, 4),
                                "price_usd": round(opposite_price, 4),
                                "contracts": hedge_contracts,
                                "outcome": "",
                                "payout_usd": "",
                                "profit_usd": "",
                            }
                            trades.append(trade)
                            save_trades(trades)
                            traded_keys.add(("ARBITRAGE_HEDGE", ticker))
                            pos["hedged"] = True
                            guaranteed = hedge_contracts * edge
                            print(
                                f"  -> [ARBITRAGE] Hedge BUY {opposite_side} ${hedge_stake:.2f} @ ${opposite_price:.4f} "
                                f"(locked edge ${guaranteed:.2f})"
                            )

            # Clear pending_previous after both PREVIOUS and MOMENTUM have traded
            if pending_previous and ("PREVIOUS", ticker) in traded_keys and ("MOMENTUM", ticker) in traded_keys:
                pending_previous = None

            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            print("\nStopped.")
            prev_stats = calc_stats(trades, "PREVIOUS")
            mom_stats = calc_stats(trades, "MOMENTUM")
            cons_stats = calc_stats(trades, "CONSENSUS")
            mom15_stats = calc_stats(trades, "MOMENTUM_15")
            prev2_stats = calc_stats(trades, "PREVIOUS_2")
            cons2_stats = calc_stats(trades, "CONSENSUS_2")
            arb_stats = calc_stats(trades, "ARBITRAGE")
            arb_hedge_stats = calc_stats(trades, "ARBITRAGE_HEDGE")
            total_stats = calc_stats(trades)
            print(f"=== FINAL STATS ===")
            print(f"PREVIOUS:  ${prev_stats['total_profit']:+.2f} | {prev_stats['wins']}W/{prev_stats['losses']}L | {prev_stats['pending']} pending")
            print(f"MOMENTUM:  ${mom_stats['total_profit']:+.2f} | {mom_stats['wins']}W/{mom_stats['losses']}L | {mom_stats['pending']} pending")
            print(f"CONSENSUS: ${cons_stats['total_profit']:+.2f} | {cons_stats['wins']}W/{cons_stats['losses']}L | {cons_stats['pending']} pending")
            print(f"MOMENTUM_15: ${mom15_stats['total_profit']:+.2f} | {mom15_stats['wins']}W/{mom15_stats['losses']}L | {mom15_stats['pending']} pending")
            print(f"PREVIOUS_2:  ${prev2_stats['total_profit']:+.2f} | {prev2_stats['wins']}W/{prev2_stats['losses']}L | {prev2_stats['pending']} pending")
            print(f"CONSENSUS_2: ${cons2_stats['total_profit']:+.2f} | {cons2_stats['wins']}W/{cons2_stats['losses']}L | {cons2_stats['pending']} pending")
            print(
                f"ARBITRAGE:   ${(arb_stats['total_profit'] + arb_hedge_stats['total_profit']):+.2f} | "
                f"{arb_stats['wins'] + arb_hedge_stats['wins']}W/"
                f"{arb_stats['losses'] + arb_hedge_stats['losses']}L | "
                f"{arb_stats['pending'] + arb_hedge_stats['pending']} pending"
            )
            print(f"TOTAL:     ${total_stats['total_profit']:+.2f} | {total_stats['wins']}W/{total_stats['losses']}L")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
