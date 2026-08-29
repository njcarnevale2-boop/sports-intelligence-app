from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
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


def _seed_prospective_snapshot(
    db_path: Path,
    *,
    snapshot_id: str,
    event_id: str,
    market_family: str,
    market_key: str,
    state_label: str,
    side: str,
    selection: str,
    line: float | None,
    price: float,
    sportsbook: str,
    book_coverage_count: int,
    market_no_vig_probability: float | None,
) -> None:
    con = sqlite3.connect(str(db_path))
    placeholders = ",".join(["?"] * 26)
    con.execute(
        f"""
        INSERT INTO prospective_market_snapshots (
            snapshot_id, captured_at_utc,
            season, week, event_id,
            market_family, market_key, phase, period, state_label,
            team_code, selection, side, line, price, sportsbook,
            book_coverage_count, market_no_vig_probability,
            production_eligible, cross_market_comparable,
            market_validation_status, model_state, shadow_recommendations,
            payload_hash, canonical_payload, idempotency_key
        ) VALUES ({placeholders})
        """,
        [
            snapshot_id,
            "2026-08-18T00:00:00+00:00",
            2026,
            38,
            event_id,
            market_family,
            market_key,
            "PREGAME",
            "FULL_GAME",
            state_label,
            None,
            selection,
            side,
            line,
            price,
            sportsbook,
            book_coverage_count,
            market_no_vig_probability,
            0,
            0,
            "AVAILABLE_TWO_SIDED_MARKET" if market_no_vig_probability is not None else "UNAVAILABLE_TWO_SIDED_MARKET",
            "RESEARCH_ONLY",
            "DISABLED",
            f"hash-{snapshot_id}",
            f"canonical-{snapshot_id}",
            f"idem-{snapshot_id}",
        ],
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
        commence_time="2026-09-20T17:00:00+00:00",
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
        commence_time="2026-09-20T17:00:00+00:00",
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


def test_spread_outcome_settlement_win_loss_push(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-s-1",
        season=2026,
        week=8,
        candidate_id="cand-s-win",
        market_family="SPREAD",
        market_key="spread",
        side="away",
        period="FULL_GAME",
        line=3.0,
        price=-110,
    )
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-s-2",
        season=2026,
        week=8,
        candidate_id="cand-s-loss",
        market_family="SPREAD",
        market_key="spread",
        side="away",
        period="FULL_GAME",
        line=3.0,
        price=-110,
    )
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-s-3",
        season=2026,
        week=8,
        candidate_id="cand-s-push",
        market_family="SPREAD",
        market_key="spread",
        side="away",
        period="FULL_GAME",
        line=3.0,
        price=-110,
    )

    shadow_markets.publish_shadow_snapshot(run_id="run-s-1", is_official=False)
    shadow_markets.publish_shadow_snapshot(run_id="run-s-2", is_official=False)
    shadow_markets.publish_shadow_snapshot(run_id="run-s-3", is_official=False)

    def _scores(event_id: str):
        if event_id == "2026_01_AWAY_HOME":
            return {"finalAwayScore": 20, "finalHomeScore": 17}
        return None

    # WIN for away +3
    out = shadow_markets.append_shadow_outcomes(fetch_scores_fn=_scores)
    assert out["appended"] >= 1

    con = sqlite3.connect(str(shadow_db))
    row = con.execute(
        "SELECT result FROM shadow_outcomes WHERE candidate_id = ?",
        ["cand-s-win"],
    ).fetchone()
    con.close()
    assert row is not None
    assert row[0] == "WIN"


def test_spread_outcome_settlement_loss(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-s-loss",
        season=2026,
        week=9,
        candidate_id="cand-s-loss-only",
        market_family="SPREAD",
        market_key="spread",
        side="away",
        period="FULL_GAME",
        line=3.0,
        price=-110,
    )
    shadow_markets.publish_shadow_snapshot(run_id="run-s-loss", is_official=False)

    out = shadow_markets.append_shadow_outcomes(
        fetch_scores_fn=lambda _: {"finalAwayScore": 14, "finalHomeScore": 20}
    )
    assert out["appended"] == 1

    con = sqlite3.connect(str(shadow_db))
    row = con.execute(
        "SELECT result FROM shadow_outcomes WHERE candidate_id = ?",
        ["cand-s-loss-only"],
    ).fetchone()
    con.close()
    assert row is not None
    assert row[0] == "LOSS"


def test_spread_outcome_settlement_push(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-s-push",
        season=2026,
        week=10,
        candidate_id="cand-s-push-only",
        market_family="SPREAD",
        market_key="spread",
        side="away",
        period="FULL_GAME",
        line=3.0,
        price=-110,
    )
    shadow_markets.publish_shadow_snapshot(run_id="run-s-push", is_official=False)

    out = shadow_markets.append_shadow_outcomes(
        fetch_scores_fn=lambda _: {"finalAwayScore": 17, "finalHomeScore": 20}
    )
    assert out["appended"] == 1

    con = sqlite3.connect(str(shadow_db))
    row = con.execute(
        "SELECT result, profit_per_dollar FROM shadow_outcomes WHERE candidate_id = ?",
        ["cand-s-push-only"],
    ).fetchone()
    con.close()
    assert row is not None
    assert row[0] == "PUSH"
    assert float(row[1]) == 0.0


