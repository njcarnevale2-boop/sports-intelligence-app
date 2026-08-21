from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import shadow_markets


@pytest.fixture
def shadow_db(monkeypatch, tmp_path: Path):
    db = tmp_path / "player_props.sqlite"
    monkeypatch.setattr(shadow_markets, "_DB_PATH", db)
    shadow_markets._ensure_schema()
    return db


def _read_prop_rows(db: Path):
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM player_prop_market_snapshots ORDER BY id ASC").fetchall()
    con.close()
    return rows


def test_player_name_normalization_and_suffixes():
    assert shadow_markets._normalize_player_name("Odell Beckham Jr.") == "ODELL BECKHAM"
    assert shadow_markets._normalize_player_name("Amon-Ra St. Brown") == "AMON RA ST BROWN"
    assert shadow_markets._normalize_player_name("D'Andre Swift") == "D ANDRE SWIFT"


def test_ambiguous_player_rejection(monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_load_canonical_player_index",
        lambda: [
            {"playerId": "1", "playerName": "Josh Allen", "normalizedPlayerName": "JOSH ALLEN", "team": "BUF", "position": "QB"},
            {"playerId": "2", "playerName": "Josh Allen", "normalizedPlayerName": "JOSH ALLEN", "team": "JAX", "position": "EDGE"},
        ],
    )
    out = shadow_markets._resolve_player_identity("Josh Allen", None)
    assert out["matchStatus"] == "AMBIGUOUS"
    assert out["canonicalPlayerId"] is None


def test_identity_uses_provider_player_id_first(monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_load_canonical_player_index",
        lambda: [
            {"playerId": "p-17", "playerName": "Josh Allen", "normalizedPlayerName": "JOSH ALLEN", "team": "BUF", "position": "QB"},
            {"playerId": "p-21", "playerName": "Josh Allen", "normalizedPlayerName": "JOSH ALLEN", "team": "JAX", "position": "EDGE"},
        ],
    )
    out = shadow_markets._resolve_player_identity("Josh Allen", None, provider_player_id="p-17")
    assert out["matchStatus"] == "EXACT"
    assert out["canonicalPlayerId"] == "p-17"
    assert out["reason"] == "PROVIDER_PLAYER_ID"


def test_identity_event_team_context_disambiguates(monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_load_canonical_player_index",
        lambda: [
            {"playerId": "1", "playerName": "A.J. Brown", "normalizedPlayerName": "A J BROWN", "team": "TEN", "position": "WR"},
            {"playerId": "2", "playerName": "A.J. Brown", "normalizedPlayerName": "A J BROWN", "team": "PHI", "position": "WR"},
        ],
    )
    out = shadow_markets._resolve_player_identity(
        "A.J. Brown",
        None,
        event_team_codes={"PHI", "DAL"},
    )
    assert out["matchStatus"] == "EXACT"
    assert out["canonicalPlayerId"] == "2"
    assert out["reason"] == "EXACT_NAME_EVENT_TEAM_CONTEXT"


def test_identity_dedupes_historical_rows_by_player_id(monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_load_canonical_player_index",
        lambda: [
            {"playerId": "same-1", "playerName": "Christian McCaffrey", "normalizedPlayerName": "CHRISTIAN MCCAFFREY", "team": "CAR", "position": "RB"},
            {"playerId": "same-1", "playerName": "Christian McCaffrey", "normalizedPlayerName": "CHRISTIAN MCCAFFREY", "team": "SF", "position": "RB"},
        ],
    )
    out = shadow_markets._resolve_player_identity("Christian McCaffrey", None)
    assert out["matchStatus"] == "EXACT"
    assert out["canonicalPlayerId"] == "same-1"


def test_player_identity_uniqueness_and_prop_type_separation(shadow_db, monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_resolve_player_identity",
        lambda name, team, **kwargs: {
            "providerPlayerName": name,
            "normalizedPlayerName": "JOSH ALLEN",
            "matchStatus": "EXACT",
            "canonicalPlayerId": "BUF_QB_17",
            "canonicalPlayerName": "Josh Allen",
            "position": "QB",
            "team": "BUF",
            "opponent": "MIA",
        },
    )
    now = datetime.now(timezone.utc)
    discovery = {
        "eventSamples": [{"eventId": "evt-1", "commenceTime": (now + timedelta(hours=2)).isoformat()}],
        "eventPayloadById": {
            "evt-1": {
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "last_update": now.isoformat(),
                        "markets": [
                            {
                                "key": "player_pass_yds",
                                "last_update": now.isoformat(),
                                "outcomes": [
                                    {"name": "Over", "description": "Josh Allen", "point": 267.5, "price": -110},
                                ],
                            },
                            {
                                "key": "player_pass_tds",
                                "last_update": now.isoformat(),
                                "outcomes": [
                                    {"name": "Over", "description": "Josh Allen", "point": 1.5, "price": -105},
                                ],
                            },
                        ],
                    }
                ]
            }
        },
    }

    out = shadow_markets.ingest_player_prop_market_snapshots(discovery=discovery)
    assert out["currentInserted"] == 2

    rows = _read_prop_rows(shadow_db)
    assert len(rows) >= 4  # opening/current are always expected; closing depends on cutoff policy.
    states = {str(r["state_label"]) for r in rows}
    assert "OPENING" in states
    assert "CURRENT" in states
    prop_types = {str(r["prop_type"]) for r in rows}
    assert prop_types == {"PASSING_YARDS", "PASSING_TD"}


