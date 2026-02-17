# PREVIOUS_2 Strategy

## Goal
Use the same directional logic as `PREVIOUS`, but wait for a better entry price.

## Signal
- Same as `PREVIOUS`:
- Previous settled market result `yes` -> target `yes`.
- Previous settled market result `no` -> target `no`.

## Entry Conditions
- `PREVIOUS` signal exists for current market.
- No existing `PREVIOUS_2` trade for current `ticker`.
- Current ask for target side is `<= DEAL_MAX_PRICE` (default `0.45`).

## Execution
- Does not buy immediately.
- Polls each cycle and enters only when price condition is met.
- Stake remains fixed (`STAKE_USD`, default `$5`).
- Contracts are fractional: `contracts = STAKE_USD / price`.

## Trade Record Fields
- `strategy = PREVIOUS_2`
- Directional fields match `PREVIOUS`.

## Settlement / P&L
- Profit = `payout - stake`.
- No strategy-specific fee.

## Notes
- If price never reaches `0.45` or lower before market close, no trade is placed.
- This strategy trades less often than `PREVIOUS` by design.