def test_build_shadow_boards_creates_three_market_candidates(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "spread",
                "side": "away",
                "latest_point": 3.0,
                "latest_price": -110,
                "sportsbook": "DraftKings",
                "last_seen": "2026-09-10T16:00:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
                "model_prob": 0.55,
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "spread",
                "side": "home",
                "latest_point": -3.0,
                "latest_price": -110,
                "sportsbook": "DraftKings",
                "last_seen": "2026-09-10T16:00:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
                "model_prob": 0.45,
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "moneyline",
                "side": "away",
                "latest_point": None,
                "latest_price": 130,
                "sportsbook": "DraftKings",
                "last_seen": "2026-09-10T16:00:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "moneyline",
                "side": "home",
                "latest_point": None,
                "latest_price": -150,
                "sportsbook": "DraftKings",
                "last_seen": "2026-09-10T16:00:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "total",
                "side": "over",
                "latest_point": 45.5,
                "latest_price": -110,
                "sportsbook": "DraftKings",
                "last_seen": "2026-09-10T16:00:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "total",
                "side": "under",
                "latest_point": 45.5,
                "latest_price": -110,
                "sportsbook": "DraftKings",
                "last_seen": "2026-09-10T16:00:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
        ]
    )
    proj = {
        "2026_01_AWAY_HOME": pd.Series(
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "model_margin_home": -2.0,
                "model_total_baseline": 45.2,
            }
        )
    }

    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: proj)

    out = shadow_markets.build_shadow_boards(week=1, season=2026)
    assert out["spreadCount"] >= 1
    assert out["moneylineCount"] >= 1
    assert out["totalCount"] >= 1

    con = sqlite3.connect(str(shadow_db))
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT market_family, production_eligible, cross_market_comparable FROM shadow_candidates").fetchall()
    con.close()
    families = {str(r["market_family"]) for r in rows}
    assert families == {"SPREAD", "MONEYLINE", "TOTAL"}

    spread_rows = [r for r in rows if str(r["market_family"]) == "SPREAD"]
    assert spread_rows
    assert all(int(r["production_eligible"]) == 1 for r in spread_rows)
    assert all(int(r["cross_market_comparable"]) == 0 for r in spread_rows)


def test_shadow_candidate_identity_unique_across_market_families(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {"api_event_id": "2026_02_A_B", "commence_time": "2026-09-17T17:00:00+00:00", "market": "spread", "side": "away", "latest_point": 3.0, "latest_price": -110, "sportsbook": "DraftKings", "last_seen": "2026-09-17T16:00:00+00:00", "home_team": "B", "away_team": "A", "model_prob": 0.56},
            {"api_event_id": "2026_02_A_B", "commence_time": "2026-09-17T17:00:00+00:00", "market": "spread", "side": "home", "latest_point": -3.0, "latest_price": -110, "sportsbook": "DraftKings", "last_seen": "2026-09-17T16:00:00+00:00", "home_team": "B", "away_team": "A", "model_prob": 0.44},
            {"api_event_id": "2026_02_A_B", "commence_time": "2026-09-17T17:00:00+00:00", "market": "moneyline", "side": "away", "latest_point": None, "latest_price": 130, "sportsbook": "DraftKings", "last_seen": "2026-09-17T16:00:00+00:00", "home_team": "B", "away_team": "A"},
            {"api_event_id": "2026_02_A_B", "commence_time": "2026-09-17T17:00:00+00:00", "market": "moneyline", "side": "home", "latest_point": None, "latest_price": -150, "sportsbook": "DraftKings", "last_seen": "2026-09-17T16:00:00+00:00", "home_team": "B", "away_team": "A"},
            {"api_event_id": "2026_02_A_B", "commence_time": "2026-09-17T17:00:00+00:00", "market": "total", "side": "over", "latest_point": 47.5, "latest_price": -110, "sportsbook": "DraftKings", "last_seen": "2026-09-17T16:00:00+00:00", "home_team": "B", "away_team": "A"},
            {"api_event_id": "2026_02_A_B", "commence_time": "2026-09-17T17:00:00+00:00", "market": "total", "side": "under", "latest_point": 47.5, "latest_price": -110, "sportsbook": "DraftKings", "last_seen": "2026-09-17T16:00:00+00:00", "home_team": "B", "away_team": "A"},
        ]
    )
    proj = {"2026_02_A_B": pd.Series({"api_event_id": "2026_02_A_B", "model_margin_home": -2.0, "model_total_baseline": 47.3})}

    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: proj)
    out = shadow_markets.build_shadow_boards(week=2, season=2026)
    assert out["candidateCount"] >= 3

    con = sqlite3.connect(str(shadow_db))
    ids = [r[0] for r in con.execute("SELECT candidate_id FROM shadow_candidates").fetchall()]
    con.close()
    assert len(ids) == len(set(ids))


def test_line_clv_sign_semantics() -> None:
    assert shadow_markets._line_clv_points("SPREAD", "away", 3.0, 2.5) > 0
    assert shadow_markets._line_clv_points("SPREAD", "away", 3.0, 3.5) < 0
    assert shadow_markets._line_clv_points("TOTAL", "over", 45.5, 46.5) > 0
    assert shadow_markets._line_clv_points("TOTAL", "under", 45.5, 44.5) > 0


