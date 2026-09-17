from __future__ import annotations

import os
import sys
from dataclasses import replace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.result_engine import ResultEngineValidationError, validate_week_completeness
from result_engine_test_utils import make_accepted_result, make_identity


def test_all_expected_games_accepted_once_is_complete():
    event_a = make_identity(away_team="NE", home_team="SEA")
    event_b = make_identity(away_team="ATL", home_team="TB", kickoff_utc="2026-09-10T03:00:00Z")

    accepted = [
        make_accepted_result(
            away_team="NE",
            home_team="SEA",
            source_event_id="a",
        ),
        make_accepted_result(
            away_team="ATL",
            home_team="TB",
            kickoff_utc="2026-09-10T03:00:00Z",
            source_event_id="b",
        ),
    ]

    result = validate_week_completeness(
        season=2026,
        week=1,
        expected_events=[event_a, event_b],
        accepted_results=accepted,
    )

    assert result.is_complete is True
    assert result.missing_event_keys == ()
    assert result.unexpected_event_keys == ()


def test_missing_expected_game_is_incomplete():
    event_a = make_identity(away_team="NE", home_team="SEA")
    event_b = make_identity(away_team="ATL", home_team="TB", kickoff_utc="2026-09-10T03:00:00Z")

    accepted = [make_accepted_result(away_team="NE", home_team="SEA", source_event_id="a")]

    result = validate_week_completeness(
        season=2026,
        week=1,
        expected_events=[event_a, event_b],
        accepted_results=accepted,
    )

    assert result.is_complete is False
    assert len(result.missing_event_keys) == 1


def test_unexpected_result_is_incomplete():
    event_a = make_identity(away_team="NE", home_team="SEA")
    accepted = [
        make_accepted_result(away_team="NE", home_team="SEA", source_event_id="a"),
        make_accepted_result(away_team="ATL", home_team="TB", kickoff_utc="2026-09-10T03:00:00Z", source_event_id="b"),
    ]

    result = validate_week_completeness(
        season=2026,
        week=1,
        expected_events=[event_a],
        accepted_results=accepted,
    )

    assert result.is_complete is False
    assert len(result.unexpected_event_keys) == 1


def test_duplicate_event_is_incomplete():
    event_a = make_identity(away_team="NE", home_team="SEA")
    accepted_a = make_accepted_result(away_team="NE", home_team="SEA", source_event_id="a")
    accepted_b = make_accepted_result(away_team="NE", home_team="SEA", source_event_id="b")

    result = validate_week_completeness(
        season=2026,
        week=1,
        expected_events=[event_a],
        accepted_results=[accepted_a, accepted_b],
    )

    assert result.is_complete is False
    assert len(result.duplicate_event_keys) == 1


def test_duplicate_team_appearance_is_incomplete():
    event_a = make_identity(away_team="NE", home_team="SEA")
    event_b = make_identity(away_team="NE", home_team="ATL", kickoff_utc="2026-09-11T00:15:00Z")

    accepted = [
        make_accepted_result(away_team="NE", home_team="SEA", source_event_id="a"),
        make_accepted_result(away_team="NE", home_team="ATL", kickoff_utc="2026-09-11T00:15:00Z", source_event_id="b"),
    ]

    result = validate_week_completeness(
        season=2026,
        week=1,
        expected_events=[event_a, event_b],
        accepted_results=accepted,
    )

    assert result.is_complete is False
    assert "NE" in result.duplicate_team_appearances


    def test_week_completeness_zero_expected_fails_closed_by_default():
        result = validate_week_completeness(
            season=2026,
            week=7,
            expected_events=[],
            accepted_results=[],
        )

        assert result.expected_count == 0
        assert result.accepted_count == 0
        assert result.is_complete is False


    def test_week_completeness_zero_expected_can_be_allowed_for_bye_week():
        result = validate_week_completeness(
            season=2026,
            week=7,
            expected_events=[],
            accepted_results=[],
            allow_zero_game_week=True,
        )

        assert result.is_complete is True


    def test_week_completeness_detects_identity_mismatch_on_same_event_key():
        expected_identity = make_identity()
        accepted = make_accepted(identity=expected_identity, kickoff_utc="2026-09-11T00:15:00Z")

        result = validate_week_completeness(
            season=2026,
            week=1,
            expected_events=[expected_identity],
            accepted_results=[accepted],
        )

        assert result.identity_mismatch_event_keys == (expected_identity.canonical_event_key,)
        assert result.is_complete is False


def test_wrong_season_or_week_in_results_is_rejected():
    event_a = make_identity(away_team="NE", home_team="SEA")
    bad = make_accepted_result(season=2027, away_team="NE", home_team="SEA", source_event_id="a")

    with pytest.raises(ResultEngineValidationError, match="must all match"):
        validate_week_completeness(
            season=2026,
            week=1,
            expected_events=[event_a],
            accepted_results=[bad],
        )


def test_corrupt_accepted_result_fails_before_completeness_complete():
    event_a = make_identity(away_team="NE", home_team="SEA")
    accepted = make_accepted_result(away_team="NE", home_team="SEA", source_event_id="a")
    corrupt = replace(accepted, payload_hash="0" * 64)

    with pytest.raises(ResultEngineValidationError, match="payload hash mismatch"):
        validate_week_completeness(
            season=2026,
            week=1,
            expected_events=[event_a],
            accepted_results=[corrupt],
        )
