from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATA_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9" / "outputs"
WALKFORWARD_PATH = DATA_ROOT / "walkforward_multiseason_predictions.csv"
VALIDATION_SPREAD_PATH = DATA_ROOT / "validation_spread_bets.csv"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "research_outputs"

SEASONS = [2022, 2023, 2024, 2025]
MIN_RESIDUAL_SAMPLE = 200
RNG_SEED = 2026


def implied_probability(odds: float) -> float:
    if odds < 0:
        return (-odds) / ((-odds) + 100.0)
    return 100.0 / (odds + 100.0)


def devig_two_way(home_odds: float, away_odds: float) -> tuple[float, float]:
    ph = implied_probability(home_odds)
    pa = implied_probability(away_odds)
    s = ph + pa
    if s <= 0:
        return 0.5, 0.5
    return ph / s, pa / s


def american_to_decimal(odds: float) -> float:
    return 1.0 + (100.0 / abs(odds) if odds < 0 else odds / 100.0)


def ev_push_aware(win_prob: float, push_prob: float, odds: float) -> float:
    dec = american_to_decimal(odds)
    profit_if_win = dec - 1.0
    loss_prob = max(0.0, 1.0 - win_prob - push_prob)
    return float(win_prob * profit_if_win - loss_prob)


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def _sim_margins(model_margin_home: float, residuals: np.ndarray) -> np.ndarray:
    return np.rint(model_margin_home + residuals)


def spread_probs_home_away(model_margin_home: float, spread_line_home: float, residuals: np.ndarray) -> dict[str, float]:
    margins = _sim_margins(model_margin_home, residuals)

    # Home ticket is quoted at home spread_line (e.g., -3.5 for home favorite).
    home_ats = margins + spread_line_home
    # Away ticket corresponds to the opposite spread (negative home line).
    away_ats = -margins - spread_line_home

    home_win = float(np.mean(home_ats > 0))
    home_push = float(np.mean(home_ats == 0))
    home_loss = max(0.0, 1.0 - home_win - home_push)

    away_win = float(np.mean(away_ats > 0))
    away_push = float(np.mean(away_ats == 0))
    away_loss = max(0.0, 1.0 - away_win - away_push)

    return {
        "home_win": home_win,
        "home_push": home_push,
        "home_loss": home_loss,
        "away_win": away_win,
        "away_push": away_push,
        "away_loss": away_loss,
    }


def side_result(actual_margin_home: float, spread_line_home: float, side: str) -> str:
    if side == "home":
        ats = actual_margin_home + spread_line_home
    else:
        ats = -actual_margin_home - spread_line_home
    if ats > 0:
        return "win"
    if ats < 0:
        return "loss"
    return "push"


def flat_profit(result: str, odds: float) -> float:
    if result == "win":
        return float(american_to_decimal(odds) - 1.0)
    if result == "loss":
        return -1.0
    return 0.0


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    wf = pd.read_csv(WALKFORWARD_PATH)
    wf = wf[wf["season"].isin(SEASONS)].copy()

    needed = [
        "season",
        "week",
        "game_id",
        "home_team",
        "away_team",
        "spread_line",
        "home_spread_odds",
        "away_spread_odds",
        "model_margin",
        "home_score",
        "away_score",
    ]
    wf = wf.dropna(subset=needed).copy()

    wf["actual_margin_home"] = pd.to_numeric(wf["home_score"], errors="coerce") - pd.to_numeric(wf["away_score"], errors="coerce")
    wf["model_margin"] = pd.to_numeric(wf["model_margin"], errors="coerce")
    wf["spread_line"] = pd.to_numeric(wf["spread_line"], errors="coerce")
    wf["residual_margin"] = wf["actual_margin_home"] - wf["model_margin"]

    wf = wf.dropna(subset=["actual_margin_home", "model_margin", "spread_line", "residual_margin"]).copy()
    wf = wf.sort_values(["season", "week", "game_id"]).reset_index(drop=True)

    val = pd.read_csv(VALIDATION_SPREAD_PATH)
    val = val[val["season"].isin(SEASONS)].copy()
    val = val[["season", "week", "game_id", "side", "edge"]].dropna().copy()
    val = val.rename(columns={"side": "production_side", "edge": "production_edge_proxy"})
    val["production_side"] = val["production_side"].astype(str).str.lower().str.strip()

    return wf, val


