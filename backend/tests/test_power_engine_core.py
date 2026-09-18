from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path

import pytest

from app.services.power_engine import (
    CANONICAL_NFL_TEAMS,
    ERROR_CAP,
    GAME_SHRINK,
    HFA,
    K,
    FinalGameResult,
    PowerSnapshot,
    PowerTeamRating,
    apply_single_game_update,
    apply_week_results,
    methodology_hash,
    snapshot_hash,
    validate_snapshot,
)
from app.services.power_engine.projection import model_margin_home
from app.services.result_engine.teams import normalize_team_id


_PHASE2E8_ENABLE_ENV = "SIA_RUN_PHASE2E8_PARITY"
_PHASE2E8_BASELINE_ENV = "SIA_PHASE2E8_BASELINE_CSV"
_PHASE2E8_RESULTS_ENV = "SIA_PHASE2E8_RESULTS_PARQUET"
_PHASE2E8_TARGET_ENV = "SIA_PHASE2E8_TARGET_SNAPSHOT"

_PHASE2E8_WEEK2_MARGIN_REFERENCE = {
    "DET@BUF": 6.334767,
    "CAR@ATL": 4.975323,
    "CIN@HOU": 1.855269,
    "CLE@TB": 4.313074,
    "GB@NYJ": -6.461671,
    "MIN@CHI": -1.071322,
    "NO@BAL": 0.814307,
    "PHI@TEN": -5.147469,
    "PIT@NE": 6.787993,
    "JAX@DEN": -4.768764,
    "LV@LAC": 3.242472,
    "MIA@SF": 4.579205,
    "SEA@ARI": -7.157223,
    "WAS@DAL": 0.712522,
    "IND@KC": 3.819167,
    "NYG@LAR": 0.885611,
}


def _teams() -> tuple[PowerTeamRating, ...]:
    return tuple(
        PowerTeamRating(team_id=team, power=float(index) / 10.0)
        for index, team in enumerate(CANONICAL_NFL_TEAMS)
    )


def _snapshot(*, through_week: int = 0, teams: tuple[PowerTeamRating, ...] | None = None) -> PowerSnapshot:
    base_teams = teams or _teams()
    snap = PowerSnapshot(
        snapshot_id="preseason-2026",
        snapshot_hash="",
        season=2026,
        through_week=through_week,
        updater_version="u1",
        methodology_hash="m1",
        source_snapshot_id=None,
        generated_at="2026-09-16T00:00:00+00:00",
        teams=base_teams,
    )
    return PowerSnapshot(
        snapshot_id=snap.snapshot_id,
        snapshot_hash=snapshot_hash(snap),
        season=snap.season,
        through_week=snap.through_week,
        updater_version=snap.updater_version,
        methodology_hash=snap.methodology_hash,
        source_snapshot_id=snap.source_snapshot_id,
        generated_at=snap.generated_at,
        teams=snap.teams,
    )


def _result(
    *,
    game_id: str = "2026_01_ARI_ATL",
    kickoff: str = "2026-09-10T20:20:00+00:00",
    home_team: str = "ATL",
    away_team: str = "ARI",
    home_score: int = 24,
    away_score: int = 17,
) -> FinalGameResult:
    return FinalGameResult(
        season=2026,
        week=1,
        game_id=game_id,
        kickoff_utc=kickoff,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        source_result_version="scores-v1",
    )


def _phase2e8_enabled() -> bool:
    return str(os.getenv(_PHASE2E8_ENABLE_ENV, "")).strip() == "1"


def _phase2e8_skip() -> None:
    pytest.skip(
        "Historical Phase 2E.8 parity replay is opt-in; set "
        f"{_PHASE2E8_ENABLE_ENV}=1 with durable input paths in the environment"
    )


def _phase2e8_env_path(name: str) -> Path:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        pytest.fail(f"Missing required environment variable for historical replay: {name}")
    path = Path(raw)
    if not path.exists():
        pytest.fail(f"Historical replay input does not exist: env={name} path={path}")
    return path


