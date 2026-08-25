from __future__ import annotations

from datetime import datetime, timezone

from app.services.decision_board import build_decision_board_payload, map_game_card_status


def _base_opp(**overrides):
    base = {
        "rank": 1,
        "eventId": "evt-1",
        "market": "spread",
        "marketType": "SPREAD",
        "pick": "BUF -3.5",
        "book": "FanDuel",
        "side": "away",
        "point": -3.5,
        "price": -105,
        "bestAvailableLine": -3.5,
        "bestAvailablePrice": -105,
        "truePlayableTo": -4.5,
        "playableTo": -4.5,
        "currentWinProbability": 0.58,
        "marketNoVigProbability": 0.52,
        "impliedProbability": 52.4,
        "edge": 6.0,
        "currentEV": 0.084,
        "confidence": 72,
        "booksTracked": 4,
        "commenceTime": "2026-09-10T17:00:00+00:00",
        "recommendation": "BET",
        "qualificationStatus": "QUALIFIED",
        "productionEligible": True,
        "marketValidationStatus": "PRODUCTION_VALIDATED",
        "marketDataStatus": "LIVE",
        "marketLastUpdated": "2026-09-10T16:57:00+00:00",
        "minimumPlayableEV": 0.0,
        "injuryContext": {"summary": "No major injuries"},
    }
    base.update(overrides)
    return base


def test_only_production_eligible_enter_official_board():
    opportunities = [
        _base_opp(eventId="evt-spread", productionEligible=True, qualificationStatus="QUALIFIED", marketType="SPREAD"),
        _base_opp(eventId="evt-tt", productionEligible=False, qualificationStatus="QUALIFIED", marketType="TEAM_TOTAL", market="team_total"),
    ]

    payload = build_decision_board_payload(opportunities, limit=3)

    assert payload["count"] == 1
    assert payload["decisionBoard"][0]["eventId"] == "evt-spread"
    assert payload["officialMarketsDisplayed"] == ["SPREAD"]


def test_zero_qualifying_opportunities_yields_no_bet_state():
    opportunities = [
        _base_opp(qualificationStatus="NOT_QUALIFIED", recommendation="WATCH"),
    ]

    payload = build_decision_board_payload(opportunities, limit=3)

    assert payload["count"] == 0
    assert payload["noBetState"] is not None
    assert "NO HIGH-CONVICTION BETS" in payload["noBetState"]["headline"]


def test_zero_qualifying_opportunities_exposes_closest_opportunity_contract():
    opportunities = [
        _base_opp(
            qualificationStatus="NOT_QUALIFIED",
            recommendation="WATCH",
            eventId="evt-watch",
            pick="BUF -4",
            side="away",
            marketType="SPREAD",
        ),
    ]

    payload = build_decision_board_payload(opportunities, limit=3)
    closest = payload["noBetState"]["closestOpportunity"]

    assert closest is not None
    assert closest["eventId"] == "evt-watch"
    assert closest["selection"] == "BUF -4"
    assert closest["distanceFromTrigger"] is not None


def test_fewer_than_three_not_padded_and_order_preserved():
    opportunities = [
        _base_opp(rank=2, eventId="evt-2", pick="A"),
        _base_opp(rank=1, eventId="evt-1", pick="B"),
    ]

    payload = build_decision_board_payload(opportunities, limit=3)

    assert payload["count"] == 2
    assert [r["eventId"] for r in payload["decisionBoard"]] == ["evt-1", "evt-2"]


def test_shadow_markets_do_not_leak_even_if_qualified():
    opportunities = [
        _base_opp(eventId="evt-spread", marketType="SPREAD", productionEligible=True, qualificationStatus="QUALIFIED"),
        _base_opp(eventId="evt-prop", marketType="PLAYER_PROP", market="player_prop", productionEligible=False, qualificationStatus="QUALIFIED"),
        _base_opp(eventId="evt-1h", marketType="FIRST_HALF_SPREAD", market="first_half_spread", productionEligible=False, qualificationStatus="QUALIFIED"),
    ]

    payload = build_decision_board_payload(opportunities, limit=3)
    ids = [row["eventId"] for row in payload["decisionBoard"]]

    assert "evt-spread" in ids
    assert "evt-prop" not in ids
    assert "evt-1h" not in ids


