from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services import shadow_markets
from research import sia_team_total_phase1_validation as tt


def _sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": [2024, 2024, 2024, 2024],
            "week": [1, 2, 3, 4],
            "game_id": ["g1", "g2", "g3", "g4"],
            "home_team": ["H1", "H2", "H3", "H4"],
            "away_team": ["A1", "A2", "A3", "A4"],
            "home_score": [24, 21, 17, 30],
            "away_score": [20, 24, 14, 27],
            "model_margin": [3, -2, 4, 3],
            "model_total": [44, 45, 31, 57],
            "spread_line": [3.0, -2.5, 4.0, 2.5],
            "total_line": [44.0, 45.0, 31.0, 57.0],
        }
    )


def test_margin_sign_convention_home_positive():
    frame = _sample_frame()
    conv = tt.infer_margin_sign_convention(frame)
    assert conv.label == "POSITIVE_MODEL_MARGIN_MEANS_HOME_FAVORED"
    assert conv.margin_sign == 1


def test_implied_score_invariants():
    home, away = tt.derive_implied_team_scores(45.0, 3.0, 1)
    assert abs((home + away) - 45.0) < 1e-9
    assert abs((home - away) - 3.0) < 1e-9


def test_non_finite_rejection():
    with pytest.raises(ValueError):
        tt.derive_implied_team_scores(float("nan"), 2.0, 1)


def test_missing_data_rejection_counts():
    frame = _sample_frame().copy()
    frame.loc[0, "model_total"] = np.nan
    conv = tt.infer_margin_sign_convention(frame.fillna(0))
    dataset, exclusions = tt.build_team_total_research_dataset(frame, conv)
    assert exclusions["missing_required_field"] + exclusions["non_finite_projection"] >= 1
    assert len(dataset) == len(frame) - 1


def test_leakage_safe_ordering():
    frame = _sample_frame().iloc[[3, 1, 0, 2]].copy()
    conv = tt.infer_margin_sign_convention(frame)
    dataset, _ = tt.build_team_total_research_dataset(frame, conv)
    keys = list(dataset.apply(lambda r: (int(r["season"]), int(r["week"]), str(r["eventId"])), axis=1))
    assert keys == sorted(keys)


def test_residual_calculation():
    frame = _sample_frame()
    conv = tt.infer_margin_sign_convention(frame)
    dataset, _ = tt.build_team_total_research_dataset(frame, conv)
    r0 = dataset.iloc[0]
    assert abs(r0["homeResidual"] - (r0["actualHomePoints"] - r0["projectedHomePoints"])) < 1e-9
    assert abs(r0["awayResidual"] - (r0["actualAwayPoints"] - r0["projectedAwayPoints"])) < 1e-9


def test_empirical_probability_sum_and_push_behavior():
    frame = pd.DataFrame(
        {
            "season": [2024] * 60,
            "week": list(range(1, 61)),
            "game_id": [f"g{i}" for i in range(60)],
            "home_team": ["H"] * 60,
            "away_team": ["A"] * 60,
            "home_score": [24, 21, 20, 23, 27] * 12,
            "away_score": [20, 24, 21, 20, 24] * 12,
            "model_margin": [3, -2, -1, 3, 3] * 12,
            "model_total": [44, 45, 41, 43, 51] * 12,
            "spread_line": [3.0, -2.5, -1.0, 3.0, 3.0] * 12,
            "total_line": [44.0, 45.0, 41.0, 43.0, 51.0] * 12,
        }
    )
    conv = tt.infer_margin_sign_convention(frame)
    dataset, _ = tt.build_team_total_research_dataset(frame, conv)
    method_pack = tt.fit_residual_methods(dataset)
    residuals = pd.concat([dataset["homeResidual"], dataset["awayResidual"]], ignore_index=True).to_numpy(float)

    int_probs = tt.team_total_probability(24.0, 24.0, method_pack, residuals)
    half_probs = tt.team_total_probability(24.0, 24.5, method_pack, residuals)

    assert abs((int_probs["over"] + int_probs["push"] + int_probs["under"]) - 1.0) < 1e-9
    assert int_probs["push"] > 0.0
    assert abs((half_probs["over"] + half_probs["push"] + half_probs["under"]) - 1.0) < 1e-9
    assert half_probs["push"] == 0.0