def test_over_under_direction_and_equal_point_price_comparison():
    over_better = shadow_markets._player_prop_sort_key("OVER", 67.5, -105)
    over_worse = shadow_markets._player_prop_sort_key("OVER", 68.5, -105)
    assert over_better > over_worse

    under_better = shadow_markets._player_prop_sort_key("UNDER", 68.5, -110)
    under_worse = shadow_markets._player_prop_sort_key("UNDER", 67.5, -110)
    assert under_better > under_worse

    eq_line_better_price = shadow_markets._player_prop_sort_key("OVER", 67.5, -102)
    eq_line_worse_price = shadow_markets._player_prop_sort_key("OVER", 67.5, -118)
    assert eq_line_better_price > eq_line_worse_price


def test_no_model_fields_fabricated_and_all_book_preserved(shadow_db, monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_resolve_player_identity",
        lambda name, team, **kwargs: {
            "providerPlayerName": name,
            "normalizedPlayerName": "JAHMYR GIBBS",
            "matchStatus": "NORMALIZED",
            "canonicalPlayerId": "DET_RB_26",
            "canonicalPlayerName": "Jahmyr Gibbs",
            "position": "RB",
            "team": "DET",
            "opponent": "GB",
        },
    )
    now = datetime.now(timezone.utc)
    discovery = {
        "eventSamples": [{"eventId": "evt-2", "commenceTime": (now + timedelta(hours=3)).isoformat()}],
        "eventPayloadById": {
            "evt-2": {
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "last_update": now.isoformat(),
                        "markets": [
                            {
                                "key": "player_rush_yds",
                                "last_update": now.isoformat(),
                                "outcomes": [
                                    {"name": "Over", "description": "Jahmyr Gibbs", "point": 65.5, "price": -110},
                                    {"name": "Under", "description": "Jahmyr Gibbs", "point": 65.5, "price": -110},
                                ],
                            }
                        ],
                    },
                    {
                        "key": "fanduel",
                        "last_update": now.isoformat(),
                        "markets": [
                            {
                                "key": "player_rush_yds",
                                "last_update": now.isoformat(),
                                "outcomes": [
                                    {"name": "Over", "description": "Jahmyr Gibbs", "point": 64.5, "price": -115},
                                    {"name": "Under", "description": "Jahmyr Gibbs", "point": 64.5, "price": -105},
                                ],
                            }
                        ],
                    },
                ]
            }
        },
    }

    out = shadow_markets.ingest_player_prop_market_snapshots(discovery=discovery)
    assert out["currentInserted"] == 4

    rows = _read_prop_rows(shadow_db)
    sample = rows[0]
    assert int(sample["model_available"]) == 0
    assert int(sample["model_validated"]) == 0
    assert int(sample["shadow_recommendation_eligible"]) == 0
    assert int(sample["production_eligible"]) == 0
    assert int(sample["cross_market_comparable"]) == 0
    assert str(sample["market_validation_status"]) == "DATA_COLLECTION_ONLY"


def test_opening_current_closing_and_no_post_kickoff_close(shadow_db, monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_resolve_player_identity",
        lambda name, team, **kwargs: {
            "providerPlayerName": name,
            "normalizedPlayerName": "A J BROWN",
            "matchStatus": "EXACT",
            "canonicalPlayerId": "PHI_WR_11",
            "canonicalPlayerName": "A.J. Brown",
            "position": "WR",
            "team": "PHI",
            "opponent": "DAL",
        },
    )
    now = datetime.now(timezone.utc)
    discovery = {
        "eventSamples": [{"eventId": "evt-3", "commenceTime": now.isoformat()}],
        "eventPayloadById": {
            "evt-3": {
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "last_update": (now + timedelta(minutes=1)).isoformat(),
                        "markets": [
                            {
                                "key": "player_reception_yds",
                                "last_update": (now + timedelta(minutes=1)).isoformat(),
                                "outcomes": [
                                    {"name": "Over", "description": "A.J. Brown", "point": 75.5, "price": -110},
                                ],
                            }
                        ],
                    }
                ]
            }
        },
    }

    out = shadow_markets.ingest_player_prop_market_snapshots(discovery=discovery)
    assert out["currentInserted"] == 1
    assert out["openingInserted"] == 1
    assert out["closingInserted"] == 0
    assert out["postKickoffRejectedCount"] == 1