def _phase2e8_preweek_snapshot_from_csv(path: Path) -> PowerSnapshot:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        teams = tuple(
            PowerTeamRating(
                team_id=normalize_team_id(row["team"]),
                power=float(row["power_points"]),
            )
            for row in reader
        )

    snapshot = PowerSnapshot(
        snapshot_id="power-2026-preweek-044ddd78ebb0",
        snapshot_hash="",
        season=2026,
        through_week=0,
        updater_version="sia_power_engine_2e4a_v1",
        methodology_hash=methodology_hash(
            __import__("app.services.power_engine.methodology", fromlist=["FROZEN_METHODOLOGY"]).FROZEN_METHODOLOGY,
            "sia_power_engine_2e4a_v1",
        ),
        source_snapshot_id=None,
        generated_at="2026-09-17T21:53:35Z",
        teams=teams,
    )
    return PowerSnapshot(
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot_hash(snapshot),
        season=snapshot.season,
        through_week=snapshot.through_week,
        updater_version=snapshot.updater_version,
        methodology_hash=snapshot.methodology_hash,
        source_snapshot_id=snapshot.source_snapshot_id,
        generated_at=snapshot.generated_at,
        teams=snapshot.teams,
    )


def _phase2e8_results_from_parquet(path: Path) -> tuple[FinalGameResult, ...]:
    import pandas as pd

    df = pd.read_parquet(path)
    week1 = df[(df["season"] == 2026) & (df["week"] == 1)].copy()
    week1 = week1.sort_values(["gameday", "gametime", "game_id"]).reset_index(drop=True)

    return tuple(
        FinalGameResult(
            season=2026,
            week=1,
            game_id=str(row.game_id),
            kickoff_utc=f"{row.gameday}T{row.gametime}:00+00:00",
            home_team=normalize_team_id(row.home_team),
            away_team=normalize_team_id(row.away_team),
            home_score=int(row.home_score),
            away_score=int(row.away_score),
            source_result_version="derived:nflverse_schedules_games.parquet:16d596881aaf28f4f69ab1834ebd11a6f34534c4bbed7462d8a5a7fda2be4340",
        )
        for row in week1.itertuples(index=False)
    )


def _phase2e8_independent_reference(snapshot: PowerSnapshot, results: tuple[FinalGameResult, ...]) -> dict[str, float]:
    powers = {team.team_id: float(team.power) for team in snapshot.teams}
    deltas = {team_id: 0.0 for team_id in powers}

    for result in results:
        expected_home_margin = powers[result.home_team] - powers[result.away_team] + HFA
        actual_home_margin = float(result.home_score - result.away_score)
        residual = actual_home_margin - expected_home_margin
        clipped_residual = max(-ERROR_CAP, min(ERROR_CAP, residual))
        home_delta = K * clipped_residual
        away_delta = -home_delta
        deltas[result.home_team] += home_delta
        deltas[result.away_team] += away_delta

    return {
        team_id: (powers[team_id] + deltas[team_id]) * GAME_SHRINK
        for team_id in powers
    }


def _phase2e8_week2_margins(postweek_lookup: dict[str, float], results_path: Path) -> dict[str, float]:
    import pandas as pd

    df = pd.read_parquet(results_path)
    week2 = df[(df["season"] == 2026) & (df["week"] == 2)].copy()
    week2 = week2.sort_values(["gameday", "gametime", "game_id"]).reset_index(drop=True)

    out: dict[str, float] = {}
    for row in week2.itertuples(index=False):
        away_team = normalize_team_id(row.away_team)
        home_team = normalize_team_id(row.home_team)
        out[f"{away_team}@{home_team}"] = model_margin_home(
            home_power=postweek_lookup[home_team],
            away_power=postweek_lookup[away_team],
            hfa=HFA,
        )
    return out


def test_canonical_team_set_has_exactly_32_teams():
    assert len(CANONICAL_NFL_TEAMS) == 32
    assert len(set(CANONICAL_NFL_TEAMS)) == 32


def test_valid_32_team_snapshot_is_accepted():
    validate_snapshot(_snapshot())


def test_missing_team_rejected():
    teams = _teams()[:-1]
    with pytest.raises(ValueError):
        validate_snapshot(_snapshot(teams=teams))


def test_duplicate_team_rejected():
    teams = list(_teams())
    teams[-1] = teams[0]
    with pytest.raises(ValueError):
        validate_snapshot(_snapshot(teams=tuple(teams)))


def test_unknown_team_rejected():
    teams = list(_teams())
    teams[-1] = PowerTeamRating(team_id="XXX", power=0.0)
    snap = PowerSnapshot(
        snapshot_id="preseason-2026",
        snapshot_hash="",
        season=2026,
        through_week=0,
        updater_version="u1",
        methodology_hash="m1",
        source_snapshot_id=None,
        generated_at="2026-09-16T00:00:00+00:00",
        teams=tuple(teams),
    )
    with pytest.raises(ValueError):
        validate_snapshot(snap)


