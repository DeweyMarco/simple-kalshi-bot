# MOMENTUM_15 Strategy

## Goal
Trade BTC direction using a full 15-minute momentum window.

## Signal
- Source: Coinbase BTC spot price history.
- Lookback window: `MOMENTUM_15_WINDOW_SECONDS = 900` seconds.
- Rule:
- If current BTC price > price from at least 15 minutes ago, signal `yes`.
- Otherwise signal `no`.

## Entry Conditions
- A market rollover has occurred (`pending_previous` exists).
- BTC history contains data at or before the 15-minute cutoff.
- No existing `MOMENTUM_15` trade for the current `ticker`.

## Execution
- Immediate buy at current ask on the signaled side.
- Fixed stake (`STAKE_USD`, default `$5`).
- Contracts are fractional: `contracts = STAKE_USD / price`.

## Trade Record Fields
- `strategy = MOMENTUM_15`
- `previous_result` stores formatted BTC move, e.g. `BTC15 -0.250%`

## Settlement / P&L
- Profit = `payout - stake`.
- No strategy-specific fee.

## Notes
- Uses a longer horizon than `MOMENTUM`, so it is less sensitive to micro-noise.
- Bot keeps a larger BTC history buffer to ensure full 15-minute coverage.