def test_over_under_complement_on_half_point():
    frame = _sample_frame()
    conv = tt.infer_margin_sign_convention(frame)
    dataset, _ = tt.build_team_total_research_dataset(frame, conv)
    method_pack = {"selected": "EMPIRICAL", "methods": {}}
    residuals = pd.concat([dataset["homeResidual"], dataset["awayResidual"]], ignore_index=True).to_numpy(float)
    probs = tt.team_total_probability(22.0, 22.5, method_pack, residuals)
    assert abs((probs["over"] + probs["under"]) - 1.0) < 1e-9


def test_fair_price_integration():
    frame = _sample_frame()
    conv = tt.infer_margin_sign_convention(frame)
    dataset, _ = tt.build_team_total_research_dataset(frame, conv)
    pack = {"selected": "EMPIRICAL", "methods": {}}
    residuals = pd.concat([dataset["homeResidual"], dataset["awayResidual"]], ignore_index=True).to_numpy(float)
    probs = tt.team_total_probability(23.0, 23.0, pack, residuals)
    win_prob = probs["over"]
    fair = tt.fair_price_from_win_push(win_prob, probs["push"])
    assert fair is not None


def test_walk_forward_is_explicit_when_lines_unavailable():
    frame = _sample_frame()
    conv = tt.infer_margin_sign_convention(frame)
    dataset, _ = tt.build_team_total_research_dataset(frame, conv)
    out = tt.walk_forward_validation(dataset, {"selected": "EMPIRICAL", "methods": {}})
    assert out["status"] == "INSUFFICIENT_DATA"
    assert out["brier"] is None


@pytest.fixture
def shadow_db(monkeypatch, tmp_path):
    db = tmp_path / "shadow_tt_phase1.sqlite"
    monkeypatch.setattr(shadow_markets, "_DB_PATH", db)
    shadow_markets._ensure_schema()
    return db


def test_live_team_total_mapping_and_firewalls(shadow_db):
    con = sqlite3.connect(str(shadow_db))
    con.execute(
        """
        INSERT INTO shadow_market_snapshots (
            snapshot_id, captured_at_utc, event_id, provider_event_id,
            market_family, market_key, phase, period, game_state_timestamp,
            team_code, selection, side, line, price, bookmaker,
            market_timestamp, fetched_at, source_snapshot_id,
            book_coverage_count, available_books, best_price_book,
            consensus_available, market_depth_status,
            payload_hash, canonical_payload, idempotency_key
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            "snap-1",
            "2026-08-19T00:00:00+00:00",
            "evt-1",
            "evt-1",
            "TEAM_TOTAL",
            "team_totals",
            "PREGAME",
            "FULL_GAME",
            None,
            "BUF",
            "BUF over 20.5",
            "over",
            20.5,
            -110,
            "fanduel",
            "2026-08-19T00:00:00+00:00",
            "2026-08-19T00:00:00+00:00",
            "src-1",
            1,
            "[\"fanduel\"]",
            "fanduel",
            0,
            "SINGLE_BOOK",
            "h",
            "{}",
            "idem-1",
        ],
    )
    con.commit()
    con.close()

    frame = pd.DataFrame(
        {
            "season": [2024] * 80,
            "week": list(range(1, 81)),
            "game_id": [f"g{i}" for i in range(80)],
            "home_team": ["H"] * 80,
            "away_team": ["A"] * 80,
            "home_score": [24, 21, 20, 23] * 20,
            "away_score": [20, 24, 21, 20] * 20,
            "model_margin": [3, -2, -1, 3] * 20,
            "model_total": [44, 45, 41, 43] * 20,
            "spread_line": [3.0, -2.5, -1.0, 3.0] * 20,
            "total_line": [44.0, 45.0, 41.0, 43.0] * 20,
        }
    )
    conv = tt.infer_margin_sign_convention(frame)
    dataset, _ = tt.build_team_total_research_dataset(frame, conv)
    method_pack = tt.fit_residual_methods(dataset)
    result = tt.live_team_total_mapping_check(dataset, method_pack)

    assert result["status"] == "PASS"
    assert result["rowsMappingCompatible"] >= 1

    assert shadow_markets.PHASE2B_MARKET_FAMILIES["TEAM_TOTAL"]["productionEligible"] is False
    assert shadow_markets.PHASE2B_MARKET_FAMILIES["TEAM_TOTAL"]["shadowEligible"] is False
    assert shadow_markets.PHASE2B_MARKET_FAMILIES["FIRST_HALF_SPREAD"]["shadowEligible"] is False


def test_production_spread_behavior_unchanged():
    assert shadow_markets._shadow_recommendation_eligible_for_market("spread") is True