def test_snapshot_hash_unknown_team_raises_value_error_not_key_error():
    teams = list(_teams())
    teams[-1] = PowerTeamRating(team_id="XXX", power=0.0)
    snap = PowerSnapshot(
        snapshot_id="preseason-2026",
        snapshot_hash="",
        season=2026,
        through_week=0,
        updater_version="u1",
        methodology_hash="m1",
        source_snapshot_id=None,
        generated_at="2026-09-16T00:00:00+00:00",
        teams=tuple(teams),
    )

    with pytest.raises(ValueError) as exc_info:
        snapshot_hash(snap)

    assert "Unknown team id" in str(exc_info.value)


def test_non_finite_power_rejected():
    teams = list(_teams())
    teams[0] = PowerTeamRating(team_id=teams[0].team_id, power=float("nan"))
    with pytest.raises(ValueError):
        validate_snapshot(_snapshot(teams=tuple(teams)))


def test_expected_result_calculation():
    result = _result(home_score=1, away_score=0)
    update = apply_single_game_update(home_power_before=0.0, away_power_before=0.5, result=result)

    assert update.expected_home_margin == pytest.approx(1.0)
    assert update.actual_home_margin == pytest.approx(1.0)
    assert update.raw_error == pytest.approx(0.0)
    assert update.clipped_error == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("actual_margin", "expected_error", "expected_clipped"),
    [
        (8, 7.0, 7.0),
        (-6, -7.0, -7.0),
        (15, 14.0, 14.0),
        (-13, -14.0, -14.0),
        (22, 21.0, 21.0),
        (-20, -21.0, -21.0),
        (31, 30.0, 21.0),
        (-29, -30.0, -21.0),
    ],
)
def test_surprise_and_clamp_scenarios(actual_margin: int, expected_error: float, expected_clipped: float):
    result = _result(home_score=max(actual_margin, 0), away_score=max(-actual_margin, 0))
    update = apply_single_game_update(home_power_before=0.0, away_power_before=0.5, result=result)

    assert update.raw_error == pytest.approx(expected_error)
    assert update.clipped_error == pytest.approx(expected_clipped)


def test_tie_game_supported():
    result = _result(home_score=17, away_score=17)
    update = apply_single_game_update(home_power_before=0.0, away_power_before=0.0, result=result)
    assert update.actual_home_margin == 0.0


def test_ordering_by_kickoff_then_game_id():
    snap = _snapshot()
    r1 = _result(game_id="G2", kickoff="2026-09-10T20:20:00+00:00", home_team="ATL", away_team="ARI")
    r2 = _result(game_id="G1", kickoff="2026-09-10T20:20:00+00:00", home_team="BUF", away_team="BAL")
    r3 = _result(game_id="G0", kickoff="2026-09-09T20:20:00+00:00", home_team="CAR", away_team="CHI")

    out = apply_week_results(snapshot=snap, results=(r1, r2, r3), generated_at="2026-09-16T00:00:00+00:00")

    assert [u.game_id for u in out.updates] == ["G0", "G1", "G2"]


def test_duplicate_game_id_rejected():
    snap = _snapshot()
    r1 = _result(game_id="dup", home_team="ATL", away_team="ARI")
    r2 = _result(game_id="dup", home_team="BUF", away_team="BAL")
    with pytest.raises(ValueError):
        apply_week_results(snapshot=snap, results=(r1, r2), generated_at="2026-09-16T00:00:00+00:00")


def test_repeated_team_supported_and_order_invariant():
    snap = _snapshot()
    r1 = _result(
        game_id="g1",
        kickoff="2026-09-10T20:20:00+00:00",
        home_team="ATL",
        away_team="ARI",
        home_score=24,
        away_score=17,
    )
    r2 = _result(
        game_id="g2",
        kickoff="2026-09-11T20:20:00+00:00",
        home_team="BUF",
        away_team="ATL",
        home_score=14,
        away_score=28,
    )

    out_a = apply_week_results(snapshot=snap, results=(r1, r2), generated_at="2026-09-16T00:00:00+00:00")

    # Swap kickoff ordering to force the opposite processing order.
    r1_swapped = _result(
        game_id="g1",
        kickoff="2026-09-12T20:20:00+00:00",
        home_team="ATL",
        away_team="ARI",
        home_score=24,
        away_score=17,
    )
    r2_swapped = _result(
        game_id="g2",
        kickoff="2026-09-09T20:20:00+00:00",
        home_team="BUF",
        away_team="ATL",
        home_score=14,
        away_score=28,
    )
    out_b = apply_week_results(snapshot=snap, results=(r1_swapped, r2_swapped), generated_at="2026-09-16T00:00:00+00:00")

    powers_a = {team.team_id: team.power for team in out_a.snapshot_after.teams}
    powers_b = {team.team_id: team.power for team in out_b.snapshot_after.teams}
    assert set(powers_a.keys()) == set(powers_b.keys())
    for team_id in powers_a:
        assert powers_a[team_id] == pytest.approx(powers_b[team_id], abs=1e-12)


