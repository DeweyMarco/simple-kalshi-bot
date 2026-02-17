# PREVIOUS Strategy

## Goal
Follow short-term market persistence by betting the same side as the last settled `KXBTC15M` market.

## Signal
- Input: previous market settlement result (`yes` or `no`).
- Rule: if previous market settled `yes`, buy `yes` in the new market; if `no`, buy `no`.

## Entry Conditions
- A market rollover happened (new `ticker` became current).
- Previous market has settled.
- No existing `PREVIOUS` trade for the current `ticker`.

## Execution
- Buys immediately at current ask for the chosen side:
- `price = yes_ask` for `yes`, `price = no_ask` for `no`.
- Stake is fixed (`STAKE_USD`, default `$5`).
- Contracts are fractional: `contracts = STAKE_USD / price`.

## Trade Record Fields
- `strategy = PREVIOUS`
- `previous_ticker =` the just-finished market
- `previous_result = yes|no`
- `buy_ticker`, `buy_side`, `stake_usd`, `price_usd`, `contracts`

## Settlement / P&L
- Win payout = `contracts`; loss payout = `0`.
- Profit = `payout - stake`.
- No strategy-specific fee.

## Notes
- This strategy does not price-filter entries.
- It can enter at expensive asks if available.
