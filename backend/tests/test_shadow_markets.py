from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.services import shadow_markets


def _seed_run_and_candidate(
    db_path: Path,
    *,
    run_id: str,
    season: int,
    week: int,
    candidate_id: str,
    market_family: str,
    market_key: str,
    side: str,
    period: str,
    line: float | None,
    price: float,
    commence_time: str = "",
) -> None:
    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        INSERT INTO shadow_candidate_runs (
            run_id, created_at_utc, season, week,
            source_snapshot_id, source_market_timestamp,
            candidate_count, payload_hash, canonical_payload
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            run_id,
            "2026-08-18T00:00:00+00:00",
            season,
            week,
            "src-snap",
            "2026-08-18T00:00:00+00:00",
            1,
            "hash-run",
            "{}",
        ],
    )

    values = [
        run_id,
        candidate_id,
        "2026-08-18T00:00:00+00:00",
        season,
        week,
        "2026_01_AWAY_HOME",
        commence_time,
        market_family,
        market_key,
        period,
        "HOME" if side == "home" else ("OVER 45.0" if side == "over" else "AWAY"),
        side,
        "HOME" if side in {"home", "away"} else None,
        line,
        "DraftKings",
        price,
        0.55,
        0.56,
        0.52,
        0.51,
        0.04,
        0.05,
        0.0 if market_family == "MONEYLINE" else 0.02,
        0.44,
        0.03,
        "model-v1",
        "engine-v1",
        "cal-v1",
        "rank-v1",
        "qual-v1",
        "git-hash",
        "2026-08-18T00:00:00+00:00",
        "odds-snap-id",
        1,
        1,
        "QUALIFIED",
    ]

    con.execute(
        f"""
        INSERT INTO shadow_candidates (
            run_id, candidate_id, created_at_utc,
            season, week, event_id, commence_time,
            market_family, market_key, period,
            selection, side, team_code,
            line, sportsbook, american_price,
            raw_model_probability, calibrated_probability,
            market_implied_probability, market_no_vig_probability,
            raw_edge, calibrated_edge, push_probability, loss_probability, current_ev,
            model_version, probability_engine_version, calibration_version,
            ranking_version, qualification_version, git_commit_hash,
            market_snapshot_timestamp, source_odds_snapshot_id,
            market_rank, week_rank, qualification_status
        ) VALUES ({','.join(['?'] * len(values))})
        """,
        values,
    )
    con.commit()
    con.close()


@pytest.fixture
def shadow_db(monkeypatch, tmp_path):
    db = tmp_path / "shadow_test.sqlite"
    monkeypatch.setattr(shadow_markets, "_DB_PATH", db)
    shadow_markets._ensure_schema()
    return db


def test_shadow_snapshot_immutability_and_duplicate_protection(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-1",
        season=2026,
        week=1,
        candidate_id="cand-1",
        market_family="MONEYLINE",
        market_key="moneyline",
        side="home",
        period="FULL_GAME",
        line=None,
        price=-150,
    )

    first = shadow_markets.publish_shadow_snapshot(run_id="run-1", is_official=False)
    second = shadow_markets.publish_shadow_snapshot(run_id="run-1", is_official=False)

    assert first["created"] is True
    assert second["created"] is False
    assert first["shadowSnapshotId"] == second["shadowSnapshotId"]

    con = sqlite3.connect(str(shadow_db))
    row = con.execute("SELECT COUNT(*) FROM shadow_publication_items").fetchone()
    con.close()
    assert int(row[0]) == 1


def test_duplicate_official_snapshot_protection(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-2",
        season=2026,
        week=2,
        candidate_id="cand-2",
        market_family="TOTAL",
        market_key="total",
        side="over",
        period="FULL_GAME",
        line=45.0,
        price=-110,
    )

    created = shadow_markets.publish_shadow_snapshot(run_id="run-2", is_official=True)
    assert created["created"] is True

    with pytest.raises(ValueError):
        shadow_markets.publish_shadow_snapshot(run_id="run-2", is_official=True)


def test_moneyline_outcome_settlement_and_recorded_price_pl(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-3",
        season=2026,
        week=3,
        candidate_id="cand-3",
        market_family="MONEYLINE",
        market_key="moneyline",
        side="home",
        period="FULL_GAME",
        line=None,
        price=-150,
    )
    pub = shadow_markets.publish_shadow_snapshot(run_id="run-3", is_official=False)

    def _scores(_: str):
        return {"finalAwayScore": 17, "finalHomeScore": 24}

    out = shadow_markets.append_shadow_outcomes(fetch_scores_fn=_scores)
    assert out["appended"] == 1

    con = sqlite3.connect(str(shadow_db))
    row = con.execute(
        "SELECT result, profit_per_dollar, shadow_snapshot_id FROM shadow_outcomes WHERE candidate_id = ?",
        ["cand-3"],
    ).fetchone()
    con.close()

    assert row is not None
    assert row[0] == "WIN"
    assert abs(float(row[1]) - (100.0 / 150.0)) < 1e-9
    assert row[2] == pub["shadowSnapshotId"]


def test_total_outcome_settlement_and_push(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-4",
        season=2026,
        week=4,
        candidate_id="cand-4",
        market_family="TOTAL",
        market_key="total",
        side="over",
        period="FULL_GAME",
        line=45.0,
        price=-110,
    )
    shadow_markets.publish_shadow_snapshot(run_id="run-4", is_official=False)

    def _scores(_: str):
        return {"finalAwayScore": 21, "finalHomeScore": 24}  # total 45 push

    out = shadow_markets.append_shadow_outcomes(fetch_scores_fn=_scores)
    assert out["appended"] == 1

    con = sqlite3.connect(str(shadow_db))
    row = con.execute(
        "SELECT result, profit_per_dollar FROM shadow_outcomes WHERE candidate_id = ?",
        ["cand-4"],
    ).fetchone()
    con.close()

    assert row is not None
    assert row[0] == "PUSH"
    assert float(row[1]) == 0.0


def test_market_and_period_separation(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-5",
        season=2026,
        week=5,
        candidate_id="cand-5a",
        market_family="MONEYLINE",
        market_key="moneyline",
        side="away",
        period="FULL_GAME",
        line=None,
        price=130,
    )
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-6",
        season=2026,
        week=5,
        candidate_id="cand-5b",
        market_family="TOTAL",
        market_key="total",
        side="under",
        period="FIRST_HALF",
        line=23.5,
        price=-105,
    )

    con = sqlite3.connect(str(shadow_db))
    rows = con.execute("SELECT market_family, period FROM shadow_candidates ORDER BY candidate_id").fetchall()
    con.close()

    assert rows[0][0] == "MONEYLINE"
    assert rows[0][1] == "FULL_GAME"
    assert rows[1][0] == "TOTAL"
    assert rows[1][1] == "FIRST_HALF"


def test_shadow_path_does_not_touch_production_sia3_tables(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-7",
        season=2026,
        week=7,
        candidate_id="cand-7",
        market_family="MONEYLINE",
        market_key="moneyline",
        side="home",
        period="FULL_GAME",
        line=None,
        price=-120,
    )
    shadow_markets.publish_shadow_snapshot(run_id="run-7", is_official=False)

    con = sqlite3.connect(str(shadow_db))
    # Production ledger tables should remain untouched by shadow operations.
    decision_ledger_exists = con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='decision_ledger'"
    ).fetchone()[0]
    pub_exists = con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='sia3_publications'"
    ).fetchone()[0]
    con.close()

    assert int(decision_ledger_exists) == 0
    assert int(pub_exists) == 0
