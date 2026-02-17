# CONSENSUS Strategy

## Goal
Only trade when two independent signals agree:
- `PREVIOUS` direction
- `MOMENTUM` (60s BTC direction)

## Signal
- `PREVIOUS` gives `yes` or `no`.
- `MOMENTUM` gives `yes` or `no`.
- Entry signal is valid only when both exist and are equal.

## Entry Conditions
- No existing `CONSENSUS` trade for the current `ticker`.
- Signals agree.
- Ask price is valid and `<= CONSENSUS_MAX_PRICE` (default `0.55`).
- Consensus bankroll is positive.
- Daily and weekly loss caps are not breached.
- Rolling performance check passes if sample window is filled.

## Risk / Sizing
- Bankroll basis: `INITIAL_BANKROLL_USD + realized P&L of settled consensus trades`.
- Target risk: `CONSENSUS_RISK_PCT` of bankroll.
- Hard cap: `CONSENSUS_MAX_RISK_PCT` of bankroll.
- Buys integer contracts only: `contracts = int(stake / price)`.

## Execution
- Immediate buy on agreed side (`yes` or `no`) at current ask.
- Stake = `contracts * ask`.

## Settlement / P&L
- Gross profit = `payout - stake`.
- Fee applied: `stake * CONSENSUS_FEE_PCT`.
- Net profit = `gross_profit - fee`.

## Notes
- If signals disagree, strategy marks market as no-trade and moves on.
- This strategy is designed to reduce false positives at the cost of fewer entries.
