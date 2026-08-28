from __future__ import annotations

import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd
import pytest

from app.services import closing_line
from app.services import decision_ledger as dl
from app.services import pregame_collection_manager as mgr
from app.services import refresh_orchestrator as orch
from app.services import shadow_markets


MAIN_EVENT_ID = "2026_01_NO_ATL"
LATE_EVENT_ID = "2026_01_BUF_KC"
KICKOFF_MAIN = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
KICKOFF_LATE = datetime(2026, 9, 13, 17, 1, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _init_closing_db(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE odds_snapshots (
            fetched_at TIMESTAMP,
            api_event_id VARCHAR,
            commence_time TIMESTAMP,
            home_team VARCHAR,
            away_team VARCHAR,
            home_code VARCHAR,
            away_code VARCHAR,
            bookmaker_key VARCHAR,
            bookmaker_title VARCHAR,
            market_key VARCHAR,
            outcome_name VARCHAR,
            outcome_code VARCHAR,
            point DOUBLE,
            price DOUBLE,
            implied_prob DOUBLE,
            snapshot_type VARCHAR,
            source VARCHAR
        )
        """
    )
    con.close()


def _insert_odds_snapshot(
    db_path: Path,
    *,
    event_id: str,
    kickoff: datetime,
    market_key: str,
    outcome_code: str,
    point: float | None,
    price: float,
    fetched_at: datetime,
    home_team: str,
    away_team: str,
    home_code: str,
    away_code: str,
    bookmaker_key: str = "DraftKings",
) -> None:
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        INSERT INTO odds_snapshots (
            fetched_at, api_event_id, commence_time, home_team, away_team,
            home_code, away_code, bookmaker_key, bookmaker_title,
            market_key, outcome_name, outcome_code, point, price,
            implied_prob, snapshot_type, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'current', 'test')
        """,
        [
            fetched_at.astimezone(timezone.utc).replace(tzinfo=None),
            event_id,
            kickoff.astimezone(timezone.utc).replace(tzinfo=None),
            home_team,
            away_team,
            home_code,
            away_code,
            bookmaker_key,
            bookmaker_key,
            market_key,
            outcome_code,
            outcome_code,
            point,
            price,
        ],
    )
    con.close()


def _seed_closing_market_history(db_path: Path) -> None:
    # Official spread decision event.
    _insert_odds_snapshot(
        db_path,
        event_id=MAIN_EVENT_ID,
        kickoff=KICKOFF_MAIN,
        market_key="spreads",
        outcome_code="away",
        point=3.0,
        price=-110.0,
        fetched_at=KICKOFF_MAIN - timedelta(hours=10),
        home_team="ATL",
        away_team="NO",
        home_code="ATL",
        away_code="NO",
    )
    _insert_odds_snapshot(
        db_path,
        event_id=MAIN_EVENT_ID,
        kickoff=KICKOFF_MAIN,
        market_key="spreads",
        outcome_code="away",
        point=1.5,
        price=-110.0,
        fetched_at=KICKOFF_MAIN - timedelta(minutes=2),
        home_team="ATL",
        away_team="NO",
        home_code="ATL",
        away_code="NO",
    )

    # Shadow moneyline event.
    _insert_odds_snapshot(
        db_path,
        event_id=LATE_EVENT_ID,
        kickoff=KICKOFF_LATE,
        market_key="h2h",
        outcome_code="away",
        point=None,
        price=140.0,
        fetched_at=KICKOFF_LATE - timedelta(hours=8),
        home_team="KC",
        away_team="BUF",
        home_code="KC",
        away_code="BUF",
    )
    _insert_odds_snapshot(
        db_path,
        event_id=LATE_EVENT_ID,
        kickoff=KICKOFF_LATE,
        market_key="h2h",
        outcome_code="away",
        point=None,
        price=125.0,
        fetched_at=KICKOFF_LATE - timedelta(minutes=2),
        home_team="KC",
        away_team="BUF",
        home_code="KC",
        away_code="BUF",
    )

    # Shadow total event.
    _insert_odds_snapshot(
        db_path,
        event_id=LATE_EVENT_ID,
        kickoff=KICKOFF_LATE,
        market_key="totals",
        outcome_code="over",
        point=45.5,
        price=-110.0,
        fetched_at=KICKOFF_LATE - timedelta(hours=8),
        home_team="KC",
        away_team="BUF",
        home_code="KC",
        away_code="BUF",
    )
    _insert_odds_snapshot(
        db_path,
        event_id=LATE_EVENT_ID,
        kickoff=KICKOFF_LATE,
        market_key="totals",
        outcome_code="over",
        point=47.0,
        price=-110.0,
        fetched_at=KICKOFF_LATE - timedelta(minutes=2),
        home_team="KC",
        away_team="BUF",
        home_code="KC",
        away_code="BUF",
    )


def _games(phase: str) -> list[dict[str, str]]:
    base = [
        {
            "eventId": MAIN_EVENT_ID,
            "commenceTime": _iso(KICKOFF_MAIN),
            "awayAbbreviation": "NO",
            "homeAbbreviation": "ATL",
        }
    ]
    if phase in {"gameday", "gameday-repeat", "closing", "closing-repeat", "postkickoff"}:
        base.append(
            {
                "eventId": LATE_EVENT_ID,
                "commenceTime": _iso(KICKOFF_LATE),
                "awayAbbreviation": "BUF",
                "homeAbbreviation": "KC",
            }
        )
    return base


def _line_board_for_phase(phase: str) -> pd.DataFrame:
    current_ts = {
        "opening": KICKOFF_MAIN - timedelta(hours=31),
        "opening-repeat": KICKOFF_MAIN - timedelta(hours=31),
        "gameday": KICKOFF_MAIN - timedelta(hours=10),
        "gameday-repeat": KICKOFF_MAIN - timedelta(hours=10),
        "closing": KICKOFF_MAIN - timedelta(minutes=2),
        "closing-repeat": KICKOFF_MAIN - timedelta(minutes=2),
        "postkickoff": KICKOFF_MAIN - timedelta(minutes=2),
    }[phase]

    rows: list[dict[str, object]] = []
    for game in _games(phase):
        event_id = str(game["eventId"])
        kickoff = KICKOFF_MAIN if event_id == MAIN_EVENT_ID else KICKOFF_LATE
        away = str(game["awayAbbreviation"])
        home = str(game["homeAbbreviation"])
        spread_point = 3.0 if phase in {"opening", "opening-repeat"} else 2.5 if phase in {"gameday", "gameday-repeat"} else 1.5
        if event_id == LATE_EVENT_ID and phase in {"gameday", "gameday-repeat"}:
            spread_point = 1.0
        if event_id == LATE_EVENT_ID and phase in {"closing", "closing-repeat", "postkickoff"}:
            spread_point = 0.5

        rows.extend(
            [
                {
                    "api_event_id": event_id,
                    "commence_time": _iso(kickoff),
                    "market": "spread",
                    "side": "away",
                    "latest_point": spread_point,
                    "latest_price": -110,
                    "sportsbook": "DraftKings",
                    "bookmakerKey": "draftkings",
                    "last_seen": _iso(current_ts),
                    "home_team": home,
                    "away_team": away,
                },
                {
                    "api_event_id": event_id,
                    "commence_time": _iso(kickoff),
                    "market": "moneyline",
                    "side": "away",
                    "latest_point": None,
                    "latest_price": 140 if event_id == LATE_EVENT_ID else 135,
                    "sportsbook": "DraftKings",
                    "bookmakerKey": "draftkings",
                    "last_seen": _iso(current_ts),
                    "home_team": home,
                    "away_team": away,
                },
                {
                    "api_event_id": event_id,
                    "commence_time": _iso(kickoff),
                    "market": "total",
                    "side": "over",
                    "latest_point": 45.5 if event_id == MAIN_EVENT_ID else 46.0,
                    "latest_price": -110,
                    "sportsbook": "DraftKings",
                    "bookmakerKey": "draftkings",
                    "last_seen": _iso(current_ts),
                    "home_team": home,
                    "away_team": away,
                },
            ]
        )
    return pd.DataFrame(rows)


def _prop_payload(event_id: str) -> dict:
    player_name = "Derek Carr" if event_id == MAIN_EVENT_ID else "Josh Allen"
    player_id = "QB-NO-4" if event_id == MAIN_EVENT_ID else "QB-BUF-17"
    return {
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": _iso(KICKOFF_MAIN - timedelta(hours=10)),
                "markets": [
                    {
                        "key": "player_pass_yds",
                        "last_update": _iso(KICKOFF_MAIN - timedelta(hours=10)),
                        "outcomes": [{"name": "Over", "description": player_name, "player_id": player_id, "point": 249.5, "price": -110}],
                    },
                    {
                        "key": "player_pass_tds",
                        "last_update": _iso(KICKOFF_MAIN - timedelta(hours=10)),
                        "outcomes": [{"name": "Over", "description": player_name, "player_id": player_id, "point": 1.5, "price": -105}],
                    },
                    {
                        "key": "player_rush_yds",
                        "last_update": _iso(KICKOFF_MAIN - timedelta(hours=10)),
                        "outcomes": [{"name": "Over", "description": player_name, "player_id": player_id, "point": 12.5, "price": -110}],
                    },
                    {
                        "key": "player_reception_yds",
                        "last_update": _iso(KICKOFF_MAIN - timedelta(hours=10)),
                        "outcomes": [{"name": "Over", "description": player_name, "player_id": player_id, "point": 0.5, "price": -110}],
                    },
                    {
                        "key": "player_receptions",
                        "last_update": _iso(KICKOFF_MAIN - timedelta(hours=10)),
                        "outcomes": [{"name": "Over", "description": player_name, "player_id": player_id, "point": 0.5, "price": -110}],
                    },
                    {
                        "key": "player_anytime_td",
                        "last_update": _iso(KICKOFF_MAIN - timedelta(hours=10)),
                        "outcomes": [{"name": "Yes", "description": player_name, "player_id": player_id, "price": 125}],
                    },
                ],
            }
        ]
    }


