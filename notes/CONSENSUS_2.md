# CONSENSUS_2 Strategy

## Goal
Use `CONSENSUS` agreement logic, but wait for discounted entry (`<= $0.45`).

## Signal
- Requires `PREVIOUS` and `MOMENTUM` signals.
- Valid only when both signals agree on the same side.

## Entry Conditions
- No existing `CONSENSUS_2` trade for current `ticker`.
- Agreement signal exists.
- Ask price for agreed side is `<= DEAL_MAX_PRICE` (default `0.45`).
- Consensus bankroll is positive.
- Daily and weekly consensus loss caps are not hit.
- Rolling break-even performance gate passes once sample is full.

## Risk / Sizing
- Shares consensus bankroll framework with `CONSENSUS`.
- Target risk: `CONSENSUS_RISK_PCT`.
- Max risk per trade: `CONSENSUS_MAX_RISK_PCT`.
- Integer contracts only.

## Execution
- Waits for price threshold; enters only when threshold is met.
- Stake = `contracts * ask`.

## Settlement / P&L
- Gross profit = `payout - stake`.
- Fee applies like `CONSENSUS`: `stake * CONSENSUS_FEE_PCT`.
- Net profit = `gross_profit - fee`.

## Notes
- `CONSENSUS_2` realized P&L is included in shared consensus bankroll and rolling metrics.
- Compared to `CONSENSUS`, this reduces entry frequency and usually improves entry price.
