INVALID - SPREAD SIGN BUG

# SIA Strict OOT Validation (Current Production Engine)

## Sample
- Total rows: 1139
- Eligible rows: 931
- Warmup rows: 208
- Eligible non-push scored: 917

## Scoring
- Current engine Brier: 0.220893
- Market Brier: 0.249475
- Current engine LogLoss: 0.628617
- Market LogLoss: 0.692097
- Beats market Brier: True
- Beats market LogLoss: True

## Notes
- This study is research-only and does not modify any production threshold, ranking, API, or UI logic.
- Historical file lacks direct per-row Sports Intelligence Score; production ranking is represented by the available historical production rank proxy score in validation_spread_bets.