def test_two_sided_no_vig_moneyline_and_single_sided_rejection(monkeypatch, tmp_path):
    import duckdb  # type: ignore

    model_root = tmp_path / "model"
    db_dir = model_root / "database"
    db_dir.mkdir(parents=True)
    db = db_dir / "nfl_model.duckdb"

    con = duckdb.connect(str(db))
    con.execute(
        """
        CREATE TABLE odds_snapshots (
            api_event_id VARCHAR,
            bookmaker_key VARCHAR,
            market_key VARCHAR,
            outcome_code VARCHAR,
            fetched_at TIMESTAMP,
            point DOUBLE,
            price DOUBLE
        )
        """
    )
    con.execute(
        """
        INSERT INTO odds_snapshots VALUES
        ('evt-1','DraftKings','h2h','home','2026-09-10 16:50:00',NULL,-150),
        ('evt-1','DraftKings','h2h','away','2026-09-10 16:50:00',NULL,130)
        """
    )
    con.close()

    monkeypatch.setattr(shadow_markets, "MODEL_ROOT", model_root)
    kickoff = pd.Timestamp("2026-09-10T17:00:00+00:00").to_pydatetime()
    p, status = shadow_markets._two_sided_closing_no_vig(
        event_id="evt-1",
        sportsbook="DraftKings",
        market_family="MONEYLINE",
        side="away",
        kickoff=kickoff,
        recommended_line=None,
    )
    assert status == "AVAILABLE_TWO_SIDED_MARKET"
    assert p is not None

    # Remove away side => single-sided should be rejected.
    con = duckdb.connect(str(db))
    con.execute("DELETE FROM odds_snapshots WHERE outcome_code = 'away'")
    con.close()
    p2, status2 = shadow_markets._two_sided_closing_no_vig(
        event_id="evt-1",
        sportsbook="DraftKings",
        market_family="MONEYLINE",
        side="home",
        kickoff=kickoff,
        recommended_line=None,
    )
    assert p2 is None
    assert status2 == "UNAVAILABLE_TWO_SIDED_MARKET"


def test_two_sided_no_vig_total_mismatch_rejected(monkeypatch, tmp_path):
    import duckdb  # type: ignore

    model_root = tmp_path / "model2"
    db_dir = model_root / "database"
    db_dir.mkdir(parents=True)
    db = db_dir / "nfl_model.duckdb"

    con = duckdb.connect(str(db))
    con.execute(
        """
        CREATE TABLE odds_snapshots (
            api_event_id VARCHAR,
            bookmaker_key VARCHAR,
            market_key VARCHAR,
            outcome_code VARCHAR,
            fetched_at TIMESTAMP,
            point DOUBLE,
            price DOUBLE
        )
        """
    )
    con.execute(
        """
        INSERT INTO odds_snapshots VALUES
        ('evt-t','DraftKings','totals','over','2026-09-10 16:50:00',47.5,-110),
        ('evt-t','DraftKings','totals','under','2026-09-10 16:50:00',46.5,-110)
        """
    )
    con.close()

    monkeypatch.setattr(shadow_markets, "MODEL_ROOT", model_root)
    kickoff = pd.Timestamp("2026-09-10T17:00:00+00:00").to_pydatetime()
    p, status = shadow_markets._two_sided_closing_no_vig(
        event_id="evt-t",
        sportsbook="DraftKings",
        market_family="TOTAL",
        side="over",
        kickoff=kickoff,
        recommended_line=47.5,
    )
    assert p is None
    assert status in {"MISMATCHED_TOTAL_POINTS", "UNAVAILABLE_TWO_SIDED_MARKET"}


def test_moneyline_price_clv_signs_with_two_sided_no_vig(monkeypatch, shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-clv-ml-pos",
        season=2026,
        week=11,
        candidate_id="cand-ml-clv-pos",
        market_family="MONEYLINE",
        market_key="moneyline",
        side="away",
        period="FULL_GAME",
        line=None,
        price=130,
        commence_time="2026-09-13T17:00:00+00:00",
    )
    shadow_markets.publish_shadow_snapshot(run_id="run-clv-ml-pos", is_official=False)

    class _Close:
        closing_status = "AVAILABLE"
        closing_point = None
        closing_price = 120.0
        closing_timestamp = pd.Timestamp("2026-09-13T16:58:00+00:00").to_pydatetime()

    monkeypatch.setattr(shadow_markets, "get_closing_line", lambda **_: _Close())
    monkeypatch.setattr(shadow_markets, "_two_sided_closing_no_vig", lambda **_: (0.58, "AVAILABLE_TWO_SIDED_MARKET"))

    out = shadow_markets.append_shadow_outcomes(fetch_scores_fn=lambda _: {"finalAwayScore": 24, "finalHomeScore": 17})
    assert out["appended"] == 1

    con = sqlite3.connect(str(shadow_db))
    row = con.execute(
        "SELECT price_clv_probability FROM shadow_outcomes WHERE candidate_id = ?",
        ["cand-ml-clv-pos"],
    ).fetchone()
    con.close()
    assert row is not None
    assert float(row[0]) > 0

    _seed_run_and_candidate(
        shadow_db,
        run_id="run-clv-ml-neg",
        season=2026,
        week=11,
        candidate_id="cand-ml-clv-neg",
        market_family="MONEYLINE",
        market_key="moneyline",
        side="away",
        period="FULL_GAME",
        line=None,
        price=130,
        commence_time="2026-09-13T17:00:00+00:00",
    )
    shadow_markets.publish_shadow_snapshot(run_id="run-clv-ml-neg", is_official=False)
    monkeypatch.setattr(shadow_markets, "_two_sided_closing_no_vig", lambda **_: (0.45, "AVAILABLE_TWO_SIDED_MARKET"))

    out2 = shadow_markets.append_shadow_outcomes(fetch_scores_fn=lambda _: {"finalAwayScore": 24, "finalHomeScore": 17})
    assert out2["appended"] == 1
    con = sqlite3.connect(str(shadow_db))
    row2 = con.execute(
        "SELECT price_clv_probability FROM shadow_outcomes WHERE candidate_id = ?",
        ["cand-ml-clv-neg"],
    ).fetchone()
    con.close()
    assert row2 is not None
    assert float(row2[0]) < 0


