from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import shadow_markets


@pytest.fixture
def shadow_db(monkeypatch, tmp_path: Path):
    db = tmp_path / "line_shopping.sqlite"
    monkeypatch.setattr(shadow_markets, "_DB_PATH", db)
    shadow_markets._ensure_schema()
    return db


def _base_row(**overrides):
    row = {
        "season": 2026,
        "week": 1,
        "eventId": "2026_01_AWAY_HOME",
        "providerEventId": "2026_01_AWAY_HOME",
        "commenceTime": "2026-09-10T17:00:00+00:00",
        "marketFamily": "SPREAD",
        "marketKey": "spread",
        "phase": "PREGAME",
        "period": "FULL_GAME",
        "teamCode": "AWAY",
        "selection": "AWAY +3",
        "side": "away",
        "line": 3.0,
        "price": -110.0,
        "sportsbook": "DraftKings",
        "bookmakerKey": "draftkings",
        "marketTimestamp": "2026-09-10T16:58:00+00:00",
        "fetchedAt": "2026-09-10T16:58:10+00:00",
        "sourceSnapshotId": "src-1",
        "bookCoverageCount": 1,
        "availableBooks": ["DraftKings"],
        "marketDepthStatus": "SINGLE_BOOK",
        "allBooks": [{"book": "DraftKings", "line": 3.0, "price": -110.0}],
        "bestPrice": -110.0,
        "bestPriceBook": "DraftKings",
        "consensusLine": None,
        "medianLine": 3.0,
        "projectedGameTotal": None,
        "projectedHomeMargin": None,
        "derivedProjectedHomePoints": None,
        "derivedProjectedAwayPoints": None,
        "selectedTeamProjectedPoints": None,
        "rawProbability": None,
        "calibratedProbability": None,
        "pushProbability": None,
        "lossProbability": None,
        "marketImpliedProbability": 0.5238,
        "marketNoVigProbability": None,
        "edge": None,
        "ev": None,
        "fairValue": None,
        "playableTo": None,
        "siScore": None,
        "marketRank": None,
        "globalResearchScore": None,
        "globalResearchRank": None,
        "productionEligible": False,
        "crossMarketComparable": False,
        "marketValidationStatus": "UNAVAILABLE_TWO_SIDED_MARKET",
        "modelState": "MODEL_BACKED",
        "shadowRecommendations": "DISABLED",
        "modelVersion": "model",
        "probabilityEngineVersion": "engine",
        "calibrationVersion": "cal",
        "rankingVersion": "rank",
        "qualificationPolicyVersion": "qual",
        "gitCommitHash": "git",
        "gameStateTimestamp": None,
        "gameQuarter": None,
        "gameClock": None,
        "possession": None,
    }
    row.update(overrides)
    return row


def _insert_rows(rows):
    out = shadow_markets._capture_prospective_rows(rows)
    assert out["rowsReceived"] == len(rows)


def test_spread_point_first_comparison():
    a = shadow_markets._line_shopping_sort_key("spread", "away", 3.5, -115)
    b = shadow_markets._line_shopping_sort_key("spread", "away", 3.0, -105)
    assert a > b


def test_spread_equal_point_price_comparison():
    a = shadow_markets._line_shopping_sort_key("spread", "away", 3.0, -105)
    b = shadow_markets._line_shopping_sort_key("spread", "away", 3.0, -115)
    assert a > b


def test_moneyline_positive_and_negative_odds_comparison():
    plus_best = shadow_markets._line_shopping_sort_key("moneyline", "away", None, 140)
    plus_worse = shadow_markets._line_shopping_sort_key("moneyline", "away", None, 125)
    assert plus_best > plus_worse

    neg_best = shadow_markets._line_shopping_sort_key("moneyline", "away", None, -105)
    neg_worse = shadow_markets._line_shopping_sort_key("moneyline", "away", None, -120)
    assert neg_best > neg_worse


def test_total_and_team_total_direction_rules():
    over_better = shadow_markets._line_shopping_sort_key("total", "over", 45.0, -110)
    over_worse = shadow_markets._line_shopping_sort_key("total", "over", 45.5, -105)
    assert over_better > over_worse

    under_better = shadow_markets._line_shopping_sort_key("total", "under", 46.0, -110)
    under_worse = shadow_markets._line_shopping_sort_key("total", "under", 45.5, -105)
    assert under_better > under_worse

    tt_over_better = shadow_markets._line_shopping_sort_key("team_total", "over", 20.5, -112)
    tt_over_worse = shadow_markets._line_shopping_sort_key("team_total", "over", 21.0, -105)
    assert tt_over_better > tt_over_worse


