from __future__ import annotations

from datetime import datetime, timezone

from app.routes import decision_ledger as decision_ledger_route
from app.services import pregame_collection_manager as pregame_mgr


def test_pregame_explicit_week_override_wins():
    assert pregame_mgr._resolve_week(7) == 7


def test_pregame_defaults_to_canonical_week(monkeypatch):
    monkeypatch.setattr(pregame_mgr, "resolve_canonical_week_metadata", lambda **kwargs: {"week": 2, "season": 2026})
    assert pregame_mgr._resolve_week(None) == 2


def test_decision_ledger_explicit_week_override_wins(monkeypatch):
    def _fake_games(week=None):
        if week == 9:
            return {
                "games": [
                    {"season": 2026, "week": 9, "eventId": "2026_9_NE_MIA"},
                ],
                "availableWeeks": [1, 2, 9],
            }
        return {"games": [], "availableWeeks": [1, 2, 9]}

    monkeypatch.setattr(decision_ledger_route.games_service, "list_games", _fake_games)
    monkeypatch.setattr(decision_ledger_route, "resolve_canonical_week_metadata", lambda **kwargs: {"week": 2, "season": 2026})

    season, week = decision_ledger_route._resolve_week_and_season(9)

    assert season == 2026
    assert week == 9


def test_decision_ledger_defaults_to_canonical_week(monkeypatch):
    def _fake_games(week=None):
        if week == 2:
            return {
                "games": [
                    {"season": 2026, "week": 2, "eventId": "2026_2_NYG_DAL"},
                ],
                "availableWeeks": [1, 2],
            }
        return {"games": [], "availableWeeks": [1, 2]}

    monkeypatch.setattr(decision_ledger_route.games_service, "list_games", _fake_games)
    monkeypatch.setattr(decision_ledger_route, "resolve_canonical_week_metadata", lambda **kwargs: {"week": 2, "season": 2026})

    season, week = decision_ledger_route._resolve_week_and_season(None)

    assert season == 2026
    assert week == 2


def test_decision_ledger_defaults_to_current_year_when_no_rows(monkeypatch):
    monkeypatch.setattr(decision_ledger_route.games_service, "list_games", lambda week=None: {"games": [], "availableWeeks": []})
    monkeypatch.setattr(decision_ledger_route, "resolve_canonical_week_metadata", lambda **kwargs: {"week": None, "season": None})

    season, week = decision_ledger_route._resolve_week_and_season(None)

    assert season == datetime.now(timezone.utc).year
    assert week == 1