def test_total_price_and_line_clv_signs(monkeypatch, shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-clv-total",
        season=2026,
        week=12,
        candidate_id="cand-total-clv",
        market_family="TOTAL",
        market_key="total",
        side="over",
        period="FULL_GAME",
        line=45.5,
        price=-110,
        commence_time="2026-09-20T17:00:00+00:00",
    )
    shadow_markets.publish_shadow_snapshot(run_id="run-clv-total", is_official=False)

    class _Close:
        closing_status = "AVAILABLE"
        closing_point = 46.5
        closing_price = -115.0
        closing_timestamp = pd.Timestamp("2026-09-20T16:58:00+00:00").to_pydatetime()

    monkeypatch.setattr(shadow_markets, "get_closing_line", lambda **_: _Close())
    monkeypatch.setattr(shadow_markets, "_two_sided_closing_no_vig", lambda **_: (0.57, "AVAILABLE_TWO_SIDED_MARKET"))

    out = shadow_markets.append_shadow_outcomes(fetch_scores_fn=lambda _: {"finalAwayScore": 24, "finalHomeScore": 24})
    assert out["appended"] == 1

    con = sqlite3.connect(str(shadow_db))
    row = con.execute(
        "SELECT line_clv_points, price_clv_probability FROM shadow_outcomes WHERE candidate_id = ?",
        ["cand-total-clv"],
    ).fetchone()
    con.close()
    assert row is not None
    assert float(row[0]) > 0
    assert float(row[1]) > 0


def test_shadow_report_includes_spread_and_global_rank_fields(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-report",
        season=2026,
        week=13,
        candidate_id="cand-report-spread",
        market_family="SPREAD",
        market_key="spread",
        side="away",
        period="FULL_GAME",
        line=3.0,
        price=-110,
    )
    shadow_markets.publish_shadow_snapshot(run_id="run-report", is_official=False)
    shadow_markets.append_shadow_outcomes(fetch_scores_fn=lambda _: {"finalAwayScore": 24, "finalHomeScore": 20})

    report = shadow_markets.shadow_performance_report()
    assert "SPREAD" in report["markets"]
    spread = report["markets"]["SPREAD"]
    assert "byGlobalResearchRank" in spread
    assert "globalResearchTopRanksTracked" in spread


