# Simple Kalshi Bot (Multi-Strategy Mock Trading)

This bot paper-trades three strategies on Kalshi's KXBTC15M (Bitcoin 15-minute) markets:

1. **PREVIOUS**: Buy the same side as the previous market's settled result (trend following)
2. **MOMENTUM**: Buy based on BTC spot price direction over the last 60 seconds
3. **CONSENSUS**: Buy only when PREVIOUS and MOMENTUM agree on the same side

All trades are simulated (mock) and logged to CSV for analysis.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create env file:
```bash
cp .env.example .env
```

3. Edit `.env` to configure your settings (see Configuration below)

## Run

```bash
python3 bot.py
```

Stop with `Ctrl+C` to see final statistics.

## Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `KALSHI_USE_DEMO` | `true` | `true` for demo API, `false` for production |
| `KALSHI_EVENT_TICKER_PREFIX` | `KXBTC15M` | Market series to watch |
| `POLL_SECONDS` | `5` | Polling interval in seconds |
| `MOCK_BUY_USD` | `5` | Paper stake per trade in USD |
| `MOCK_TRADES_CSV_PATH` | `data/mock_trades.csv` | Output CSV path |
| `MOMENTUM_WINDOW_SECONDS` | `60` | Lookback window for BTC momentum |

## Output CSV Columns

| Column | Description |
|--------|-------------|
| `time` | ISO timestamp of mock trade |
| `strategy` | `PREVIOUS`, `MOMENTUM`, or `CONSENSUS` |
| `previous_ticker` | The previous market ticker (for PREVIOUS/MOMENTUM) |
| `previous_result` | What triggered the trade (settled side or BTC % change) |
| `buy_ticker` | Market ticker being traded |
| `buy_side` | `yes` or `no` |
| `stake_usd` | Amount staked |
| `price_usd` | Entry price per contract |
| `contracts` | Number of contracts (stake / price) |
| `outcome` | `WIN`, `LOSS`, or empty if pending |
| `payout_usd` | Payout if won (contracts), 0 if lost |
| `profit_usd` | Net profit/loss (payout - stake) |

## How It Works

1. Bot polls for the next expiring open market in the configured series
2. When a market closes and a new one opens:
   - **PREVIOUS** checks the settled result and buys that side on the new market
   - **MOMENTUM** compares current BTC price to price 60s ago and buys accordingly
   - **CONSENSUS** only trades if both signals agree
3. Pending trades are checked for settlement each poll cycle
4. Statistics are updated and displayed in real-time

## Notes

- This is a paper trading bot - no real orders are placed
- Each strategy stakes independently (up to $15 total exposure when all agree)
- The bot uses Coinbase's public API for BTC spot prices
- Demo mode uses `demo-api.kalshi.com`, production uses `trading-api.kalshi.com`