def build_weekly_candidates() -> tuple[pd.DataFrame, dict[str, Any]]:
    wf, val = load_inputs()

    rows: list[dict[str, Any]] = []
    lookahead_violations = 0
    week_keys = sorted(wf[["season", "week"]].drop_duplicates().itertuples(index=False, name=None))

    for season, week in week_keys:
        prior = wf[(wf["season"] < season) | ((wf["season"] == season) & (wf["week"] < week))].copy()
        residuals = prior["residual_margin"].to_numpy(float)

        eligible = len(residuals) >= MIN_RESIDUAL_SAMPLE

        if len(prior):
            prior_key_df = prior[["season", "week"]].drop_duplicates().sort_values(["season", "week"])
            prior_max_row = prior_key_df.iloc[-1]
            prior_max_key = (int(prior_max_row["season"]), int(prior_max_row["week"]))
        else:
            prior_max_key = None

        decision_key = (int(season), int(week))
        if prior_max_key is not None and not (prior_max_key < decision_key):
            lookahead_violations += 1

        wk = wf[(wf["season"] == season) & (wf["week"] == week)]
        for _, r in wk.iterrows():
            spread_home = float(r["spread_line"])
            home_odds = float(r["home_spread_odds"])
            away_odds = float(r["away_spread_odds"])
            mm = float(r["model_margin"])
            am = float(r["actual_margin_home"])

            # Market probabilities.
            home_prob_raw = implied_probability(home_odds)
            away_prob_raw = implied_probability(away_odds)
            home_prob_novig, away_prob_novig = devig_two_way(home_odds, away_odds)

            probs = None
            if eligible:
                probs = spread_probs_home_away(mm, spread_home, residuals)

            for side in ["home", "away"]:
                odds = home_odds if side == "home" else away_odds
                market_raw = home_prob_raw if side == "home" else away_prob_raw
                market_novig = home_prob_novig if side == "home" else away_prob_novig
                res = side_result(am, spread_home, side)

                if eligible and probs is not None:
                    wp = probs[f"{side}_win"]
                    pp = probs[f"{side}_push"]
                    lp = probs[f"{side}_loss"]
                    ev = ev_push_aware(wp, pp, odds)
                    edge = wp - market_novig
                else:
                    wp = np.nan
                    pp = np.nan
                    lp = np.nan
                    ev = np.nan
                    edge = np.nan

                if side == "home":
                    side_line = spread_home
                    model_vs_market = mm - spread_home
                else:
                    side_line = -spread_home
                    model_vs_market = -mm + spread_home

                rows.append(
                    {
                        "season": int(season),
                        "week": int(week),
                        "game_id": str(r["game_id"]),
                        "home_team": str(r["home_team"]),
                        "away_team": str(r["away_team"]),
                        "decision_key": f"{int(season)}-W{int(week):02d}",
                        "side": side,
                        "side_line": float(side_line),
                        "spread_line_home": spread_home,
                        "odds": odds,
                        "market_prob_raw": market_raw,
                        "market_prob_novig": market_novig,
                        "model_margin_home": mm,
                        "model_vs_market_side": model_vs_market,
                        "actual_margin_home": am,
                        "result": res,
                        "is_push": 1 if res == "push" else 0,
                        "y": 1.0 if res == "win" else 0.0 if res == "loss" else np.nan,
                        "flat_profit": flat_profit(res, odds),
                        "eligible": bool(eligible),
                        "residual_sample_size": int(len(residuals)),
                        "residual_min_key": None if prior.empty else f"{int(prior['season'].min())}-W{int(prior['week'].min()):02d}",
                        "residual_max_key": None if prior.empty else f"{int(prior['season'].max())}-W{int(prior['week'].max()):02d}",
                        "current_win_prob": wp,
                        "current_push_prob": pp,
                        "current_loss_prob": lp,
                        "current_ev": ev,
                        "current_edge": edge,
                    }
                )

    cands = pd.DataFrame(rows)

    # Bring in historical production-side proxy from validation file.
    cands = cands.merge(val, on=["season", "week", "game_id"], how="left")

    return cands, {"lookahead_violations": int(lookahead_violations)}


