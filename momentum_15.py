#!/usr/bin/env python3
"""
MOMENTUM_15 Strategy Bot - Real Trading on Kalshi

Places trades based on BTC spot momentum over a full 15-minute window.

Requires environment variables:
  KALSHI_API_KEY_ID       - Kalshi API key ID
  KALSHI_PRIVATE_KEY_PATH - Path to RSA private key file
  KALSHI_USE_DEMO         - "true" for demo API, "false" for production
  DRY_RUN                 - "true" to simulate orders without executing
"""

import base64
import csv
import os
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv

# Configuration
SERIES_TICKER = os.getenv("KALSHI_EVENT_TICKER_PREFIX", "KXBTC15M")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "5"))
STAKE_USD = float(os.getenv("STAKE_USD", "5.0"))
MOMENTUM_15_WINDOW_SECONDS = int(os.getenv("MOMENTUM_15_WINDOW_SECONDS", "900"))
TRADES_CSV = Path(os.getenv("MOMENTUM_15_TRADES_CSV", "data/momentum_15_trades.csv"))


def get_api_base():
    """Return API base URL based on KALSHI_USE_DEMO env var."""
    use_demo = os.getenv("KALSHI_USE_DEMO", "true").lower() == "true"
    if use_demo:
        return "https://demo-api.kalshi.co/trade-api/v2"
    return "https://api.elections.kalshi.com/trade-api/v2"


def load_private_key():
    """Load RSA private key from file."""
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    if not key_path:
        raise ValueError("KALSHI_PRIVATE_KEY_PATH environment variable required")

    key_path = os.path.expanduser(key_path)
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    return private_key


class KalshiClient:
    """Authenticated Kalshi API client using RSA key signing."""

    def __init__(self):
        self.api_base = get_api_base()
        self.api_key_id = os.getenv("KALSHI_API_KEY_ID", "")
        if not self.api_key_id:
            raise ValueError("KALSHI_API_KEY_ID environment variable required")

        self.private_key = load_private_key()
        self.session = requests.Session()

    def _sign_request(self, method: str, path: str, timestamp: str) -> str:
        """Generate RSA-PSS signature for request."""
        path_without_query = path.split("?")[0]
        message = f"{timestamp}{method}/trade-api/v2{path_without_query}"
        signature = self.private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _request(self, method: str, path: str, **kwargs):
        """Make authenticated request to Kalshi API."""
        url = f"{self.api_base}{path}"
        timestamp = str(int(time.time() * 1000))
        signature = self._sign_request(method.upper(), path, timestamp)

        headers = kwargs.pop("headers", {})
        headers.update({
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        })

        resp = self.session.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def get_balance(self):
        """Get account balance."""
        return self._request("GET", "/portfolio/balance", timeout=20)

    def get_markets(self, series_ticker, status="open", limit=50):
        """Get markets for a series."""
        params = {"series_ticker": series_ticker, "status": status, "limit": limit}
        resp = self._request("GET", "/markets", params=params, timeout=20)
        return resp.get("markets", [])

    def get_market(self, ticker):
        """Get a specific market."""
        resp = self._request("GET", f"/markets/{ticker}", timeout=20)
        return resp.get("market", {})

    def place_order(self, ticker, side, contracts, price_cents, dry_run=False):
        """
        Place a limit order.

        Args:
            ticker: Market ticker
            side: "yes" or "no"
            contracts: Number of contracts
            price_cents: Price per contract in cents (1-99)
            dry_run: If True, simulate without executing

        Returns:
            Order response dict
        """
        if dry_run:
            return {
                "order": {
                    "order_id": f"DRY-RUN-{uuid.uuid4()}",
                    "status": "simulated",
                    "ticker": ticker,
                    "side": side,
                    "count": contracts,
                }
            }

        order = {
            "ticker": ticker,
            "client_order_id": str(uuid.uuid4()),
            "type": "limit",
            "action": "buy",
            "side": side,
            "count": contracts,
        }

        if side == "yes":
            order["yes_price"] = price_cents
        else:
            order["no_price"] = price_cents

        return self._request("POST", "/portfolio/orders", json=order, timeout=30)


def get_btc_price():
    """Get current BTC price from Coinbase."""
    resp = requests.get(
        "https://api.coinbase.com/v2/prices/BTC-USD/spot",
        timeout=10,
    )
    resp.raise_for_status()
    return float(resp.json()["data"]["amount"])


