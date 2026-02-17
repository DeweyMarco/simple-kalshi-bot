# ARBITRAGE Strategy

## Goal
Enter immediately, then add an opposite-side hedge only when a positive arbitrage edge appears.

## Leg 1 (Immediate Entry)

### Signal
- Uses current market asks only.
- Chooses cheaper side first:
- If `yes_ask <= no_ask`, first side is `yes`; else first side is `no`.

### Entry Conditions
- No existing `ARBITRAGE` trade for current `ticker`.
- Both asks are valid (`> 0`).

### Execution
- Immediate buy with fixed stake (`STAKE_USD`, default `$5`).
- Contracts are fractional: `contracts = STAKE_USD / first_price`.
- Position state is stored for hedge evaluation.

## Leg 2 (Hedge Entry)

### Hedge Rule
- Opposite ask is monitored every poll cycle.
- Arbitrage edge formula:
- `edge = 1 - (first_price + opposite_price)`
- Hedge only if `edge > 0`.

### Hedge Size Constraint
- Hedge trade must be less than `$10`.
- Max hedge contracts: `int((ARBITRAGE_MAX_BET_USD - 0.0001) / opposite_price)`.
- Actual hedge contracts are capped by both:
- Existing first-leg contracts
- Max contracts allowed by `< $10` hedge limit

### Execution
- Places `ARBITRAGE_HEDGE` trade on opposite side.
- Marks position as hedged to avoid repeated hedge entries.

## Settlement / P&L
- Leg 1 and hedge leg settle independently as normal binary contracts.
- Combined result (first leg + hedge leg) reflects the realized arbitrage profile.
- No strategy-specific fee.

## Notes
- If no positive edge appears before market close, only first leg remains.
- Hedge limit applies per hedge order, not as a global daily cap.