def test_best_executable_quote_renders_from_line_shopping():
    opportunities = [_base_opp()]

    def fake_line_shopping(_opp):
        return {
            "bestMarketQuote": {
                "point": -3.5,
                "americanPrice": -105,
                "sportsbook": "FanDuel",
                "quoteFreshness": "FRESH",
            },
            "bestPlayableQuote": {
                "point": -3.0,
                "americanPrice": -110,
                "sportsbook": "DraftKings",
                "quoteFreshness": "FRESH",
            },
            "marketDepth": {"marketDepthStatus": "DEEP", "bookCount": 7},
            "status": "OK",
        }

    payload = build_decision_board_payload(opportunities, line_shopping_fn=fake_line_shopping)
    row = payload["decisionBoard"][0]

    assert row["line"] == -3.0
    assert row["price"] == -110
    assert row["sportsbook"] == "DraftKings"
    assert row["bestAvailableLine"] == -3.5
    assert row["bestAvailableSportsbook"] == "FanDuel"


def test_stale_quote_and_limited_depth_warnings():
    opportunities = [_base_opp(booksTracked=1, marketLastUpdated="2026-09-10T10:00:00+00:00")]

    payload = build_decision_board_payload(opportunities, now_utc=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc))
    row = payload["decisionBoard"][0]

    assert row["quoteWarnings"]["isStale"] is True
    assert row["quoteWarnings"]["limitedDepth"] is True


def test_playable_to_and_optional_fields_do_not_crash():
    opportunities = [
        _base_opp(
            truePlayableTo=None,
            playableTo=None,
            currentWinProbability=None,
            marketNoVigProbability=None,
            currentEV=None,
            edge=None,
        )
    ]

    payload = build_decision_board_payload(opportunities)
    row = payload["decisionBoard"][0]

    assert row["playableTo"] is None
    assert row["modelProbability"] is not None or row["modelProbability"] is None
    assert isinstance(row["whySiaLikesIt"], str)
    assert len(row["whySiaLikesIt"]) > 0


def test_game_card_status_mapping():
    assert map_game_card_status({"productionEligible": True, "qualificationStatus": "QUALIFIED", "marketDataStatus": "LIVE"}) == "SIA PLAY"
    assert map_game_card_status({"productionEligible": True, "qualificationStatus": "NOT_QUALIFIED", "recommendation": "LEAN", "marketDataStatus": "LIVE"}) == "LEAN"
    assert map_game_card_status({"recommendation": "WATCH", "marketDataStatus": "LIVE"}) == "WATCH"
    assert map_game_card_status({"marketDataStatus": "STALE"}) == "MARKET DATA LIMITED"
    assert map_game_card_status({"marketDataStatus": "LIVE"}) == "NO EDGE"


def test_market_family_firewalls_and_universal_disabled():
    opportunities = [
        _base_opp(eventId="evt-spread", marketType="SPREAD", productionEligible=True, qualificationStatus="QUALIFIED"),
        _base_opp(eventId="evt-prop", marketType="PLAYER_PROP", productionEligible=False, qualificationStatus="QUALIFIED"),
        _base_opp(eventId="evt-tt", marketType="TEAM_TOTAL", productionEligible=False, qualificationStatus="QUALIFIED"),
        _base_opp(eventId="evt-1h", marketType="FIRST_HALF_TOTAL", productionEligible=False, qualificationStatus="QUALIFIED"),
    ]
    payload = build_decision_board_payload(opportunities)

    assert payload["officialMarketsDisplayed"] == ["SPREAD"]
    assert payload["crossMarketComparable"] is False
    assert payload["universalSia3"] == "DISABLED"