def _read_count(db_path: Path, table: str) -> int:
    con = sqlite3.connect(str(db_path))
    count = int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    con.close()
    return count


def _read_one(db_path: Path, sql: str, params: list[object] | None = None) -> sqlite3.Row | None:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    row = con.execute(sql, params or []).fetchone()
    con.close()
    return row


def _seed_shadow_candidate(
    db_path: Path,
    *,
    run_id: str,
    candidate_id: str,
    event_id: str,
    commence_time: str,
    market_family: str,
    market_key: str,
    side: str,
    line: float | None,
    price: float,
) -> None:
    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        INSERT INTO shadow_candidate_runs (
            run_id, created_at_utc, season, week, source_snapshot_id,
            source_market_timestamp, candidate_count, payload_hash, canonical_payload
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [run_id, "2026-09-12T00:00:00+00:00", 2026, 1, f"src-{run_id}", "2026-09-12T00:00:00+00:00", 1, f"hash-{run_id}", "{}"],
    )
    values = [
        run_id,
        candidate_id,
        "2026-09-12T00:00:00+00:00",
        2026,
        1,
        event_id,
        commence_time,
        market_family,
        market_key,
        "FULL_GAME",
        "BUF" if market_family == "MONEYLINE" else "OVER 46.0",
        side,
        "BUF" if market_family == "MONEYLINE" else None,
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
        "2026-09-12T00:00:00+00:00",
        f"odds-{candidate_id}",
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


@contextmanager
def _freeze_module_datetimes(monkeypatch: pytest.MonkeyPatch, now: datetime):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return now.astimezone(timezone.utc).replace(tzinfo=None)
            return now.astimezone(tz)

    monkeypatch.setattr(orch, "datetime", FrozenDateTime)
    monkeypatch.setattr(closing_line, "datetime", FrozenDateTime)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    yield


def run_week1_full_lifecycle_certification(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    shadow_db = tmp_path / "week1_shadow.sqlite"
    ledger_db = tmp_path / "week1_ledger.sqlite"
    closing_db = tmp_path / "week1_closing.duckdb"

    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    monkeypatch.setattr(shadow_markets, "_DB_PATH", shadow_db)
    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(closing_line, "_DB_PATH", closing_db)

    shadow_markets._ensure_schema()
    mgr._ensure_manager_schema()
    dl._ensure_schema()
    _init_closing_db(closing_db)
    _seed_closing_market_history(closing_db)

    phase = {"name": "opening"}
    provider_calls: list[dict[str, object]] = []

    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(phase["name"])))
    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: _line_board_for_phase(phase["name"]))
    monkeypatch.setattr(
        shadow_markets,
        "_resolve_player_identity",
        lambda name, team, **kwargs: {
            "providerPlayerName": name,
            "normalizedPlayerName": str(name).upper(),
            "matchStatus": "EXACT",
            "canonicalPlayerId": kwargs.get("provider_player_id") or f"ID-{str(name).upper()}",
            "canonicalPlayerName": name,
            "position": "QB",
            "team": "NO" if kwargs.get("provider_player_id") == "QB-NO-4" else "BUF",
            "opponent": "ATL" if kwargs.get("provider_player_id") == "QB-NO-4" else "KC",
        },
    )

    def _provider(event_id: str, allowlist: list[str]):
        provider_calls.append({"eventId": event_id, "allowlist": tuple(allowlist)})
        return 200, {"x-requests-last": "6", "x-requests-remaining": "994", "x-requests-used": str(len(provider_calls))}, _prop_payload(event_id)

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)

    counts: dict[str, int] = {
        "opening_after_t1": 0,
        "opening_after_t2": 0,
        "props_after_t3": 0,
        "props_after_t4": 0,
        "closing_after_t5": 0,
        "closing_after_t6": 0,
        "shadow_after_t10": 0,
    }

    with _freeze_module_datetimes(monkeypatch, KICKOFF_MAIN - timedelta(hours=31)):
        t0_standard = _read_count(shadow_db, "prospective_market_snapshots")
        t0_props = _read_count(shadow_db, "player_prop_market_snapshots")
        t1 = orch._run_pregame_automation_tick()
        counts["opening_after_t1"] = _read_count(shadow_db, "prospective_market_snapshots")

    phase["name"] = "opening-repeat"
    with _freeze_module_datetimes(monkeypatch, KICKOFF_MAIN - timedelta(hours=31)):
        t2 = orch._run_pregame_automation_tick()
        counts["opening_after_t2"] = _read_count(shadow_db, "prospective_market_snapshots")

    phase["name"] = "gameday"
    with _freeze_module_datetimes(monkeypatch, KICKOFF_MAIN - timedelta(hours=10)):
        t3 = orch._run_pregame_automation_tick()
        counts["props_after_t3"] = _read_count(shadow_db, "player_prop_market_snapshots")

    current_spread = _read_one(
        shadow_db,
        """
        SELECT source_snapshot_id, line, price, sportsbook
        FROM prospective_market_snapshots
        WHERE event_id = ? AND market_family = 'SPREAD' AND state_label = 'CURRENT'
        ORDER BY id DESC
        LIMIT 1
        """,
        [MAIN_EVENT_ID],
    )
    assert current_spread is not None

    decision = dl.record_decision(
        {
            "publishedAtUTC": "2026-09-13T07:01:00+00:00",
            "season": 2026,
            "week": 1,
            "eventId": MAIN_EVENT_ID,
            "commenceTime": _iso(KICKOFF_MAIN),
            "awayTeam": "NO",
            "homeTeam": "ATL",
            "selection": f"NO +{float(current_spread['line']):g}",
            "market": "spreads",
            "side": "away",
            "point": float(current_spread["line"]),
            "price": float(current_spread["price"]),
            "sportsbook": str(current_spread["sportsbook"]),
            "rawProbability": 0.57,
            "calibratedProbability": 0.59,
            "pushProbability": 0.02,
            "lossProbability": 0.39,
            "rawEdge": 0.032,
            "calibratedEdge": 0.041,
            "currentEV": 0.054,
            "fairLine": -128.0,
            "truePlayableTo": -118.0,
            "truePlayableToStatus": "AVAILABLE",
            "siScore": 80.0,
            "siGrade": "A-",
            "siRank": 1,
            "recommendation": "BET",
            "qualificationStatus": "QUALIFIED",
            "qualificationReasons": ["edge", "ev"],
            "oddsProvider": "line_movement_board",
            "oddsTimestamp": "2026-09-13T07:00:00+00:00",
            "modelTimestamp": "2026-09-13T06:58:00+00:00",
            "marketTimestamp": "2026-09-13T07:00:00+00:00",
            "sourceSnapshotId": str(current_spread["source_snapshot_id"]),
        },
        publication_type="SIA_3",
    )
    publication = dl.publish_sia3(
        {
            "publicationType": "SIA_3",
            "publishedAtUTC": "2026-09-13T07:02:00+00:00",
            "season": 2026,
            "week": 1,
            "isOfficial": True,
            "slots": [
                {"decisionId": decision["decisionId"], "slotLabel": "BET", "qualificationStatus": "QUALIFIED"},
                {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
                {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
            ],
        }
    )

    _seed_shadow_candidate(
        shadow_db,
        run_id="shadow-ml-week1",
        candidate_id="cand-ml-week1",
        event_id=LATE_EVENT_ID,
        commence_time=_iso(KICKOFF_LATE),
        market_family="MONEYLINE",
        market_key="moneyline",
        side="away",
        line=None,
        price=140.0,
    )
    _seed_shadow_candidate(
        shadow_db,
        run_id="shadow-total-week1",
        candidate_id="cand-total-week1",
        event_id=LATE_EVENT_ID,
        commence_time=_iso(KICKOFF_LATE),
        market_family="TOTAL",
        market_key="total",
        side="over",
        line=46.0,
        price=-110.0,
    )
    shadow_markets.publish_shadow_snapshot(run_id="shadow-ml-week1", is_official=False)
    shadow_markets.publish_shadow_snapshot(run_id="shadow-total-week1", is_official=False)

    phase["name"] = "gameday-repeat"
    with _freeze_module_datetimes(monkeypatch, KICKOFF_MAIN - timedelta(hours=10)):
        t4 = orch._run_pregame_automation_tick()
        counts["props_after_t4"] = _read_count(shadow_db, "player_prop_market_snapshots")

    phase["name"] = "closing"
    with _freeze_module_datetimes(monkeypatch, KICKOFF_MAIN - timedelta(minutes=2)):
        t5 = orch._run_pregame_automation_tick()
        closing_t5 = _read_one(
            shadow_db,
            "SELECT COUNT(*) AS n FROM prospective_market_snapshots WHERE state_label = 'CLOSING'",
        )
        counts["closing_after_t5"] = 0 if closing_t5 is None else int(closing_t5["n"])

    phase["name"] = "closing-repeat"
    with _freeze_module_datetimes(monkeypatch, KICKOFF_MAIN - timedelta(minutes=2)):
        t6 = orch._run_pregame_automation_tick()
        closing_t6 = _read_one(
            shadow_db,
            "SELECT COUNT(*) AS n FROM prospective_market_snapshots WHERE state_label = 'CLOSING'",
        )
        counts["closing_after_t6"] = 0 if closing_t6 is None else int(closing_t6["n"])

    phase["name"] = "postkickoff"
    with _freeze_module_datetimes(monkeypatch, KICKOFF_LATE + timedelta(minutes=2)):
        before_postkick_counts = {
            "standard": _read_count(shadow_db, "prospective_market_snapshots"),
            "props": _read_count(shadow_db, "player_prop_market_snapshots"),
        }
        t8 = orch._run_pregame_automation_tick()
        after_postkick_counts = {
            "standard": _read_count(shadow_db, "prospective_market_snapshots"),
            "props": _read_count(shadow_db, "player_prop_market_snapshots"),
        }

    def _scores(event_id: str):
        if event_id == MAIN_EVENT_ID:
            return {"status": "FINAL", "finalAwayScore": 24, "finalHomeScore": 20, "sourceSnapshotId": "score-main-1"}
        if event_id == LATE_EVENT_ID:
            return {"status": "FINAL", "finalAwayScore": 27, "finalHomeScore": 24, "sourceSnapshotId": "score-late-1"}
        return None

    with _freeze_module_datetimes(monkeypatch, KICKOFF_LATE + timedelta(hours=3)):
        postgame1 = dl.run_official_postgame_lifecycle(fetch_scores_fn=_scores)
        postgame2 = dl.run_official_postgame_lifecycle(fetch_scores_fn=_scores)
        shadow_postgame1 = shadow_markets.append_shadow_outcomes(fetch_scores_fn=_scores)
        shadow_postgame2 = shadow_markets.append_shadow_outcomes(fetch_scores_fn=_scores)
        performance = dl.get_prospective_performance()
        promotion = dl._official_promotion_progress(performance)
        shadow_perf = shadow_markets.shadow_performance_report()
        shadow_gates = shadow_markets.shadow_promotion_gates()
        counts["shadow_after_t10"] = _read_count(shadow_db, "shadow_outcomes")

    outcome = dl.get_decision(decision["decisionId"])
    latest_outcome = _read_one(
        ledger_db,
        """
        SELECT bet_result, closing_line, closing_price, clv, final_away_score, final_home_score
        FROM decision_outcomes
        WHERE decision_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        [decision["decisionId"]],
    )
    ledger_summary = dl.get_admin_ledger_summary(limit=10)
    schedule_firewalls = mgr.build_pregame_collection_schedule_v1(
        week=1,
        now_utc=KICKOFF_MAIN - timedelta(hours=31),
        prop_allowlist=list(mgr.DEFAULT_PROP_ALLOWLIST),
    )["firewalls"]

    return {
        "ticks": {"t1": t1, "t2": t2, "t3": t3, "t4": t4, "t5": t5, "t6": t6, "t8": t8},
        "counts": counts,
        "providerCalls": provider_calls,
        "t0Counts": {"standard": t0_standard, "props": t0_props},
        "postKickCountsStable": before_postkick_counts == after_postkick_counts,
        "postgame": {"run1": postgame1, "run2": postgame2, "shadow1": shadow_postgame1, "shadow2": shadow_postgame2},
        "performance": performance,
        "promotion": promotion,
        "shadowPerformance": shadow_perf,
        "shadowPromotion": shadow_gates,
        "decision": decision,
        "publication": publication,
        "decisionRecord": outcome,
        "latestOutcome": None if latest_outcome is None else dict(latest_outcome),
        "ledgerSummary": ledger_summary,
        "firewalls": schedule_firewalls,
    }


@pytest.fixture
def certification_summary(monkeypatch, tmp_path: Path):
    return run_week1_full_lifecycle_certification(monkeypatch, tmp_path)


def test_week1_full_lifecycle_certification_end_to_end(certification_summary):
    summary = certification_summary

    assert summary["t0Counts"] == {"standard": 0, "props": 0}

    assert summary["ticks"]["t1"]["status"] == "COMPLETED"
    assert summary["ticks"]["t1"]["providerRequests"] == 0
    assert summary["counts"]["opening_after_t1"] > 0

    assert summary["ticks"]["t2"]["status"] == "NO_WORK_DUE"
    assert summary["counts"]["opening_after_t2"] == summary["counts"]["opening_after_t1"]

    assert summary["ticks"]["t3"]["status"] == "COMPLETED"
    assert summary["ticks"]["t3"]["providerRequests"] == 2
    assert summary["ticks"]["t3"]["verifiedCredits"] == 12.0
    assert len(summary["providerCalls"]) == 2
    assert all(tuple(call["allowlist"]) == mgr.DEFAULT_PROP_ALLOWLIST for call in summary["providerCalls"])
    assert summary["counts"]["props_after_t3"] > 0

    assert summary["ticks"]["t4"]["status"] == "NO_WORK_DUE"
    assert summary["counts"]["props_after_t4"] == summary["counts"]["props_after_t3"]

    assert summary["ticks"]["t5"]["status"] == "COMPLETED"
    assert summary["ticks"]["t5"]["providerRequests"] == 0
    assert summary["counts"]["closing_after_t5"] > 0

    assert summary["ticks"]["t6"]["status"] == "NO_WORK_DUE"
    assert summary["counts"]["closing_after_t6"] == summary["counts"]["closing_after_t5"]

    assert summary["ticks"]["t8"]["status"] == "NO_WORK_DUE"
    assert summary["ticks"]["t8"]["providerRequests"] == 0
    assert summary["postKickCountsStable"] is True

    assert summary["postgame"]["run1"]["settled"] == 1
    assert summary["postgame"]["run1"]["resultBreakdown"]["WIN"] == 1
    assert summary["postgame"]["run1"]["clvAvailable"] == 1
    assert summary["postgame"]["run2"]["settled"] == 0

    assert summary["postgame"]["shadow1"]["appended"] == 2
    assert summary["postgame"]["shadow2"]["appended"] == 0
    assert summary["shadowPerformance"]["markets"]["MONEYLINE"]["graded"] == 1
    assert summary["shadowPerformance"]["markets"]["TOTAL"]["graded"] == 1
    assert summary["shadowPromotion"]["markets"]["MONEYLINE"]["productionEligibility"] == "NO"
    assert summary["shadowPromotion"]["markets"]["TOTAL"]["productionEligibility"] == "NO"

    assert summary["performance"]["gradedDecisions"] == 1
    assert summary["performance"]["W"] == 1
    assert summary["promotion"]["sampleCount"] == 1

    assert summary["decisionRecord"]["selection"] == "NO +2.5"
    assert summary["decisionRecord"]["truePlayableTo"] == -118.0
    assert summary["latestOutcome"]["bet_result"] == "WIN"
    assert summary["latestOutcome"]["closing_line"] == 1.5
    assert summary["latestOutcome"]["clv"] == 1.0

    firewalls = summary["firewalls"]
    assert firewalls["officialProductionMarket"] == "SPREAD"
    assert firewalls["moneylineProductionEligible"] is False
    assert firewalls["totalProductionEligible"] is False
    assert firewalls["playerPropProductionEligible"] is False
    assert firewalls["playerPropRecommendations"] == "DISABLED"
    assert firewalls["teamTotalRecommendations"] == "DISABLED"
    assert firewalls["firstHalfRecommendations"] == "DISABLED"
    assert firewalls["crossMarketComparable"] is False
    assert firewalls["universalSIA3"] == "DISABLED"
    assert firewalls["productionSpreadEngineChanged"] == "NO"


def test_provider_unavailable_during_game_day_isolated(monkeypatch, tmp_path: Path):
    shadow_db = tmp_path / "provider_failure.sqlite"
    monkeypatch.setattr(shadow_markets, "_DB_PATH", shadow_db)
    shadow_markets._ensure_schema()
    mgr._ensure_manager_schema()

    now = KICKOFF_MAIN - timedelta(hours=10)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games("gameday")))
    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: _line_board_for_phase("gameday"))
    monkeypatch.setattr(
        shadow_markets,
        "_resolve_player_identity",
        lambda name, team, **kwargs: {
            "providerPlayerName": name,
            "normalizedPlayerName": str(name).upper(),
            "matchStatus": "EXACT",
            "canonicalPlayerId": kwargs.get("provider_player_id") or f"ID-{str(name).upper()}",
            "canonicalPlayerName": name,
            "position": "QB",
            "team": "BUF",
            "opponent": "KC",
        },
    )

    calls: list[str] = []

    def _provider(event_id: str, allowlist: list[str]):
        calls.append(event_id)
        if event_id == MAIN_EVENT_ID:
            return 503, {"x-requests-last": "6"}, {"error": "down"}
        return 200, {"x-requests-last": "6", "x-requests-remaining": "900", "x-requests-used": "2"}, _prop_payload(event_id)

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)

    out = mgr.run_pregame_collection_manager(dry_run=False)

    assert out["status"] == "COMPLETED"
    assert out["execution"]["providerRequests"] == 2
    assert calls == [MAIN_EVENT_ID, LATE_EVENT_ID]
    assert _read_count(shadow_db, "prospective_market_snapshots") > 0
    assert _read_count(shadow_db, "player_prop_market_snapshots") > 0


def test_unknown_cost_request_budget_and_credit_budget_fail_safe(monkeypatch, tmp_path: Path):
    shadow_db = tmp_path / "budget_guard.sqlite"
    monkeypatch.setattr(shadow_markets, "_DB_PATH", shadow_db)
    shadow_markets._ensure_schema()
    mgr._ensure_manager_schema()

    now = KICKOFF_MAIN - timedelta(hours=10)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games("gameday")))
    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: _line_board_for_phase("gameday"))

    provider_called = {"count": 0}

    def _provider(*args, **kwargs):
        provider_called["count"] += 1
        return 200, {}, {}

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)

    unknown_cost = mgr.run_pregame_collection_manager(dry_run=False, prop_allowlist=["player_pass_yds"])
    assert unknown_cost["status"] == "SKIPPED"
    assert unknown_cost["execution"]["skipReason"] == "UNKNOWN_PROVIDER_CREDIT_COST"

    request_budget = mgr.run_pregame_collection_manager(dry_run=False, max_requests_per_run=0)
    assert request_budget["status"] == "SKIPPED"
    assert request_budget["execution"]["skipReason"] == "REQUEST_BUDGET_EXCEEDED"

    credit_budget = mgr.run_pregame_collection_manager(dry_run=False, max_estimated_credits_per_run=5.0)
    assert credit_budget["status"] == "SKIPPED"
    assert credit_budget["execution"]["skipReason"] == "RUN_CREDIT_BUDGET_EXCEEDED"
    assert provider_called["count"] == 0


def test_missing_closing_line_and_missing_final_score_safe(monkeypatch, tmp_path: Path):
    ledger_db = tmp_path / "missing_safe_ledger.sqlite"
    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    dl._ensure_schema()

    decision = dl.record_decision(
        {
            "publishedAtUTC": "2026-09-13T07:01:00+00:00",
            "season": 2026,
            "week": 1,
            "eventId": MAIN_EVENT_ID,
            "commenceTime": _iso(KICKOFF_MAIN),
            "awayTeam": "NO",
            "homeTeam": "ATL",
            "selection": "NO +3",
            "market": "spreads",
            "side": "away",
            "point": 3.0,
            "price": -110.0,
            "sportsbook": "DraftKings",
            "rawProbability": 0.57,
            "calibratedProbability": 0.59,
            "pushProbability": 0.02,
            "lossProbability": 0.39,
            "rawEdge": 0.032,
            "calibratedEdge": 0.041,
            "currentEV": 0.054,
            "fairLine": -128.0,
            "truePlayableTo": -118.0,
            "truePlayableToStatus": "AVAILABLE",
            "siScore": 80.0,
            "siGrade": "A-",
            "siRank": 1,
            "recommendation": "BET",
            "qualificationStatus": "QUALIFIED",
            "qualificationReasons": ["edge", "ev"],
            "oddsProvider": "line_movement_board",
            "oddsTimestamp": "2026-09-13T07:00:00+00:00",
            "modelTimestamp": "2026-09-13T06:58:00+00:00",
            "marketTimestamp": "2026-09-13T07:00:00+00:00",
            "sourceSnapshotId": "source-1",
        },
        publication_type="SIA_3",
    )
    dl.publish_sia3(
        {
            "publicationType": "SIA_3",
            "publishedAtUTC": "2026-09-13T07:02:00+00:00",
            "season": 2026,
            "week": 1,
            "isOfficial": True,
            "slots": [
                {"decisionId": decision["decisionId"], "slotLabel": "BET", "qualificationStatus": "QUALIFIED"},
                {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
                {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
            ],
        }
    )

    missing_score = dl.run_official_postgame_lifecycle(fetch_scores_fn=lambda event_id: None)
    assert missing_score["settled"] == 0
    assert missing_score["skipped"]["missingFinalScore"] == 1

    with patch.object(dl, "get_closing_line") as mocked_closing:
        mocked_closing.return_value = type(
            "C",
            (),
            {
                "closing_status": "NOT_CAPTURED",
                "closing_point": None,
                "closing_price": None,
                "closing_timestamp": None,
            },
        )()
        missing_close = dl.run_official_postgame_lifecycle(
            fetch_scores_fn=lambda event_id: {
                "status": "FINAL",
                "finalAwayScore": 24,
                "finalHomeScore": 20,
                "sourceSnapshotId": "score-1",
            }
        )

    assert missing_close["settled"] == 1
    assert missing_close["clvPending"] == 1
    assert missing_close["closingLineMissing"] == 1


def test_duplicate_scheduler_execution_and_automation_exception_safe(monkeypatch, tmp_path: Path):
    summary = run_week1_full_lifecycle_certification(monkeypatch, tmp_path)
    assert summary["ticks"]["t2"]["providerRequests"] == 0
    assert summary["ticks"]["t4"]["providerRequests"] == 0
    assert summary["ticks"]["t6"]["providerRequests"] == 0
    assert summary["postgame"]["run2"]["settled"] == 0

    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    with patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", side_effect=RuntimeError("pregame exploded")):
        out = orch._run_pregame_automation_tick()

    assert out["status"] == "ERROR"
    assert out["providerRequests"] == 0