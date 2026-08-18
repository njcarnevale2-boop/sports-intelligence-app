INVALID - SPREAD SIGN BUG

# SIA Out-of-Time Calibration Research Report

## Scope
Read-only research pipeline. No production recommendation logic, UI, thresholds, or API behavior modified.

## OOS Sample
- Sample size: 1139
- Seasons: 2022, 2023, 2024, 2025
- Pushes: 29

## Baselines
- Raw Brier: 0.257219
- Market Brier: 0.249708
- Raw Log Loss: 0.709103
- Market Log Loss: 0.692562

## Best Calibration
- Method: guarded_isotonic_structural
- Brier: 0.251280
- Log Loss: 0.696002
- Beats market Brier: False
- Beats market Log Loss: False

## Limitations
- No untouched post-2025 holdout season exists in this 2022-2025 OOS sample.
- Current dataset is spread decisions only; totals and moneyline calibration are out of scope here.
- Historical SI Score / production ranking signal is not present in walkforward_multiseason_predictions.csv, so ranking research uses available probability/EV/edge signals only.
