from __future__ import annotations

from app.services.result_engine.contracts import AcceptedFinalGameResult

from .contracts import FinalGameResult
from .validation import validate_final_result


def accepted_result_to_final_game_result(result: AcceptedFinalGameResult) -> FinalGameResult:
    out = FinalGameResult(
        season=result.season,
        week=result.week,
        game_id=result.canonical_event_key,
        kickoff_utc=result.kickoff_utc,
        home_team=result.home_team,
        away_team=result.away_team,
        home_score=result.home_score,
        away_score=result.away_score,
        source_result_version=result.source_result_version,
    )
    validate_final_result(out)
    return out