def test_moneyline_total_progress_report_and_gates(monkeypatch, shadow_db):
    # Moneyline side 1.
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-ml-home",
        season=2026,
        week=15,
        candidate_id="cand-ml-home",
        market_family="MONEYLINE",
        market_key="moneyline",
        side="home",
        period="FULL_GAME",
        line=None,
        price=-150,
        commence_time="2026-09-20T17:00:00+00:00",
    )
    # Moneyline side 2.
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-ml-away",
        season=2026,
        week=15,
        candidate_id="cand-ml-away",
        market_family="MONEYLINE",
        market_key="moneyline",
        side="away",
        period="FULL_GAME",
        line=None,
        price=130,
        commence_time="2026-09-20T17:00:00+00:00",
    )
    # Total over/under pair.
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-total-over",
        season=2026,
        week=15,
        candidate_id="cand-total-over",
        market_family="TOTAL",
        market_key="total",
        side="over",
        period="FULL_GAME",
        line=45.5,
        price=-110,
        commence_time="2026-09-20T17:00:00+00:00",
    )
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-total-under",
        season=2026,
        week=15,
        candidate_id="cand-total-under",
        market_family="TOTAL",
        market_key="total",
        side="under",
        period="FULL_GAME",
        line=45.5,
        price=-110,
        commence_time="2026-09-20T17:00:00+00:00",
    )

    shadow_markets.publish_shadow_snapshot(run_id="run-ml-home", is_official=False)
    shadow_markets.publish_shadow_snapshot(run_id="run-ml-away", is_official=False)
    shadow_markets.publish_shadow_snapshot(run_id="run-total-over", is_official=False)
    shadow_markets.publish_shadow_snapshot(run_id="run-total-under", is_official=False)

    class _Close:
        def __init__(self, closing_point, closing_price):
            self.closing_status = "AVAILABLE"
            self.closing_point = closing_point
            self.closing_price = closing_price
            self.closing_timestamp = pd.Timestamp("2026-09-20T16:58:00+00:00").to_pydatetime()

    def _get_closing_line(**kwargs):
        market_key = str(kwargs.get("market_key") or "")
        outcome_code = str(kwargs.get("outcome_code") or "").lower()
        if market_key == "h2h":
            return _Close(None, -170.0 if outcome_code == "home" else 120.0)
        if market_key == "totals":
            return _Close(46.5 if outcome_code == "over" else 44.5, -115.0)
        return _Close(None, None)

    monkeypatch.setattr(shadow_markets, "get_closing_line", _get_closing_line)
    monkeypatch.setattr(shadow_markets, "_two_sided_closing_no_vig", lambda **_: (0.58, "AVAILABLE_TWO_SIDED_MARKET"))

    shadow_markets.append_shadow_outcomes(
        fetch_scores_fn=lambda _: {
            "finalAwayScore": 21,
            "finalHomeScore": 28,
        }
    )

    _seed_prospective_snapshot(
        shadow_db,
        snapshot_id="snap-ml-opening",
        event_id="evt-ml",
        market_family="MONEYLINE",
        market_key="moneyline",
        state_label="OPENING",
        side="home",
        selection="HOME",
        line=None,
        price=-150,
        sportsbook="DraftKings",
        book_coverage_count=4,
        market_no_vig_probability=0.58,
    )
    _seed_prospective_snapshot(
        shadow_db,
        snapshot_id="snap-ml-current",
        event_id="evt-ml",
        market_family="MONEYLINE",
        market_key="moneyline",
        state_label="CURRENT",
        side="home",
        selection="HOME",
        line=None,
        price=-145,
        sportsbook="DraftKings",
        book_coverage_count=5,
        market_no_vig_probability=0.56,
    )
    _seed_prospective_snapshot(
        shadow_db,
        snapshot_id="snap-ml-closing",
        event_id="evt-ml",
        market_family="MONEYLINE",
        market_key="moneyline",
        state_label="CLOSING",
        side="home",
        selection="HOME",
        line=None,
        price=-140,
        sportsbook="DraftKings",
        book_coverage_count=5,
        market_no_vig_probability=0.55,
    )

    _seed_prospective_snapshot(
        shadow_db,
        snapshot_id="snap-total-opening",
        event_id="evt-total",
        market_family="TOTAL",
        market_key="total",
        state_label="OPENING",
        side="over",
        selection="OVER 45.5",
        line=45.5,
        price=-110,
        sportsbook="DraftKings",
        book_coverage_count=5,
        market_no_vig_probability=0.51,
    )
    _seed_prospective_snapshot(
        shadow_db,
        snapshot_id="snap-total-current",
        event_id="evt-total",
        market_family="TOTAL",
        market_key="total",
        state_label="CURRENT",
        side="over",
        selection="OVER 45.5",
        line=45.5,
        price=-108,
        sportsbook="DraftKings",
        book_coverage_count=4,
        market_no_vig_probability=0.505,
    )
    _seed_prospective_snapshot(
        shadow_db,
        snapshot_id="snap-total-closing",
        event_id="evt-total",
        market_family="TOTAL",
        market_key="total",
        state_label="CLOSING",
        side="over",
        selection="OVER 45.5",
        line=46.5,
        price=-115,
        sportsbook="DraftKings",
        book_coverage_count=4,
        market_no_vig_probability=0.53,
    )

    report = shadow_markets.shadow_performance_report()
    ml = report["markets"]["MONEYLINE"]
    total = report["markets"]["TOTAL"]

    assert ml["published"] == 2
    assert ml["graded"] == 2
    assert ml["settledSampleTarget"] == 200
    assert ml["settledSampleProgress"] == pytest.approx(2 / 200)
    assert ml["openingCoverage"] == 1.0
    assert ml["currentCoverage"] == 1.0
    assert ml["closingCoverage"] == 1.0
    assert ml["twoSidedNoVigCoverage"] == 1.0
    assert ml["averageSportsbookDepth"] == pytest.approx(4.6666666667)
    assert ml["medianSportsbookDepth"] == 5.0
    assert ml["averageModelProbability"] is not None
    assert ml["averageCLV"] is not None
    assert ml["positiveCLVRate"] is not None

    assert total["published"] == 2
    assert total["graded"] == 2
    assert total["settledSampleTarget"] == 300
    assert total["settledSampleProgress"] == pytest.approx(2 / 300)
    assert total["openingCoverage"] == 1.0
    assert total["currentCoverage"] == 1.0
    assert total["closingCoverage"] == 1.0
    assert total["twoSidedNoVigCoverage"] == 1.0
    assert total["averageSportsbookDepth"] == pytest.approx(4.3333333333)
    assert total["medianSportsbookDepth"] == 4.0
    assert total["averageModelProbability"] is not None
    assert total["averageCLV"] is not None
    assert total["positiveCLVRate"] is not None

    gates = shadow_markets.shadow_promotion_gates()["markets"]
    assert gates["MONEYLINE"]["criteria"]["settledSampleTarget"] == 200
    assert gates["TOTAL"]["criteria"]["settledSampleTarget"] == 300
    assert gates["MONEYLINE"]["productionEligibility"] == "NO"
    assert gates["TOTAL"]["productionEligibility"] == "NO"