def get_open_market(client):
    """Get the next expiring open market."""
    markets = client.get_markets(SERIES_TICKER, status="open")
    now = datetime.now(timezone.utc)
    candidates = []

    for market in markets:
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


def get_settled_side(market):
    """Return 'yes' or 'no' if market is settled, else None."""
    result = market.get("result")
    if result in ("yes", "no"):
        return result
    return None


def load_trades():
    """Load trades from CSV."""
    if not TRADES_CSV.exists():
        return []
    with TRADES_CSV.open() as f:
        return list(csv.DictReader(f))


def save_trades(trades):
    """Save trades to CSV."""
    if not trades:
        return
    TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "time",
        "strategy",
        "previous_ticker",
        "previous_result",
        "buy_ticker",
        "buy_side",
        "stake_usd",
        "price_usd",
        "contracts",
        "order_id",
        "outcome",
        "payout_usd",
        "profit_usd",
    ]
    with TRADES_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trades)


def calc_stats(trades):
    """Calculate P&L stats."""
    total_staked = 0.0
    total_profit = 0.0
    wins = 0
    losses = 0
    pending = 0

    for t in trades:
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

    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

    print("=" * 60)
    print("MOMENTUM_15 STRATEGY BOT - REAL TRADING")
    print("=" * 60)
    print(f"Series: {SERIES_TICKER}")
    print(f"Stake: ${STAKE_USD} per trade")
    print(f"Momentum window: {MOMENTUM_15_WINDOW_SECONDS}s")
    print(f"Poll interval: {POLL_SECONDS}s")
    print(f"Trades CSV: {TRADES_CSV}")
    print(f"DRY RUN: {dry_run}")
    print()

    try:
        client = KalshiClient()
        print(f"API: {client.api_base}")
        print(f"API Key: {client.api_key_id[:8]}...")
    except Exception as e:
        print(f"Client init failed: {e}")
        return 1

    try:
        balance = client.get_balance()
        balance_usd = balance.get("balance", 0) / 100
        print(f"Account balance: ${balance_usd:.2f}")
    except Exception as e:
        print(f"Could not fetch balance: {e}")
        return 1

    print()

    current_ticker = None
    pending_previous = None
    trades = load_trades()
    traded_tickers = {t.get("buy_ticker") for t in trades if t.get("buy_ticker")}

    btc_history_len = max(
        200,
        int(MOMENTUM_15_WINDOW_SECONDS / max(POLL_SECONDS, 1)) + 30,
    )
    btc_prices = deque(maxlen=btc_history_len)

    stats = calc_stats(trades)
    print(f"Loaded {len(trades)} trades from CSV")
    print(
        f"Stats: ${stats['total_profit']:+.2f} profit | "
        f"{stats['wins']}W/{stats['losses']}L | {stats['pending']} pending"
    )
    print()
    print("Starting bot loop...")
    print("-" * 60)

    while True:
        try:
            now = datetime.now(timezone.utc)

            try:
                btc_price = get_btc_price()
                btc_prices.append((now, btc_price))
            except Exception as e:
                btc_price = None
                print(f"  [BTC price error: {e}]")

            market = get_open_market(client)

            if not market:
                print(f"[{now.strftime('%H:%M:%S')}] No open market found")
                time.sleep(POLL_SECONDS)
                continue

            ticker = market["ticker"]
            yes_ask = market.get("yes_ask", 0) / 100
            no_ask = market.get("no_ask", 0) / 100

            close_time_str = market.get("close_time", "")
            close_time = (
                datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
                if close_time_str
                else None
            )
            time_to_close = (close_time - now).total_seconds() if close_time else None

            if current_ticker is None:
                current_ticker = ticker
            elif ticker != current_ticker:
                pending_previous = current_ticker
                current_ticker = ticker
                print(f"  Market changed: {pending_previous} -> {ticker}")

            updated = False
            for trade in trades:
                if trade.get("outcome"):
                    continue

                buy_ticker = trade.get("buy_ticker")
                if not buy_ticker:
                    continue

                try:
                    m = client.get_market(buy_ticker)
                    result = get_settled_side(m)
                    if result:
                        buy_side = trade.get("buy_side")
                        contracts = float(trade.get("contracts", 0))
                        stake = float(trade.get("stake_usd", 0))

                        won = result == buy_side
                        payout = contracts if won else 0
                        profit = payout - stake

                        trade["outcome"] = "WIN" if won else "LOSS"
                        trade["payout_usd"] = round(payout, 4)
                        trade["profit_usd"] = round(profit, 4)
                        updated = True

                        print(
                            f"  ** SETTLED {buy_ticker}: {trade['outcome']} ${profit:+.2f}"
                        )
                except Exception:
                    pass

            if updated:
                save_trades(trades)

            stats = calc_stats(trades)
            btc_str = f"BTC=${btc_price:,.0f}" if btc_price else "BTC=?"
            time_str = f"{time_to_close:.0f}s" if time_to_close else "?"
            mode_str = "[DRY]" if dry_run else "[LIVE]"
            print(
                f"[{now.strftime('%H:%M:%S')}] {mode_str} {ticker} ({time_str}) | "
                f"yes=${yes_ask:.2f} no=${no_ask:.2f} | {btc_str} | "
                f"P&L: ${stats['total_profit']:+.2f}"
            )

            # Wait for market rollover before evaluating this strategy.
            if not pending_previous:
                time.sleep(POLL_SECONDS)
                continue

            if ticker in traded_tickers:
                time.sleep(POLL_SECONDS)
                continue

            cutoff = now - timedelta(seconds=MOMENTUM_15_WINDOW_SECONDS)
            old_prices = [(t, p) for t, p in btc_prices if t <= cutoff]

            if not old_prices:
                print(
                    f"  Waiting for full {MOMENTUM_15_WINDOW_SECONDS}s BTC history "
                    f"before trading {ticker}"
                )
                time.sleep(POLL_SECONDS)
                continue

            _, old_price = old_prices[-1]
            _, current_price = btc_prices[-1]
            side = "yes" if current_price > old_price else "no"
            pct_change = ((current_price - old_price) / old_price) * 100

            price = yes_ask if side == "yes" else no_ask
            if price <= 0:
                print(f"  Invalid price ${price:.4f}, skipping {ticker}")
                traded_tickers.add(ticker)
                time.sleep(POLL_SECONDS)
                continue

            contracts = int(STAKE_USD / price)
            if contracts < 1:
                contracts = 1

            stake_actual = contracts * price
            price_cents = int(price * 100)

            print()
            print(f"  >>> MOMENTUM_15 SIGNAL: {side.upper()} (BTC15 {pct_change:+.3f}%) <<<")
            print(
                f"  Placing order: BUY {contracts} {side} @ ${price:.2f} "
                f"(${stake_actual:.2f} total)"
            )

            try:
                order_resp = client.place_order(
                    ticker=ticker,
                    side=side,
                    contracts=contracts,
                    price_cents=price_cents,
                    dry_run=dry_run,
                )
                order = order_resp.get("order", {})
                order_id = order.get("order_id", "?")
                print(f"  Order placed! ID: {order_id}")

                trade = {
                    "time": now.isoformat(),
                    "strategy": "MOMENTUM_15",
                    "previous_ticker": pending_previous,
                    "previous_result": f"BTC15 {pct_change:+.3f}%",
                    "buy_ticker": ticker,
                    "buy_side": side,
                    "stake_usd": round(stake_actual, 4),
                    "price_usd": round(price, 4),
                    "contracts": contracts,
                    "order_id": order_id,
                    "outcome": "",
                    "payout_usd": "",
                    "profit_usd": "",
                }
                trades.append(trade)
                save_trades(trades)
                traded_tickers.add(ticker)
                pending_previous = None
            except Exception as e:
                print(f"  ORDER FAILED: {e}")
                traded_tickers.add(ticker)

            print()
            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            print("\n")
            print("=" * 60)
            print("STOPPED - FINAL STATS")
            print("=" * 60)
            stats = calc_stats(trades)
            print(f"Total trades: {len(trades)}")
            print(f"Wins: {stats['wins']} | Losses: {stats['losses']} | Pending: {stats['pending']}")
            print(f"Total staked: ${stats['total_staked']:.2f}")
            print(f"Total profit: ${stats['total_profit']:+.2f}")
            if stats["total_staked"] > 0:
                roi = (stats["total_profit"] / stats["total_staked"]) * 100
                print(f"ROI: {roi:.1f}%")
            break

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(POLL_SECONDS)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