def test_prop_two_sided_novig_and_single_sided_rejection():
    quotes = [
        {
            "side": "OVER",
            "point": 65.5,
            "price": -110,
            "bookmakerKey": "draftkings",
            "marketTimestamp": "2026-09-10T16:00:00+00:00",
        },
        {
            "side": "UNDER",
            "point": 65.5,
            "price": -110,
            "bookmakerKey": "draftkings",
            "marketTimestamp": "2026-09-10T16:00:00+00:00",
        },
    ]
    p, status = shadow_markets._player_prop_two_sided_no_vig(quotes, quotes[0])
    assert status == "AVAILABLE_TWO_SIDED_MARKET"
    assert p is not None

    p2, status2 = shadow_markets._player_prop_two_sided_no_vig(quotes[:1], quotes[0])
    assert p2 is None
    assert status2 == "UNAVAILABLE_TWO_SIDED_MARKET"


def test_grading_mapping_and_missing_stat_behavior(monkeypatch, tmp_path):
    # No DB present => all missing.
    monkeypatch.setattr(shadow_markets, "MODEL_ROOT", tmp_path / "missing-model")
    out = shadow_markets.player_prop_grading_source_audit()
    assert out["statusByPropType"]["PASSING_YARDS"] == "MISSING_STAT_SOURCE"
    assert out["statusByPropType"]["FIRST_TD"] == "MISSING_STAT_SOURCE"


def test_quota_accounting(monkeypatch):
    event_payload = {
        "bookmakers": [
            {
                "key": "draftkings",
                "last_update": "2026-09-10T15:55:00Z",
                "markets": [
                    {
                        "key": "player_pass_yds",
                        "last_update": "2026-09-10T15:55:00Z",
                        "outcomes": [
                            {"name": "Over", "description": "Josh Allen", "point": 265.5, "price": -110}
                        ],
                    }
                ],
            }
        ]
    }

    monkeypatch.setattr(
        shadow_markets,
        "_call_odds_api_events",
        lambda: (
            200,
            {"x-requests-remaining": "19990", "x-requests-used": "10", "x-requests-last": "1"},
            [{"id": "evt-q", "away_team": "A", "home_team": "B", "commence_time": "2026-09-10T17:00:00Z"}],
        ),
    )
    monkeypatch.setattr(
        shadow_markets,
        "_call_odds_api_event_odds",
        lambda event_id, markets: (
            200,
            {"x-requests-remaining": "19989", "x-requests-used": "11", "x-requests-last": "2"},
            event_payload,
        ),
    )

    out = shadow_markets.discover_player_props()
    assert out["status"] == "PASS"
    assert out["quotaTelemetry"]["eventsQueried"] == 1
    assert out["quotaTelemetry"]["marketsRequested"] == len(shadow_markets.PLAYER_PROP_TARGET_MARKETS)


def test_player_prop_coverage_report_ready(shadow_db, monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_resolve_player_identity",
        lambda name, team, **kwargs: {
            "providerPlayerName": name,
            "normalizedPlayerName": "JOSH ALLEN",
            "matchStatus": "EXACT",
            "canonicalPlayerId": "BUF_QB_17",
            "canonicalPlayerName": "Josh Allen",
            "position": "QB",
            "team": "BUF",
            "opponent": "MIA",
        },
    )
    now = datetime.now(timezone.utc)
    discovery = {
        "eventSamples": [{"eventId": "evt-r", "commenceTime": (now + timedelta(hours=2)).isoformat()}],
        "eventPayloadById": {
            "evt-r": {
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "last_update": now.isoformat(),
                        "markets": [
                            {
                                "key": "player_pass_yds",
                                "last_update": now.isoformat(),
                                "outcomes": [
                                    {"name": "Over", "description": "Josh Allen", "point": 265.5, "price": -110},
                                    {"name": "Under", "description": "Josh Allen", "point": 265.5, "price": -110},
                                ],
                            }
                        ],
                    }
                ]
            }
        },
    }
    shadow_markets.ingest_player_prop_market_snapshots(discovery=discovery)
    report = shadow_markets.player_prop_coverage_report()
    assert report["eventsCaptured"] >= 1
    assert report["quotesCaptured"] >= 2
    assert "identityMatchRates" in report