def test_team_total_candidate_team_identity_and_period(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {
                "api_event_id": "2026_03_BUF_MIA",
                "commence_time": "2026-09-24T17:00:00+00:00",
                "market": "team_totals",
                "side": "over",
                "team_code": "BUF",
                "latest_point": 27.5,
                "latest_price": -110,
                "sportsbook": "DraftKings",
                "last_seen": "2026-09-24T16:00:00+00:00",
                "home_team": "MIA",
                "away_team": "BUF",
            },
            {
                "api_event_id": "2026_03_BUF_MIA",
                "commence_time": "2026-09-24T17:00:00+00:00",
                "market": "team_totals",
                "side": "under",
                "team_code": "BUF",
                "latest_point": 27.5,
                "latest_price": -110,
                "sportsbook": "DraftKings",
                "last_seen": "2026-09-24T16:00:00+00:00",
                "home_team": "MIA",
                "away_team": "BUF",
            },
        ]
    )
    proj = {
        "2026_03_BUF_MIA": pd.Series(
            {
                "api_event_id": "2026_03_BUF_MIA",
                "model_margin_home": -2.0,
                "model_total_baseline": 48.0,
            }
        )
    }
    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: proj)

    out = shadow_markets.build_shadow_boards(week=3, season=2026)
    assert out["teamTotalCount"] == 0

    con = sqlite3.connect(str(shadow_db))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT market_family, period, team_code, cross_market_comparable, production_eligible FROM shadow_candidates"
    ).fetchall()
    con.close()
    assert len(rows) == 0


def test_first_half_markets_not_generated_without_validated_model(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {"api_event_id": "2026_04_A_B", "commence_time": "2026-09-30T17:00:00+00:00", "market": "spreads_h1", "side": "away", "latest_point": 1.5, "latest_price": -110, "sportsbook": "DraftKings", "last_seen": "2026-09-30T16:00:00+00:00", "home_team": "B", "away_team": "A"},
            {"api_event_id": "2026_04_A_B", "commence_time": "2026-09-30T17:00:00+00:00", "market": "h2h_h1", "side": "away", "latest_point": None, "latest_price": 120, "sportsbook": "DraftKings", "last_seen": "2026-09-30T16:00:00+00:00", "home_team": "B", "away_team": "A"},
            {"api_event_id": "2026_04_A_B", "commence_time": "2026-09-30T17:00:00+00:00", "market": "totals_h1", "side": "over", "latest_point": 23.5, "latest_price": -110, "sportsbook": "DraftKings", "last_seen": "2026-09-30T16:00:00+00:00", "home_team": "B", "away_team": "A"},
        ]
    )
    proj = {"2026_04_A_B": pd.Series({"api_event_id": "2026_04_A_B", "model_margin_home": -2.0, "model_total_baseline": 47.0})}

    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: proj)

    out = shadow_markets.build_shadow_boards(week=4, season=2026)
    assert out["firstHalfSpreadCount"] == 0
    assert out["firstHalfMoneylineCount"] == 0
    assert out["firstHalfTotalCount"] == 0


def test_no_full_game_first_half_closing_collision(monkeypatch, tmp_path):
    import duckdb  # type: ignore

    model_root = tmp_path / "model-collision"
    db_dir = model_root / "database"
    db_dir.mkdir(parents=True)
    db = db_dir / "nfl_model.duckdb"

    con = duckdb.connect(str(db))
    con.execute(
        """
        CREATE TABLE odds_snapshots (
            api_event_id VARCHAR,
            bookmaker_key VARCHAR,
            market_key VARCHAR,
            outcome_code VARCHAR,
            outcome_name VARCHAR,
            fetched_at TIMESTAMP,
            point DOUBLE,
            price DOUBLE
        )
        """
    )
    con.execute(
        """
        INSERT INTO odds_snapshots VALUES
        ('evt-c','DraftKings','totals','over','OVER','2026-09-10 16:50:00',23.5,-110),
        ('evt-c','DraftKings','totals','under','UNDER','2026-09-10 16:50:00',23.5,-110)
        """
    )
    con.close()

    monkeypatch.setattr(shadow_markets, "MODEL_ROOT", model_root)
    kickoff = pd.Timestamp("2026-09-10T17:00:00+00:00").to_pydatetime()
    p, status = shadow_markets._two_sided_closing_no_vig(
        event_id="evt-c",
        sportsbook="DraftKings",
        market_family="FIRST_HALF_TOTAL",
        side="over",
        kickoff=kickoff,
        recommended_line=23.5,
    )
    assert p is None
    assert status == "UNAVAILABLE_TWO_SIDED_MARKET"


def test_team_total_and_first_half_outcome_grading(shadow_db):
    _seed_run_and_candidate(
        shadow_db,
        run_id="run-tt-1",
        season=2026,
        week=14,
        candidate_id="cand-tt-win",
        market_family="TEAM_TOTAL",
        market_key="team_total",
        side="over",
        period="FULL_GAME",
        line=20.5,
        price=-110,
    )
    con = sqlite3.connect(str(shadow_db))
    con.execute("UPDATE shadow_candidates SET team_code = ? WHERE candidate_id = ?", ["AWAY", "cand-tt-win"])
    con.commit()
    con.close()

    _seed_run_and_candidate(
        shadow_db,
        run_id="run-h1-ml",
        season=2026,
        week=14,
        candidate_id="cand-h1-ml-tie",
        market_family="FIRST_HALF_MONEYLINE",
        market_key="first_half_moneyline",
        side="away",
        period="FIRST_HALF",
        line=None,
        price=120,
    )

    shadow_markets.publish_shadow_snapshot(run_id="run-tt-1", is_official=False)
    shadow_markets.publish_shadow_snapshot(run_id="run-h1-ml", is_official=False)

    out = shadow_markets.append_shadow_outcomes(
        fetch_scores_fn=lambda _: {
            "finalAwayScore": 24,
            "finalHomeScore": 21,
            "firstHalfAwayScore": 10,
            "firstHalfHomeScore": 10,
        }
    )
    assert out["appended"] == 2

    con = sqlite3.connect(str(shadow_db))
    rows = con.execute(
        "SELECT candidate_id, result FROM shadow_outcomes WHERE candidate_id IN ('cand-tt-win','cand-h1-ml-tie') ORDER BY candidate_id"
    ).fetchall()
    con.close()
    assert rows[0][1] == "PUSH"  # 1H moneyline tie
    assert rows[1][1] == "WIN"   # team total over hit


