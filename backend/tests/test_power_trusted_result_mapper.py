from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.power_engine.trusted_result_mapper import accepted_result_to_final_game_result
from result_engine_test_utils import make_accepted_result


def test_power_handoff_mapper_has_no_provider_specific_payload_dependency():
    accepted = make_accepted_result(
        season=2030,
        week=3,
        away_team="ARI",
        home_team="ATL",
        source="sportradar_nfl",
        source_event_id="provider-event-guid",
        source_result_version="derived:sr-result-v1:abc123",
    )

    out = accepted_result_to_final_game_result(accepted)

    assert out.season == accepted.season
    assert out.week == accepted.week
    assert out.game_id == accepted.canonical_event_key
    assert out.kickoff_utc == accepted.kickoff_utc
    assert out.home_team == accepted.home_team
    assert out.away_team == accepted.away_team
    assert out.home_score == accepted.home_score
    assert out.away_score == accepted.away_score
    assert out.source_result_version == accepted.source_result_version