def test_production_firewall_and_live_compatibility():
    live = shadow_markets.live_sia_future_schema_compatibility()
    assert live["phaseLiveSupported"] is True
    assert live["identityUnchanged"] is True

    contract = shadow_markets.player_prop_market_contract()
    assert contract["modelFields"]["productionEligible"] is False
    assert contract["modelFields"]["crossMarketComparable"] is False


def test_mapping_plan_uses_event_team_context(monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_load_canonical_player_index",
        lambda: [
            {"playerId": "1", "playerName": "Kyle Williams", "normalizedPlayerName": "KYLE WILLIAMS", "team": "BUF", "position": "WR"},
            {"playerId": "2", "playerName": "Kyle Williams", "normalizedPlayerName": "KYLE WILLIAMS", "team": "SEA", "position": "WR"},
        ],
    )
    out = shadow_markets.player_identity_mapping_plan(
        [
            {
                "description": "Kyle Williams",
                "eventAwayTeam": "New England Patriots",
                "eventHomeTeam": "Seattle Seahawks",
            }
        ]
    )
    assert out["ambiguousCount"] == 0
    assert out["exactMatchRate"] == 1.0


def test_ingest_supports_fallback_event_market_payload_keys(shadow_db, monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_resolve_player_identity",
        lambda name, team, **kwargs: {
            "providerPlayerName": name,
            "normalizedPlayerName": "BROCK PURDY",
            "matchStatus": "EXACT",
            "canonicalPlayerId": "SF_QB_13",
            "canonicalPlayerName": "Brock Purdy",
            "position": "QB",
            "team": "SF",
            "opponent": "LAR",
            "reason": "EXACT_NAME",
        },
    )
    now = datetime.now(timezone.utc)
    discovery = {
        "eventSamples": [
            {
                "eventId": "evt-fallback",
                "awayTeam": "Los Angeles Rams",
                "homeTeam": "San Francisco 49ers",
                "commenceTime": (now + timedelta(hours=4)).isoformat(),
            }
        ],
        "eventPayloadById": {
            "evt-fallback:player_anytime_td": {
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "last_update": now.isoformat(),
                        "markets": [
                            {
                                "key": "player_anytime_td",
                                "last_update": now.isoformat(),
                                "outcomes": [
                                    {"name": "Brock Purdy", "price": 350},
                                ],
                            }
                        ],
                    }
                ]
            }
        },
    }

    out = shadow_markets.ingest_player_prop_market_snapshots(discovery=discovery)
    assert out["currentInserted"] >= 1

    rows = _read_prop_rows(shadow_db)
    assert any(str(r["prop_type"] or "") == "ANYTIME_TD" for r in rows)


def test_anytime_uses_description_player_name_not_yes_token(shadow_db, monkeypatch):
    monkeypatch.setattr(
        shadow_markets,
        "_resolve_player_identity",
        lambda name, team, **kwargs: {
            "providerPlayerName": name,
            "normalizedPlayerName": shadow_markets._normalize_player_name(name),
            "matchStatus": "EXACT" if name == "Brock Purdy" else "UNMATCHED",
            "canonicalPlayerId": "SF_QB_13" if name == "Brock Purdy" else None,
            "canonicalPlayerName": name if name == "Brock Purdy" else None,
            "position": "QB" if name == "Brock Purdy" else None,
            "team": "SF" if name == "Brock Purdy" else None,
            "opponent": "LAR" if name == "Brock Purdy" else None,
            "reason": "EXACT_NAME" if name == "Brock Purdy" else "NO_CANONICAL_MATCH",
        },
    )
    now = datetime.now(timezone.utc)
    discovery = {
        "eventSamples": [
            {
                "eventId": "evt-anytime",
                "awayTeam": "Los Angeles Rams",
                "homeTeam": "San Francisco 49ers",
                "commenceTime": (now + timedelta(hours=5)).isoformat(),
            }
        ],
        "eventPayloadById": {
            "evt-anytime": {
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "last_update": now.isoformat(),
                        "markets": [
                            {
                                "key": "player_anytime_td",
                                "last_update": now.isoformat(),
                                "outcomes": [
                                    {"name": "Yes", "description": "Brock Purdy", "price": 450},
                                ],
                            }
                        ],
                    }
                ]
            }
        },
    }

    out = shadow_markets.ingest_player_prop_market_snapshots(discovery=discovery)
    assert out["currentInserted"] >= 1

    rows = _read_prop_rows(shadow_db)
    matched = [r for r in rows if str(r["provider_player_name"] or "") == "Brock Purdy"]
    assert matched