def test_phase2b_foundation_audit_shape(monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "discover_expanded_markets",
        lambda: {
            "targets": {
                "TEAM_TOTAL": {"supported": True},
                "1H_SPREAD": {"supported": False},
                "1H_MONEYLINE": {"supported": False},
                "1H_TOTAL": {"supported": False},
            },
            "quota": {},
        },
    )
    audit = shadow_markets.phase2b_market_foundation_audit()
    assert "markets" in audit
    assert "TEAM_TOTAL" in audit["markets"]
    assert audit["markets"]["TEAM_TOTAL"]["dataAvailable"] is True
    assert audit["markets"]["FIRST_HALF_SPREAD"]["modelValidated"] is False


def test_discover_expanded_markets_uses_event_odds_and_provider_keys(monkeypatch):
    events = [
        {
            "id": "evt-1",
            "away_team": "Away",
            "home_team": "Home",
            "commence_time": "2026-09-01T17:00:00Z",
        }
    ]
    called = {"markets": []}

    def _events():
        return 200, {"x-requests-remaining": "19990", "x-requests-used": "10", "x-requests-last": "0"}, events

    def _event_odds(event_id: str, markets: list[str]):
        called["markets"] = list(markets)
        return (
            200,
            {"x-requests-remaining": "19989", "x-requests-used": "11", "x-requests-last": "4"},
            {
                "bookmakers": [
                    {
                        "key": "fanduel",
                        "last_update": "2026-09-01T16:59:00Z",
                        "markets": [
                            {"key": "team_totals", "last_update": "2026-09-01T16:59:00Z", "outcomes": [{"name": "over", "description": "Away", "point": 20.5, "price": -110}]},
                            {"key": "spreads_h1", "last_update": "2026-09-01T16:59:00Z", "outcomes": [{"name": "away", "point": 1.5, "price": -110}]},
                            {"key": "h2h_h1", "last_update": "2026-09-01T16:59:00Z", "outcomes": [{"name": "away", "price": 120}]},
                            {"key": "totals_h1", "last_update": "2026-09-01T16:59:00Z", "outcomes": [{"name": "over", "point": 23.5, "price": -110}]},
                        ],
                    }
                ]
            },
        )

    monkeypatch.setattr(shadow_markets, "_call_odds_api_events", _events)
    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _event_odds)
    monkeypatch.setenv("EXPANDED_MARKET_EVENT_SAMPLE_SIZE", "1")

    out = shadow_markets.discover_expanded_markets(provider_opt_in=True)
    assert set(called["markets"]) == {"team_totals", "spreads_h1", "h2h_h1", "totals_h1"}
    assert out["targets"]["TEAM_TOTAL"]["status"] == "AVAILABLE"
    assert out["targets"]["1H_SPREAD"]["status"] == "AVAILABLE"
    assert out["targets"]["1H_MONEYLINE"]["status"] == "AVAILABLE"
    assert out["targets"]["1H_TOTAL"]["status"] == "AVAILABLE"
    assert out["quotaAccounting"]["expandedMarketRequestCount"] == 1


def test_discover_expanded_markets_requires_provider_opt_in_by_default():
    out = shadow_markets.discover_expanded_markets(provider_opt_in=False)
    assert out["estimatedRequestCost"] == 0
    assert out["quotaAccounting"]["expandedMarketRequestCount"] == 0
    assert all(str(v.get("status") or "") == "PROVIDER_OPT_IN_REQUIRED" for v in (out.get("targets") or {}).values())