def test_non_string_game_id_fails_before_sort():
    snap = _snapshot()
    bad = FinalGameResult(
        season=2026,
        week=1,
        game_id=123,  # type: ignore[arg-type]
        kickoff_utc="2026-09-10T20:20:00+00:00",
        home_team="ATL",
        away_team="ARI",
        home_score=24,
        away_score=17,
        source_result_version="scores-v1",
    )
    with pytest.raises(ValueError, match="game_id"):
        apply_week_results(snapshot=snap, results=(bad,), generated_at="2026-09-16T00:00:00+00:00")


def test_mixed_malformed_game_id_types_do_not_raise_sorting_type_error():
    snap = _snapshot()
    good = _result(game_id="g2", home_team="BUF", away_team="BAL")
    bad = FinalGameResult(
        season=2026,
        week=1,
        game_id=999,  # type: ignore[arg-type]
        kickoff_utc="2026-09-10T20:20:00+00:00",
        home_team="ATL",
        away_team="ARI",
        home_score=24,
        away_score=17,
        source_result_version="scores-v1",
    )

    with pytest.raises(ValueError, match="game_id"):
        apply_week_results(snapshot=snap, results=(good, bad), generated_at="2026-09-16T00:00:00+00:00")


def test_non_integer_week_fails_intentionally():
    snap = _snapshot()
    bad = FinalGameResult(
        season=2026,
        week="1",  # type: ignore[arg-type]
        game_id="g1",
        kickoff_utc="2026-09-10T20:20:00+00:00",
        home_team="ATL",
        away_team="ARI",
        home_score=24,
        away_score=17,
        source_result_version="scores-v1",
    )
    with pytest.raises(ValueError, match="week must be an integer"):
        apply_week_results(snapshot=snap, results=(bad,), generated_at="2026-09-16T00:00:00+00:00")


def test_bool_week_fails_intentionally():
    snap = _snapshot()
    bad = FinalGameResult(
        season=2026,
        week=True,  # type: ignore[arg-type]
        game_id="g1",
        kickoff_utc="2026-09-10T20:20:00+00:00",
        home_team="ATL",
        away_team="ARI",
        home_score=24,
        away_score=17,
        source_result_version="scores-v1",
    )
    with pytest.raises(ValueError, match="week must be an integer"):
        apply_week_results(snapshot=snap, results=(bad,), generated_at="2026-09-16T00:00:00+00:00")


def test_non_integer_season_fails_intentionally():
    snap = _snapshot()
    bad = FinalGameResult(
        season="2026",  # type: ignore[arg-type]
        week=1,
        game_id="g1",
        kickoff_utc="2026-09-10T20:20:00+00:00",
        home_team="ATL",
        away_team="ARI",
        home_score=24,
        away_score=17,
        source_result_version="scores-v1",
    )
    with pytest.raises(ValueError, match="season must be an integer"):
        apply_week_results(snapshot=snap, results=(bad,), generated_at="2026-09-16T00:00:00+00:00")


def test_snapshot_teams_none_fails_intentionally():
    snap = PowerSnapshot(
        snapshot_id="preseason-2026",
        snapshot_hash="",
        season=2026,
        through_week=0,
        updater_version="u1",
        methodology_hash="m1",
        source_snapshot_id=None,
        generated_at="2026-09-16T00:00:00+00:00",
        teams=None,  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="Snapshot teams must be provided"):
        validate_snapshot(snap)


