# Invalidated Research Reports (Audit Trail)

These reports were invalidated because historical spread_line was incorrectly treated as the home-team spread.

Canonical spread convention:
- spread_line belongs to the AWAY team.
- Negative spread_line means away favorite.
- Positive spread_line means away underdog.

The corrected historical baseline supersedes these reports:
- backend/research_outputs/sia_corrected_historical_baseline_report.md
- backend/research_outputs/sia_corrected_historical_baseline_report.json

Files in this directory are preserved only for audit trail and historical traceability.
They must never be used as current model-performance evidence.