def test_first_half_direction_rules():
    spread_better = shadow_markets._line_shopping_sort_key("first_half_spread", "away", 1.5, -110)
    spread_worse = shadow_markets._line_shopping_sort_key("first_half_spread", "away", 1.0, -105)
    assert spread_better > spread_worse

    total_better = shadow_markets._line_shopping_sort_key("first_half_total", "under", 24.0, -110)
    total_worse = shadow_markets._line_shopping_sort_key("first_half_total", "under", 23.5, -105)
    assert total_better > total_worse


def test_best_market_and_best_playable_quote_selection(shadow_db):
    now = datetime.now(timezone.utc)
    rows = [
        _base_row(
            sportsbook="FanDuel",
            bookmakerKey="fanduel",
            line=3.5,
            price=-115,
            marketTimestamp=(now - timedelta(seconds=30)).isoformat(),
            selection="AWAY +3.5",
        ),
        _base_row(
            sportsbook="DraftKings",
            bookmakerKey="draftkings",
            line=3.0,
            price=-105,
            marketTimestamp=(now - timedelta(seconds=40)).isoformat(),
            selection="AWAY +3",
        ),
    ]
    _insert_rows(rows)

    out = shadow_markets.line_shopping_market_view(
        event_id="2026_01_AWAY_HOME",
        market_family="SPREAD",
        side="away",
        playable_to_line=3.0,
    )
    assert out["bestMarketQuote"]["sportsbook"] == "FanDuel"
    assert out["bestPlayableQuote"]["sportsbook"] == "FanDuel"
    assert out["playableBookCount"] >= 1


def test_playable_to_rejection_and_no_executable_price(shadow_db):
    now = datetime.now(timezone.utc)
    rows = [
        _base_row(
            line=-4.5,
            side="home",
            selection="HOME -4.5",
            sportsbook="Caesars",
            bookmakerKey="caesars",
            marketTimestamp=(now - timedelta(seconds=20)).isoformat(),
        )
    ]
    _insert_rows(rows)

    out = shadow_markets.line_shopping_market_view(
        event_id="2026_01_AWAY_HOME",
        market_family="SPREAD",
        side="home",
        playable_to_line=-4.0,
    )
    assert out["status"] == "NO_EXECUTABLE_PRICE"
    assert out["bestMarketQuote"] is not None
    assert out["bestPlayableQuote"] is None