def test_snapshot_malformed_team_item_fails_intentionally():
    teams = list(_teams())
    teams[0] = {"team_id": "ARI", "power": 0.0}  # type: ignore[assignment]
    snap = PowerSnapshot(
        snapshot_id="preseason-2026",
        snapshot_hash="",
        season=2026,
        through_week=0,
        updater_version="u1",
        methodology_hash="m1",
        source_snapshot_id=None,
        generated_at="2026-09-16T00:00:00+00:00",
        teams=tuple(teams),
    )
    with pytest.raises(ValueError, match="Invalid team entry"):
        validate_snapshot(snap)


def test_missing_or_invalid_score_rejected():
    snap = _snapshot()
    bad = FinalGameResult(
        season=2026,
        week=1,
        game_id="bad",
        kickoff_utc="2026-09-10T20:20:00+00:00",
        home_team="ATL",
        away_team="ARI",
        home_score=-1,
        away_score=17,
        source_result_version="scores-v1",
    )
    with pytest.raises(ValueError):
        apply_week_results(snapshot=snap, results=(bad,), generated_at="2026-09-16T00:00:00+00:00")


def test_bool_score_rejected_intentionally():
    snap = _snapshot()
    bad = FinalGameResult(
        season=2026,
        week=1,
        game_id="bad-bool-score",
        kickoff_utc="2026-09-10T20:20:00+00:00",
        home_team="ATL",
        away_team="ARI",
        home_score=True,  # type: ignore[arg-type]
        away_score=17,
        source_result_version="scores-v1",
    )
    with pytest.raises(ValueError, match="home_score must be an integer"):
        apply_week_results(snapshot=snap, results=(bad,), generated_at="2026-09-16T00:00:00+00:00")


def test_unknown_result_team_rejected_intentionally():
    snap = _snapshot()
    bad = FinalGameResult(
        season=2026,
        week=1,
        game_id="bad-unknown-team",
        kickoff_utc="2026-09-10T20:20:00+00:00",
        home_team="XXX",
        away_team="ARI",
        home_score=24,
        away_score=17,
        source_result_version="scores-v1",
    )
    with pytest.raises(ValueError, match="Unknown team id"):
        apply_week_results(snapshot=snap, results=(bad,), generated_at="2026-09-16T00:00:00+00:00")


def test_same_home_away_team_rejected_intentionally():
    snap = _snapshot()
    bad = FinalGameResult(
        season=2026,
        week=1,
        game_id="bad-same-team",
        kickoff_utc="2026-09-10T20:20:00+00:00",
        home_team="ATL",
        away_team="ATL",
        home_score=24,
        away_score=17,
        source_result_version="scores-v1",
    )
    with pytest.raises(ValueError, match="cannot match"):
        apply_week_results(snapshot=snap, results=(bad,), generated_at="2026-09-16T00:00:00+00:00")


def test_non_participating_team_receives_weekly_shrink_once():
    snap = _snapshot()
    before = {t.team_id: t.power for t in snap.teams}
    r = _result(game_id="g1", home_team="ATL", away_team="ARI", home_score=24, away_score=17)

    out = apply_week_results(snapshot=snap, results=(r,), generated_at="2026-09-16T00:00:00+00:00")
    after = {t.team_id: t.power for t in out.snapshot_after.teams}

    assert after["BUF"] == pytest.approx(before["BUF"] * GAME_SHRINK)
    assert after["ARI"] != pytest.approx(before["ARI"])
    assert after["ATL"] != pytest.approx(before["ATL"])


def test_repeated_team_adjustments_aggregate_before_single_shrink():
    snap = _snapshot()
    before = {t.team_id: t.power for t in snap.teams}
    r1 = _result(
        game_id="g1",
        kickoff="2026-09-10T20:20:00+00:00",
        home_team="ATL",
        away_team="ARI",
        home_score=24,
        away_score=17,
    )
    r2 = _result(
        game_id="g2",
        kickoff="2026-09-11T20:20:00+00:00",
        home_team="BUF",
        away_team="ATL",
        home_score=14,
        away_score=28,
    )

    out = apply_week_results(snapshot=snap, results=(r1, r2), generated_at="2026-09-16T00:00:00+00:00")
    after = {t.team_id: t.power for t in out.snapshot_after.teams}

    atl_total_adjustment = sum(
        update.home_adjustment
        for update in out.updates
        if update.home_team == "ATL"
    ) + sum(
        update.away_adjustment
        for update in out.updates
        if update.away_team == "ATL"
    )
    expected_atl = (before["ATL"] + atl_total_adjustment) * GAME_SHRINK
    assert after["ATL"] == pytest.approx(expected_atl, abs=1e-12)


