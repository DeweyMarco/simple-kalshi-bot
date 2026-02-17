# MOMENTUM Strategy

## Goal
Trade with very short-term BTC direction over the last 60 seconds.

## Signal
- Source: Coinbase BTC spot price sampled every poll cycle.
- Lookback window: `MOMENTUM_WINDOW_SECONDS` (default `60`).
- Rule:
- If current BTC price > BTC price from at least 60 seconds ago, signal `yes`.
- Otherwise signal `no`.

## Entry Conditions
- A market rollover has occurred (`pending_previous` exists).
- At least one historical BTC point exists at or before the 60s cutoff.
- No existing `MOMENTUM` trade for the current `ticker`.

## Execution
- Buys immediately at current ask on the signaled side.
- Stake is fixed (`STAKE_USD`, default `$5`).
- Contracts are fractional: `contracts = STAKE_USD / price`.

## Trade Record Fields
- `strategy = MOMENTUM`
- `previous_result` stores formatted BTC move, e.g. `BTC +0.123%`
- Standard order fields: side, stake, price, contracts

## Settlement / P&L
- Profit = `payout - stake`.
- No strategy-specific fee.

## Notes
- This is independent from previous market settlement.
- It is fast-reacting and sensitive to short-term noise.