def test_stale_quote_rejection_for_executable(shadow_db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("PREGAME_QUOTE_FRESH_SECONDS", "60")
    monkeypatch.setenv("PREGAME_QUOTE_STALE_SECONDS", "120")

    rows = [
        _base_row(
            sportsbook="BookA",
            bookmakerKey="draftkings",
            line=3.0,
            price=-105,
            marketTimestamp=(now - timedelta(seconds=200)).isoformat(),
            selection="AWAY +3",
        )
    ]
    _insert_rows(rows)

    out = shadow_markets.line_shopping_market_view(
        event_id="2026_01_AWAY_HOME",
        market_family="SPREAD",
        side="away",
        playable_to_line=2.5,
    )
    assert out["status"] == "NO_EXECUTABLE_PRICE"
    assert out["bestMarketQuote"]["quoteFreshness"] == "STALE"


def test_book_normalization():
    key = shadow_markets._normalize_bookmaker_key("DK")
    display = shadow_markets._normalize_bookmaker_display("", key)
    assert key == "draftkings"
    assert display == "DraftKings"


def test_market_depth_consensus_median_and_moneyline_point_none(shadow_db):
    now = datetime.now(timezone.utc)
    rows = [
        _base_row(
            marketFamily="MONEYLINE",
            marketKey="moneyline",
            side="away",
            teamCode="AWAY",
            selection="AWAY",
            line=None,
            price=140,
            sportsbook="BookA",
            bookmakerKey="fanduel",
            marketTimestamp=(now - timedelta(seconds=20)).isoformat(),
        ),
        _base_row(
            marketFamily="MONEYLINE",
            marketKey="moneyline",
            side="away",
            teamCode="AWAY",
            selection="AWAY",
            line=None,
            price=130,
            sportsbook="BookB",
            bookmakerKey="draftkings",
            marketTimestamp=(now - timedelta(seconds=25)).isoformat(),
        ),
    ]
    _insert_rows(rows)

    out = shadow_markets.line_shopping_market_view(
        event_id="2026_01_AWAY_HOME",
        market_family="MONEYLINE",
        side="away",
        playable_to_price=118,
    )
    assert out["marketDepth"]["bookCount"] == 2
    assert out["marketDepth"]["consensusLine"] is None
    assert out["marketDepth"]["medianLine"] is None
    assert out["bestMarketQuote"]["point"] is None


def test_line_shopping_value_metrics_present(shadow_db):
    now = datetime.now(timezone.utc)
    rows = [
        _base_row(
            line=3.5,
            price=-115,
            sportsbook="BookA",
            bookmakerKey="fanduel",
            marketTimestamp=(now - timedelta(seconds=20)).isoformat(),
            selection="AWAY +3.5",
        ),
        _base_row(
            line=3.0,
            price=-105,
            sportsbook="BookB",
            bookmakerKey="draftkings",
            marketTimestamp=(now - timedelta(seconds=21)).isoformat(),
            selection="AWAY +3",
        ),
        _base_row(
            line=3.0,
            price=-110,
            sportsbook="BookC",
            bookmakerKey="betmgm",
            marketTimestamp=(now - timedelta(seconds=22)).isoformat(),
            selection="AWAY +3",
        ),
    ]
    _insert_rows(rows)

    out = shadow_markets.line_shopping_market_view(
        event_id="2026_01_AWAY_HOME",
        market_family="SPREAD",
        side="away",
        playable_to_line=2.5,
    )
    value = out["lineShoppingValue"]
    assert value["lineImprovement"] is not None
    assert value["priceImprovement"] is not None
    assert value["impliedProbabilityImprovement"] is not None


def test_sportsbook_coverage_audit_from_local_snapshots(shadow_db):
    rows = [
        _base_row(marketFamily="SPREAD", marketKey="spread", sportsbook="BookA", bookmakerKey="draftkings"),
        _base_row(marketFamily="MONEYLINE", marketKey="moneyline", sportsbook="BookA", bookmakerKey="draftkings", line=None),
        _base_row(marketFamily="TOTAL", marketKey="total", sportsbook="BookA", bookmakerKey="draftkings", side="over", selection="OVER 45.5"),
        _base_row(marketFamily="TEAM_TOTAL", marketKey="team_total", sportsbook="BookA", bookmakerKey="draftkings", side="over", selection="AWAY OVER 21.5", modelState="RESEARCH_ONLY"),
        _base_row(marketFamily="FIRST_HALF_SPREAD", marketKey="first_half_spread", sportsbook="BookA", bookmakerKey="draftkings", period="FIRST_HALF"),
        _base_row(marketFamily="FIRST_HALF_MONEYLINE", marketKey="first_half_moneyline", sportsbook="BookA", bookmakerKey="draftkings", period="FIRST_HALF", line=None),
        _base_row(marketFamily="FIRST_HALF_TOTAL", marketKey="first_half_total", sportsbook="BookA", bookmakerKey="draftkings", period="FIRST_HALF", side="over", selection="OVER 23.5"),
    ]
    _insert_rows(rows)

    audit = shadow_markets.sportsbook_coverage_audit()
    assert audit["status"] == "PASS"
    assert audit["markets"]["SPREAD"]["eventsSampled"] >= 1


def test_sportsbook_coverage_audit_provider_fallback_requires_opt_in(shadow_db, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "present")

    called = {"sport": 0, "events": 0, "eventOdds": 0}

    def _sport(*args, **kwargs):
        called["sport"] += 1
        raise AssertionError("sport-wide provider call must not run without explicit opt-in")

    def _events(*args, **kwargs):
        called["events"] += 1
        raise AssertionError("events provider call must not run without explicit opt-in")

    def _event_odds(*args, **kwargs):
        called["eventOdds"] += 1
        raise AssertionError("event odds provider call must not run without explicit opt-in")

    monkeypatch.setattr(shadow_markets, "_call_odds_api", _sport)
    monkeypatch.setattr(shadow_markets, "_call_odds_api_events", _events)
    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _event_odds)

    out = shadow_markets.sportsbook_coverage_audit(provider_opt_in=False)
    assert out["status"] in {"PASS", "FAIL"}
    assert called == {"sport": 0, "events": 0, "eventOdds": 0}


def test_canonical_quote_contract_and_live_future_compatibility():
    contract = shadow_markets.canonical_quote_contract()
    assert "eventId" in contract["fields"]
    assert "americanPrice" in contract["fields"]

    live = shadow_markets.live_sia_future_schema_compatibility()
    assert live["phaseLiveSupported"] is True
    assert live["identityUnchanged"] is True


def test_production_guardrails_unchanged():
    assert shadow_markets._shadow_recommendation_eligible_for_market("team_total") is False
    assert shadow_markets._shadow_recommendation_eligible_for_market("first_half_spread") is False
    assert shadow_markets._shadow_recommendation_eligible_for_market("first_half_moneyline") is False
    assert shadow_markets._shadow_recommendation_eligible_for_market("first_half_total") is False
    assert shadow_markets.PHASE2B_MARKET_FAMILIES["TEAM_TOTAL"]["productionEligible"] is False