def test_ingest_expanded_market_snapshots_persists_raw_rows_and_depth(monkeypatch, shadow_db):
    discovery = {
        "targets": {
            "TEAM_TOTAL": {"supported": True},
            "1H_SPREAD": {"supported": True},
            "1H_MONEYLINE": {"supported": True},
            "1H_TOTAL": {"supported": True},
        },
        "eventSamples": [
            {
                "eventId": "evt-raw-1",
                "awayTeam": "Away Team",
                "homeTeam": "Home Team",
                "commenceTime": "2026-09-01T17:00:00Z",
            }
        ],
        "eventPayloadById": {
            "evt-raw-1": {
                "bookmakers": [
                    {
                        "key": "fanduel",
                        "last_update": "2026-09-01T16:58:00Z",
                        "markets": [
                            {
                                "key": "team_totals",
                                "last_update": "2026-09-01T16:58:00Z",
                                "outcomes": [
                                    {"name": "over", "description": "Away Team", "point": 20.5, "price": -110},
                                    {"name": "under", "description": "Away Team", "point": 20.5, "price": -110},
                                ],
                            },
                            {
                                "key": "spreads_h1",
                                "last_update": "2026-09-01T16:58:00Z",
                                "outcomes": [
                                    {"name": "away", "point": 1.5, "price": -105},
                                    {"name": "home", "point": -1.5, "price": -115},
                                ],
                            },
                            {
                                "key": "h2h_h1",
                                "last_update": "2026-09-01T16:58:00Z",
                                "outcomes": [
                                    {"name": "away", "price": 120},
                                    {"name": "home", "price": -140},
                                ],
                            },
                            {
                                "key": "totals_h1",
                                "last_update": "2026-09-01T16:58:00Z",
                                "outcomes": [
                                    {"name": "over", "point": 23.5, "price": -110},
                                    {"name": "under", "point": 23.5, "price": -110},
                                ],
                            },
                        ],
                    }
                ]
            }
        },
    }

    out = shadow_markets.ingest_expanded_market_snapshots(discovery=discovery)
    assert out["rowsSaved"] == 8

    con = sqlite3.connect(str(shadow_db))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT market_family, market_key, phase, period, side, team_code, line, price,
               book_coverage_count, market_depth_status, source_snapshot_id
        FROM shadow_market_snapshots
        ORDER BY market_family, side
        """
    ).fetchall()
    con.close()

    assert rows
    families = {str(r["market_family"]) for r in rows}
    assert families == {"TEAM_TOTAL", "FIRST_HALF_SPREAD", "FIRST_HALF_MONEYLINE", "FIRST_HALF_TOTAL"}
    assert all(str(r["phase"]) == "PREGAME" for r in rows)
    assert all(int(r["book_coverage_count"]) == 1 for r in rows)
    assert all(str(r["market_depth_status"]) == "SINGLE_BOOK" for r in rows)
    assert all(str(r["source_snapshot_id"]) for r in rows)
    tt = [r for r in rows if str(r["market_family"]) == "TEAM_TOTAL"]
    assert tt
    assert all(str(r["period"]) == "FULL_GAME" for r in tt)
    assert all(str(r["team_code"]) == "AWAY TEAM" for r in tt)
    h1_ml = [r for r in rows if str(r["market_family"]) == "FIRST_HALF_MONEYLINE"]
    assert h1_ml
    assert all(r["line"] is None for r in h1_ml)


def test_ingest_expanded_market_snapshots_idempotent(monkeypatch, shadow_db):
    discovery = {
        "targets": {
            "TEAM_TOTAL": {"supported": True},
            "1H_SPREAD": {"supported": False},
            "1H_MONEYLINE": {"supported": False},
            "1H_TOTAL": {"supported": False},
        },
        "eventSamples": [{"eventId": "evt-idem-1", "awayTeam": "Away", "homeTeam": "Home"}],
        "eventPayloadById": {
            "evt-idem-1": {
                "bookmakers": [
                    {
                        "key": "fanduel",
                        "markets": [
                            {
                                "key": "team_totals",
                                "outcomes": [
                                    {"name": "over", "description": "Away", "point": 21.5, "price": -110},
                                    {"name": "under", "description": "Away", "point": 21.5, "price": -110},
                                ],
                            }
                        ],
                    }
                ]
            }
        },
    }

    first = shadow_markets.ingest_expanded_market_snapshots(discovery=discovery)
    second = shadow_markets.ingest_expanded_market_snapshots(discovery=discovery)
    assert first["rowsSaved"] == 2
    assert second["rowsSaved"] == 0


def test_expanded_market_collection_status_and_quota_accounting(monkeypatch, shadow_db):
    monkeypatch.setattr(
        shadow_markets,
        "discover_expanded_markets",
        lambda: {
            "targets": {
                "TEAM_TOTAL": {"supported": True, "status": "AVAILABLE"},
                "1H_SPREAD": {"supported": True, "status": "AVAILABLE"},
                "1H_MONEYLINE": {"supported": True, "status": "AVAILABLE"},
                "1H_TOTAL": {"supported": True, "status": "AVAILABLE"},
            },
            "quota": {"remaining": "19990", "used": "10", "last": "4"},
            "quotaAccounting": {
                "creditsUsed": "10",
                "creditsRemaining": "19990",
                "lastRequestCost": "4",
                "expandedMarketRequestCount": 3,
            },
            "eventSamples": [],
            "eventPayloadById": {},
        },
    )
    audit = shadow_markets.phase2b_market_foundation_audit()
    assert audit["providerAudit"]["quotaAccounting"]["expandedMarketRequestCount"] == 3
    assert "collectionStatus" in audit
    assert "TEAM_TOTAL" in audit["collectionStatus"]["markets"]


def test_team_total_research_math_and_probability_symmetry():
    df = pd.DataFrame(
        {
            "home_score": [21, 24, 17, 28] * 60,
            "away_score": [20, 17, 21, 24] * 60,
            "model_margin": [1, 7, -4, 4] * 60,
            "model_total": [41, 41, 38, 52] * 60,
            "home_team_total_line": [20.5, 23.5, 18.5, 26.5] * 60,
            "away_team_total_line": [20.5, 17.5, 19.5, 24.5] * 60,
        }
    )
    out = shadow_markets._team_total_research_from_df(df)
    assert out["ready"] is True
    assert out["identityChecks"]["totalConsistencyMaxAbs"] < 1e-9
    assert out["identityChecks"]["marginConsistencyMaxAbs"] < 1e-9
    assert out["probabilityValidation"]["maxSymmetryError"] is not None
    assert out["probabilityValidation"]["maxSymmetryError"] < 1e-9
    assert out["probabilityValidation"]["pushRate"] is not None