def test_phase2e8_week1_shadow_parity_if_artifacts_available():
    if not _phase2e8_enabled():
        _phase2e8_skip()

    baseline_path = _phase2e8_env_path(_PHASE2E8_BASELINE_ENV)
    results_path = _phase2e8_env_path(_PHASE2E8_RESULTS_ENV)
    target_path = _phase2e8_env_path(_PHASE2E8_TARGET_ENV)

    preweek_snapshot = _phase2e8_preweek_snapshot_from_csv(baseline_path)
    results = _phase2e8_results_from_parquet(results_path)
    target_payload = json.loads(target_path.read_text(encoding="utf-8"))

    out = apply_week_results(
        snapshot=preweek_snapshot,
        results=results,
        generated_at=str(target_payload["generated_at"]),
        updater_version=str(target_payload["updater_version"]),
    )

    independent_reference = _phase2e8_independent_reference(preweek_snapshot, results)
    actual = {team.team_id: float(team.power) for team in out.snapshot_after.teams}
    expected_shadow = {team["team_id"]: float(team["power"]) for team in target_payload["teams"]}

    assert set(independent_reference.keys()) == set(actual.keys()) == set(expected_shadow.keys())

    max_abs_diff = max(abs(actual[team_id] - independent_reference[team_id]) for team_id in actual)
    assert max_abs_diff <= 1e-12

    max_shadow_diff = max(abs(actual[team_id] - expected_shadow[team_id]) for team_id in actual)
    assert max_shadow_diff <= 1e-12

    week2_margins = _phase2e8_week2_margins(actual, results_path)
    assert set(week2_margins.keys()) == set(_PHASE2E8_WEEK2_MARGIN_REFERENCE.keys())
    for matchup, reference_margin in _PHASE2E8_WEEK2_MARGIN_REFERENCE.items():
        assert week2_margins[matchup] == pytest.approx(reference_margin, abs=1e-6)


def test_repeated_identical_run_produces_identical_output():
    snap = _snapshot()
    r1 = _result(game_id="g1", home_team="ATL", away_team="ARI", home_score=24, away_score=17)
    r2 = _result(game_id="g2", home_team="BUF", away_team="BAL", home_score=14, away_score=10)

    out1 = apply_week_results(
        snapshot=snap,
        results=(r1, r2),
        generated_at="2026-09-16T00:00:00+00:00",
    )
    out2 = apply_week_results(
        snapshot=snap,
        results=(r1, r2),
        generated_at="2026-09-16T00:00:00+00:00",
    )

    assert out1.snapshot_after.snapshot_hash == out2.snapshot_after.snapshot_hash
    assert out1.snapshot_after.teams == out2.snapshot_after.teams
    assert out1.updates == out2.updates


def test_methodology_hash_is_deterministic():
    h1 = methodology_hash(methodology=__import__("app.services.power_engine.methodology", fromlist=["FROZEN_METHODOLOGY"]).FROZEN_METHODOLOGY, updater_version="v1")
    h2 = methodology_hash(methodology=__import__("app.services.power_engine.methodology", fromlist=["FROZEN_METHODOLOGY"]).FROZEN_METHODOLOGY, updater_version="v1")
    assert h1 == h2


def test_snapshot_hash_independent_of_input_team_ordering():
    teams = _teams()
    reverse_teams = tuple(reversed(teams))
    snap1 = _snapshot(teams=teams)
    snap2 = _snapshot(teams=reverse_teams)
    assert snapshot_hash(snap1) == snapshot_hash(snap2)


def test_source_snapshot_not_mutated():
    snap = _snapshot(through_week=0)
    before = tuple((t.team_id, t.power) for t in snap.teams)
    result = _result(game_id="g1", home_team="ATL", away_team="ARI", home_score=24, away_score=17)

    _ = apply_week_results(snapshot=snap, results=(result,), generated_at="2026-09-16T00:00:00+00:00")

    assert snap.through_week == 0
    assert tuple((t.team_id, t.power) for t in snap.teams) == before


def test_future_margin_identity_after_update():
    result = _result(home_score=31, away_score=20)
    update = apply_single_game_update(home_power_before=2.25, away_power_before=-1.5, result=result)
    margin = update.home_power_after - update.away_power_after + HFA
    assert math.isfinite(margin)


def test_frozen_constants_match_contract():
    assert HFA == 1.5
    assert K == 0.07
    assert ERROR_CAP == 21.0
    assert GAME_SHRINK == 0.985
