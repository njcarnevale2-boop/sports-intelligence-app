# 2026 Prospective Validation Protocol

Status: pre-registered before 2026 regular season.

## Scope Labels

- 2018-2025 reconstructed research must be labeled as MARKET-REFERENCE BACKTEST.
- 2026+ immutable decision ledger must be labeled as PROSPECTIVE AUDITED TRACK RECORD.
- Headline performance must not combine these labels without explicit separation.

## Decision Population

- Publication events:
  - SIA_3 publication snapshots
  - MY_CARD explicit add actions
  - optional SYSTEM_SNAPSHOT and OTHER audit events
- SIA slots captured prospectively for rank #1, #2, and #3, including BET, LEAN, WATCH, or PASS.

## Primary Metrics (Frozen)

### SIA 3 Aggregate

- W-L-P
- Win rate (excluding pushes in denominator)
- Profit per dollar and ROI
- CLV
- Average CLV
- Percent beating closing line

### By Rank

- Rank #1 metrics
- Rank #2 metrics
- Rank #3 metrics

### Probability Quality

- Brier score
- Log loss
- Calibration error (reported by bins and overall)

## Required Breakdowns

- Week
- Favorite versus underdog
- Market (spread, total, moneyline)
- SI Score band
- Edge band
- EV band
- Sportsbook

## Integrity Rules

- Decision rows are append-only and immutable.
- Changes in line, price, SI score, or recommendation state create new versions.
- Hash validation is required for ledger integrity checks.
- Outcome capture appends to linked decision records and does not overwrite decision payloads.

## Closing-Line Rules

- Closing line capture uses pre-kickoff snapshots only.
- Post-kick snapshots are excluded.
- Closing-line source methodology must be recorded when consensus is used.

## Governance

- No post-hoc metric redefinition after 2026 results are observed.
- No retroactive creation of official historical SIA 3 records.
- Version fields (model, probability engine, calibration, SI score, ranking, qualification policy, git commit) must be stored with each decision.