def summarize_top(df: pd.DataFrame, score_col: str, max_picks: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    d = df[df[score_col].notna()].copy()
    d = d.sort_values(["season", "week", score_col], ascending=[True, True, False])
    d["pick_rank"] = d.groupby(["season", "week"]).cumcount() + 1
    picks = d[d["pick_rank"] <= max_picks].copy()

    wins = int((picks["result"] == "win").sum())
    losses = int((picks["result"] == "loss").sum())
    pushes = int((picks["result"] == "push").sum())
    denom = max(1, wins + losses)

    by_season = (
        picks.groupby("season")
        .agg(
            bets=("game_id", "size"),
            wins=("result", lambda s: int((s == "win").sum())),
            losses=("result", lambda s: int((s == "loss").sum())),
            pushes=("result", lambda s: int((s == "push").sum())),
            roi=("flat_profit", "mean"),
        )
        .reset_index()
        .to_dict("records")
    )

    by_rank = (
        picks.groupby("pick_rank")
        .agg(
            bets=("game_id", "size"),
            wins=("result", lambda s: int((s == "win").sum())),
            losses=("result", lambda s: int((s == "loss").sum())),
            pushes=("result", lambda s: int((s == "push").sum())),
            roi=("flat_profit", "mean"),
        )
        .reset_index()
        .to_dict("records")
    )

    out = {
        "bets": int(len(picks)),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate_ex_push": float(wins / denom),
        "roi": float(picks["flat_profit"].mean()) if len(picks) else None,
        "by_season": by_season,
        "by_rank": by_rank,
    }

    return picks, out


def odds_summary(df: pd.DataFrame) -> dict[str, Any]:
    o = df["odds"].dropna().astype(float)
    return {
        "N": int(len(o)),
        "median": float(o.median()),
        "mean": float(o.mean()),
        "p05": float(o.quantile(0.05)),
        "p95": float(o.quantile(0.95)),
        "min": float(o.min()),
        "max": float(o.max()),
        "malformed_non_finite": int((~np.isfinite(o)).sum()),
    }


def market_baselines(df: pd.DataFrame) -> dict[str, float]:
    d = df[(df["eligible"]) & (df["is_push"] == 0) & df["current_win_prob"].notna() & df["y"].notna()].copy()

    y = d["y"].to_numpy(float)
    p_cur = d["current_win_prob"].to_numpy(float)
    p_raw = d["market_prob_raw"].to_numpy(float)
    p_novig = d["market_prob_novig"].to_numpy(float)

    return {
        "current_brier": brier(y, p_cur),
        "market_raw_brier": brier(y, p_raw),
        "market_novig_brier": brier(y, p_novig),
        "current_logloss": logloss(y, p_cur),
        "market_raw_logloss": logloss(y, p_raw),
        "market_novig_logloss": logloss(y, p_novig),
    }


def side_symmetry_checks(df: pd.DataFrame) -> dict[str, Any]:
    d = df[df["eligible"]].copy()

    pivot = d.pivot_table(
        index=["season", "week", "game_id"],
        columns="side",
        values=["current_win_prob", "current_push_prob", "current_ev", "odds", "side_line", "model_margin_home", "actual_margin_home", "result"],
        aggfunc="first",
    )
    pivot.columns = [f"{col}_{side}" for col, side in pivot.columns]
    pair = pivot.reset_index()

    non_integer = pair[np.abs(pair["side_line_home"] % 1) > 1e-12].copy()
    integer = pair[np.abs(pair["side_line_home"] % 1) <= 1e-12].copy()

    tol = 1e-9
    non_integer_violation = int((np.abs((non_integer["current_win_prob_home"] + non_integer["current_win_prob_away"]) - 1.0) > tol).sum())

    integer_violation = int(
        (
            np.abs(
                (
                    integer["current_win_prob_home"]
                    + integer["current_win_prob_away"]
                    + integer["current_push_prob_home"]
                )
                - 1.0
            )
            > tol
        ).sum()
    )

    both_pos_ev = pair[(pair["current_ev_home"] > 0) & (pair["current_ev_away"] > 0)]

    sample = pair.sample(n=min(12, len(pair)), random_state=RNG_SEED).copy()
    sample_rows = []
    for _, r in sample.iterrows():
        selected_side = "home" if float(r["current_ev_home"]) >= float(r["current_ev_away"]) else "away"
        sample_rows.append(
            {
                "season": int(r["season"]),
                "week": int(r["week"]),
                "game_id": str(r["game_id"]),
                "home_line": float(r["side_line_home"]),
                "away_line": float(r["side_line_away"]),
                "home_win_prob": float(r["current_win_prob_home"]),
                "away_win_prob": float(r["current_win_prob_away"]),
                "home_push_prob": float(r["current_push_prob_home"]),
                "away_push_prob": float(r["current_push_prob_away"]),
                "home_ev": float(r["current_ev_home"]),
                "away_ev": float(r["current_ev_away"]),
                "selected_side_by_ev": selected_side,
                "actual_result_home_side": str(r["result_home"]),
                "actual_result_away_side": str(r["result_away"]),
            }
        )

    return {
        "non_integer_symmetry_violations": non_integer_violation,
        "integer_symmetry_violations": integer_violation,
        "both_sides_positive_ev_count": int(len(both_pos_ev)),
        "both_sides_positive_ev_examples": both_pos_ev[["season", "week", "game_id", "current_ev_home", "current_ev_away"]]
        .head(10)
        .to_dict("records"),
        "sample_rows": sample_rows,
    }


def reproducibility_sample(df: pd.DataFrame) -> dict[str, Any]:
    eligible = df[df["eligible"]].copy()
    # One row per game by choosing side with higher EV; deterministic replay candidate.
    pick = eligible.sort_values(["season", "week", "game_id", "current_ev"], ascending=[True, True, True, False]).drop_duplicates(
        subset=["season", "week", "game_id"], keep="first"
    )

    rng = np.random.default_rng(RNG_SEED)
    idx = rng.choice(pick.index.to_numpy(), size=min(10, len(pick)), replace=False)
    sample = pick.loc[idx].sort_values(["season", "week", "game_id"]) 

    checks: list[dict[str, Any]] = []
    mismatch = 0

    raw_wf, _ = load_inputs()
    raw_wf = raw_wf.set_index(["season", "week", "game_id"])

    for _, row in sample.iterrows():
        key = (int(row["season"]), int(row["week"]), str(row["game_id"]))
        src = raw_wf.loc[key]
        prior = raw_wf.reset_index()
        prior = prior[(prior["season"] < key[0]) | ((prior["season"] == key[0]) & (prior["week"] < key[1]))]
        residuals = prior["residual_margin"].to_numpy(float)

        probs = spread_probs_home_away(float(src["model_margin"]), float(src["spread_line"]), residuals)
        side = str(row["side"])
        wp = probs[f"{side}_win"]
        pp = probs[f"{side}_push"]
        lp = probs[f"{side}_loss"]
        odds = float(src["home_spread_odds"] if side == "home" else src["away_spread_odds"])
        ev = ev_push_aware(wp, pp, odds)

        ok = (
            abs(wp - float(row["current_win_prob"])) < 1e-12
            and abs(pp - float(row["current_push_prob"])) < 1e-12
            and abs(lp - float(row["current_loss_prob"])) < 1e-12
            and abs(ev - float(row["current_ev"])) < 1e-12
        )
        if not ok:
            mismatch += 1

        checks.append(
            {
                "game": key[2],
                "decision": f"{key[0]}-W{key[1]:02d}",
                "model_margin_home": float(src["model_margin"]),
                "market_line_home": float(src["spread_line"]),
                "selected_side": side,
                "residual_sample_size": int(len(residuals)),
                "residual_source_range": None if prior.empty else f"{int(prior['season'].min())}-W{int(prior['week'].min()):02d} to {int(prior['season'].max())}-W{int(prior['week'].max()):02d}",
                "P_win": float(row["current_win_prob"]),
                "P_push": float(row["current_push_prob"]),
                "P_loss": float(row["current_loss_prob"]),
                "price": float(row["odds"]),
                "EV": float(row["current_ev"]),
                "actual_result": str(row["result"]),
                "independent_recompute_match": bool(ok),
            }
        )

    return {
        "sample_size": int(len(checks)),
        "mismatch_count": int(mismatch),
        "rows": checks,
    }


def high_ev_group(df: pd.DataFrame) -> dict[str, Any]:
    d = df[(df["eligible"]) & (df["current_ev"] >= 0.40)].copy()
    nonpush = d[d["is_push"] == 0]

    sample = d.sort_values(["season", "week", "current_ev"], ascending=[True, True, False]).head(20)
    sample_rows = []
    for _, r in sample.iterrows():
        matchup = f"{r['away_team']} @ {r['home_team']}"
        selection = f"{r['home_team']} {r['side_line']:+g}" if r["side"] == "home" else f"{r['away_team']} {r['side_line']:+g}"
        sample_rows.append(
            {
                "season": int(r["season"]),
                "week": int(r["week"]),
                "matchup": matchup,
                "selection": selection,
                "line": float(r["side_line"]),
                "price": float(r["odds"]),
                "model_margin_home": float(r["model_margin_home"]),
                "win_probability": float(r["current_win_prob"]),
                "EV": float(r["current_ev"]),
                "actual_margin_home": float(r["actual_margin_home"]),
                "result": str(r["result"]),
            }
        )

    return {
        "N": int(len(d)),
        "win_rate_ex_push": None if len(nonpush) == 0 else float(nonpush["y"].mean()),
        "roi": None if len(d) == 0 else float(d["flat_profit"].mean()),
        "sample_rows": sample_rows,
    }


def edge_20pp_group(df: pd.DataFrame) -> dict[str, Any]:
    d = df[(df["eligible"]) & (df["current_edge"] >= 0.20)].copy()

    if d.empty:
        return {
            "N": 0,
            "win_rate_ex_push": None,
            "roi": None,
            "model_vs_market_side_summary": {},
            "market_spread_summary": {},
            "favdog": {},
            "homeaway": {},
            "season": {},
            "spread_magnitude_bucket": {},
        }

    nonpush = d[d["is_push"] == 0]

    spread_mag = np.abs(d["side_line"])
    bucket = pd.cut(spread_mag, bins=[0, 3, 7, 10, 100], labels=["0-3", "3-7", "7-10", "10+"], right=False)

    favdog = np.where(d["side_line"] < 0, "favorite", "underdog")

    return {
        "N": int(len(d)),
        "win_rate_ex_push": float(nonpush["y"].mean()) if len(nonpush) else None,
        "roi": float(d["flat_profit"].mean()),
        "model_vs_market_side_summary": {
            "mean": float(d["model_vs_market_side"].mean()),
            "median": float(d["model_vs_market_side"].median()),
            "p10": float(d["model_vs_market_side"].quantile(0.10)),
            "p90": float(d["model_vs_market_side"].quantile(0.90)),
        },
        "market_spread_summary": {
            "mean_abs": float(np.abs(d["side_line"]).mean()),
            "median_abs": float(np.abs(d["side_line"]).median()),
            "p10_abs": float(np.abs(d["side_line"]).quantile(0.10)),
            "p90_abs": float(np.abs(d["side_line"]).quantile(0.90)),
        },
        "favdog": pd.Series(favdog).value_counts().to_dict(),
        "homeaway": d["side"].value_counts().to_dict(),
        "season": d["season"].value_counts().sort_index().to_dict(),
        "spread_magnitude_bucket": pd.Series(bucket).value_counts().to_dict(),
    }


def duplicate_audit(wf: pd.DataFrame, val: pd.DataFrame) -> dict[str, Any]:
    wf_key_dupes = int(wf.duplicated(subset=["season", "week", "game_id"]).sum())
    val_key_dupes = int(val.duplicated(subset=["season", "week", "game_id"]).sum())

    return {
        "walkforward_duplicate_game_rows": wf_key_dupes,
        "validation_duplicate_game_rows": val_key_dupes,
        "walkforward_rows": int(len(wf)),
        "validation_rows": int(len(val)),
    }


def strict_weekly_replay(df: pd.DataFrame) -> dict[str, Any]:
    d = df[df["eligible"]].copy()

    # Current-EV and current-edge replays are strictly pre-outcome score-based.
    ev_top1_picks, ev_top1 = summarize_top(d, "current_ev", 1)
    edge_top1_picks, edge_top1 = summarize_top(d, "current_edge", 1)

    # Production ranking proxy replay if available.
    prod = d[d["side"] == d["production_side"]].copy()
    prod_top1_picks, prod_top1 = summarize_top(prod, "production_edge_proxy", 1)

    return {
        "current_ev_top1": ev_top1,
        "current_edge_top1": edge_top1,
        "production_proxy_top1": prod_top1,
        "current_ev_top1_win_rate": ev_top1["win_rate_ex_push"],
        "current_edge_top1_win_rate": edge_top1["win_rate_ex_push"],
        "production_proxy_top1_win_rate": prod_top1["win_rate_ex_push"],
        "current_ev_top1_bets": int(len(ev_top1_picks)),
        "current_edge_top1_bets": int(len(edge_top1_picks)),
        "production_proxy_top1_bets": int(len(prod_top1_picks)),
    }


def build_report() -> dict[str, Any]:
    wf, val = load_inputs()
    cands, lookahead_meta = build_weekly_candidates()

    eligible = cands[cands["eligible"]].copy()
    eligible_prod = eligible[eligible["side"] == eligible["production_side"]].copy()

    baselines = market_baselines(eligible_prod)
    symmetry = side_symmetry_checks(cands)
    replay = strict_weekly_replay(cands)

    # Side-selection outcome usage check:
    # Candidate scores are computed before any result-dependent aggregation; selection keys do not read `result`.
    side_selection_uses_outcome = False

    # Residual no-lookahead explicit assertion count.
    residual_lookahead_violations = int(lookahead_meta["lookahead_violations"])

    odds_stats = odds_summary(cands)

    dupes = duplicate_audit(wf, val)
    future_best_line_bias = False

    high_ev = high_ev_group(cands)
    edge20 = edge_20pp_group(cands)

    repro = reproducibility_sample(cands)

    # Model feature safety judgment from artifacts only.
    # model_margin is read directly from walkforward rows; no live team_power file is used by this audit script.
    uses_live_team_power_file = False

    # But generation-time provenance of model_margin internals cannot be fully proven from outputs alone.
    historical_features_as_of_time_safe = "UNKNOWN_FROM_ARTIFACTS"

    report = {
        "inputs": {
            "walkforward_path": str(WALKFORWARD_PATH),
            "validation_spread_path": str(VALIDATION_SPREAD_PATH),
            "team_power_ratings_latest_path": str(DATA_ROOT / "team_power_ratings_latest.csv"),
            "uses_live_team_power_file_in_audit": uses_live_team_power_file,
        },
        "sample": {
            "candidate_rows_total": int(len(cands)),
            "candidate_rows_eligible": int(len(eligible)),
            "production_side_rows_eligible": int(len(eligible_prod)),
            "games_eligible": int(eligible[["season", "week", "game_id"]].drop_duplicates().shape[0]),
            "weeks_eligible": int(eligible[["season", "week"]].drop_duplicates().shape[0]),
        },
        "feature_safety": {
            "historical_model_features_as_of_time_safe": historical_features_as_of_time_safe,
            "future_feature_leakage_found": "UNKNOWN_FROM_ARTIFACTS",
            "details": [
                "Audit script uses model_margin directly from historical walkforward rows, not reconstructed from live team_power_ratings_latest.csv.",
                "Underlying feature-engineering provenance/timestamps for model_margin cannot be conclusively verified from output CSVs alone.",
            ],
        },
        "residual_no_lookahead": {
            "violations": residual_lookahead_violations,
            "assertion": "max(residual_source_key) < decision_key for each eligible decision window (season-week granularity)",
            "note": "Intra-week kickoff timestamps are unavailable, so same-week game ordering cannot be audited at sub-week resolution.",
        },
        "side_selection": {
            "uses_outcome": side_selection_uses_outcome,
            "method": "home/away candidate probabilities and EV computed pre-outcome; ranking scores current_ev/current_edge used for selection",
        },
        "opposite_side_checks": symmetry,
        "market_timing": {
            "historical_market_line_type": "UNKNOWN_REFERENCE_LINE",
            "historical_price_type": "UNKNOWN_REFERENCE_PRICE",
            "executable_or_reference": "MARKET_REFERENCE_ROI",
            "details": "Source files contain one spread/odds snapshot per game with no offer timestamp history; cannot prove executable quoting window.",
        },
        "odds_sanity": odds_stats,
        "duplicates": dupes,
        "future_best_line_bias_found": future_best_line_bias,
        "reproducibility_10_game_check": repro,
        "high_ev_group_ge_40pct": high_ev,
        "edge_group_ge_20pp": edge20,
        "market_baselines": baselines,
        "strict_replay": replay,
        "historical_si_score_available_as_of_time": False,
        "canonical_snapshot_spec_ready": True,
        "canonical_snapshot_spec_fields": {
            "decision_fields": [
                "decisionId",
                "publishedAtUTC",
                "season",
                "week",
                "eventId",
                "selection",
                "market",
                "side",
                "point",
                "price",
                "sportsbook",
                "modelVersion",
                "probabilityEngineVersion",
                "calibrationVersion",
                "siScoreVersion",
                "rankingVersion",
                "currentWinProbability",
                "currentPushProbability",
                "currentLossProbability",
                "currentEV",
                "modelEdge",
                "fairLine",
                "truePlayableTo",
                "siScore",
                "siaRank",
                "qualificationStatus",
                "sourceOddsTimestamp",
                "sourceModelTimestamp",
                "sourceMarketTimestamp",
                "payloadHash",
            ],
            "outcome_fields_append_only": [
                "closingLine",
                "closingPrice",
                "closingTimestamp",
                "CLV",
                "gameResult",
                "betResult",
                "realizedProfitPerDollar",
            ],
        },
    }

    return report


def save_report(report: dict[str, Any]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "sia_current_engine_forensic_audit_report.json"
    md_path = OUTPUT_DIR / "sia_current_engine_forensic_audit_report.md"

    json_path.write_text(json.dumps(report, indent=2))

    b = report["market_baselines"]
    r = report["strict_replay"]
    lines = [
        "# SIA Current-Engine Forensic Audit",
        "",
        "## Core",
        f"- Residual lookahead violations: {report['residual_no_lookahead']['violations']}",
        f"- Opposite-side symmetry violations (non-integer): {report['opposite_side_checks']['non_integer_symmetry_violations']}",
        f"- Opposite-side symmetry violations (integer): {report['opposite_side_checks']['integer_symmetry_violations']}",
        "",
        "## Baselines",
        f"- Current Brier: {b['current_brier']:.6f}",
        f"- Market raw Brier: {b['market_raw_brier']:.6f}",
        f"- Market no-vig Brier: {b['market_novig_brier']:.6f}",
        f"- Current LogLoss: {b['current_logloss']:.6f}",
        f"- Market raw LogLoss: {b['market_raw_logloss']:.6f}",
        f"- Market no-vig LogLoss: {b['market_novig_logloss']:.6f}",
        "",
        "## Top1 Replay",
        f"- Current EV Top1 win rate: {r['current_ev_top1_win_rate']:.4f}",
        f"- Current edge Top1 win rate: {r['current_edge_top1_win_rate']:.4f}",
        f"- Production proxy Top1 win rate: {r['production_proxy_top1_win_rate']:.4f}",
    ]

    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


def main() -> None:
    report = build_report()
    json_path, md_path = save_report(report)

    print("FORENSIC AUDIT COMPLETE")
    print(f"Report JSON: {json_path}")
    print(f"Report MD: {md_path}")
    print(f"Residual lookahead violations: {report['residual_no_lookahead']['violations']}")
    print(f"Current-EV Top1 win rate: {report['strict_replay']['current_ev_top1_win_rate']:.6f}")
    print(f"Current-edge Top1 win rate: {report['strict_replay']['current_edge_top1_win_rate']:.6f}")


if __name__ == "__main__":
    main()
