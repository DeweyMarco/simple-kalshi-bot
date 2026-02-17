# CONSENSUS Strategy Improvement Plan

## Context
Current benchmark from `analyze.py` on mock data:
- Win rate: 70.37% (19W / 8L)
- Profit: $39.31
- ROI: 29.12%
- Avg profit/trade: $1.46

## Goals
1. Keep using CONSENSUS as primary signal.
2. Improve execution realism.
3. Add risk controls so the strategy scales safely.
4. Pause automatically when edge weakens.

## Improvements

### 1. Prove edge with larger sample
- Target: at least 100+ settled CONSENSUS trades before scaling aggressively.
- Status: process change (no code needed).

### 2. Size by bankroll (not fixed $5)
- Rule: risk 1% of CONSENSUS bankroll per trade, capped at 2%.
- Status: implemented in `bot.py`.
- Config:
  - `INITIAL_BANKROLL_USD` (default `500`)
  - `CONSENSUS_RISK_PCT` (default `0.01`)
  - `CONSENSUS_MAX_RISK_PCT` (default `0.02`)

### 3. Add price filter
- Rule: skip CONSENSUS entries when ask price is too high.
- Default: `price <= 0.55`.
- Status: implemented in `bot.py`.
- Config: `CONSENSUS_MAX_PRICE` (default `0.55`).

### 4. Add daily and weekly loss caps
- Rule: stop new CONSENSUS entries after hitting risk-budgeted drawdown.
- Defaults:
  - Daily cap: `3R`
  - Weekly cap: `8R`
  - `R = bankroll * CONSENSUS_RISK_PCT`
- Status: implemented in `bot.py`.
- Config:
  - `CONSENSUS_DAILY_LOSS_CAP_R` (default `3`)
  - `CONSENSUS_WEEKLY_LOSS_CAP_R` (default `8`)

### 5. Keep one trade per market and no-trade on disagreement
- Rule: single CONSENSUS attempt per ticker; skip when PREVIOUS != MOMENTUM.
- Status: already present; retained in `bot.py`.

### 6. Pause when rolling performance loses edge
- Rule: monitor rolling window win rate and compare against break-even win rate from avg win/loss.
- Action: skip new CONSENSUS entries when rolling win rate < break-even.
- Status: implemented in `bot.py`.
- Config: `CONSENSUS_ROLLING_WINDOW` (default `30`).

### 7. Fee-aware P&L
- Rule: subtract fees from realized profit.
- Status: implemented in `bot.py` settlement logic.
- Config: `CONSENSUS_FEE_PCT` (default `0.0`, set >0 to simulate fees).

### 8. Fill verification / partial fills
- Rule: only record executed quantity and real fill price.
- Status: not applicable to mock `bot.py` (no live order lifecycle).
- Next step: implement in live `consensus.py` using order status/filled-count fields.

## What was updated now
- `bot.py`
  - Added consensus risk config via env vars.
  - Added bankroll-based position sizing.
  - Added max-price entry filter.
  - Added daily and weekly loss cap checks.
  - Added rolling break-even pause check.
  - Added fee-aware realized P&L (`fee_usd`, `gross_profit_usd`).
  - Added status print for consensus bankroll.

## Quick test run
1. Keep defaults and run:
   - `python bot.py`
2. Simulate fees:
   - `CONSENSUS_FEE_PCT=0.02 python bot.py`
3. More conservative entry pricing:
   - `CONSENSUS_MAX_PRICE=0.52 python bot.py`
4. Tighter risk:
   - `CONSENSUS_RISK_PCT=0.005 CONSENSUS_MAX_RISK_PCT=0.01 python bot.py`

## Notes
- `analyze.py` will continue to work; it reads `profit_usd` and `stake_usd` and ignores extra CSV columns.
- Fee impact only appears if `CONSENSUS_FEE_PCT` is set above `0`.
