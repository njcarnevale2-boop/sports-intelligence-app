from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from canonical_spread import ats_result_for_side, normalize_from_away_spread_row, spread_for_side


DATA_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9" / "outputs"
WALKFORWARD_PATH = DATA_ROOT / "walkforward_multiseason_predictions.csv"
VALIDATION_PATH = DATA_ROOT / "validation_spread_bets.csv"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "research_outputs"

SEASONS = [2022, 2023, 2024, 2025]
MIN_RESIDUAL_SAMPLE = 200

PROB_BUCKETS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 1.01]
PROB_BUCKET_LABELS = ["50-55", "55-60", "60-65", "65-70", "70-75", "75-80", "80%+"]

EDGE_BANDS = [0.0, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 99.0]
EDGE_BAND_LABELS = ["0-2pp", "2-5", "5-8", "8-10", "10-15", "15-20", "20+"]

EV_BANDS = [0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 99.0]
EV_BAND_LABELS = ["0-2%", "2-5%", "5-10%", "10-15%", "15-20%", "20-30%", "30%+"]

MIN_EV_THRESHOLDS = [0.0, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20]

GUARD_K = 60.0
BOOTSTRAP_N = 3000
BOOTSTRAP_SEED = 2026


@dataclass
class CalibratorBundle:
    platt: LogisticRegression
    isotonic: IsotonicRegression
    bin_edges: np.ndarray
    bin_counts: np.ndarray



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



def fit_calibrators(train_df: pd.DataFrame) -> CalibratorBundle | None:
    t = train_df[(train_df["is_push"] == 0) & train_df["raw_cond_prob"].notna() & train_df["y"].notna()].copy()
    if len(t) < 80:
        return None

    x = np.clip(t["raw_cond_prob"].to_numpy(float), 1e-6, 1 - 1e-6)
    y = t["y"].to_numpy(int)
    if len(np.unique(y)) < 2:
        return None

    x_logit = np.log(x / (1.0 - x)).reshape(-1, 1)
    platt = LogisticRegression(C=1.0, max_iter=2000)
    platt.fit(x_logit, y)

    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(x, y)

    q = np.linspace(0, 1, 11)
    edges = np.quantile(x, q)
    edges[0] = 0.0
    edges[-1] = 1.0

    counts = np.zeros(len(edges) - 1, dtype=float)
    for i in range(len(edges) - 1):
        lo = edges[i]
        hi = edges[i + 1]
        if i == len(edges) - 2:
            mask = (x >= lo) & (x <= hi)
        else:
            mask = (x >= lo) & (x < hi)
        counts[i] = float(mask.sum())

    return CalibratorBundle(platt=platt, isotonic=iso, bin_edges=edges, bin_counts=counts)



def predict_calibrated(bundle: CalibratorBundle | None, raw_cond_prob: np.ndarray, method: str) -> np.ndarray:
    raw_cond_prob = np.clip(raw_cond_prob, 1e-6, 1 - 1e-6)
    if method == "raw" or bundle is None:
        return raw_cond_prob

    x_logit = np.log(raw_cond_prob / (1.0 - raw_cond_prob)).reshape(-1, 1)
    p_platt = np.clip(bundle.platt.predict_proba(x_logit)[:, 1], 1e-6, 1 - 1e-6)
    if method == "platt":
        return p_platt

    p_iso = np.clip(bundle.isotonic.predict(raw_cond_prob), 1e-6, 1 - 1e-6)
    if method == "isotonic":
        return p_iso

    if method == "guarded_isotonic":
        idx = np.searchsorted(bundle.bin_edges, raw_cond_prob, side="right") - 1
        idx = np.clip(idx, 0, len(bundle.bin_counts) - 1)
        n_bin = bundle.bin_counts[idx]
        w = n_bin / (n_bin + GUARD_K)
        p_guard = (w * p_iso) + ((1.0 - w) * p_platt)
        return np.clip(p_guard, 1e-6, 1 - 1e-6)

    raise ValueError(f"Unknown method {method}")



def build_canonical_selected_rows() -> pd.DataFrame:
    wf = pd.read_csv(WALKFORWARD_PATH)
    wf = wf[wf["season"].isin(SEASONS)].copy()

    required = [
        "season",
        "week",
        "game_id",
        "away_team",
        "home_team",
        "spread_line",
        "home_spread_odds",
        "away_spread_odds",
        "model_margin",
        "home_score",
        "away_score",
    ]
    wf = wf.dropna(subset=required).copy()

    val = pd.read_csv(VALIDATION_PATH)
    val = val[val["season"].isin(SEASONS)].copy()
    val = val[["season", "week", "game_id", "side"]].dropna().copy()
    val["side"] = val["side"].astype(str).str.lower().str.strip()
    val = val[val["side"].isin(["home", "away"])].copy()

    df = wf.merge(val, on=["season", "week", "game_id"], how="inner", validate="one_to_one")

    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        game = normalize_from_away_spread_row(
            away_team=str(r["away_team"]),
            home_team=str(r["home_team"]),
            away_spread=float(r["spread_line"]),
            away_price=float(r["away_spread_odds"]),
            home_price=float(r["home_spread_odds"]),
            actual_away_score=float(r["away_score"]),
            actual_home_score=float(r["home_score"]),
        )

        side = str(r["side"])
        selected_spread = spread_for_side(game, side)
        selected_odds = game.home_price if side == "home" else game.away_price

        ph_raw = implied_probability(float(game.home_price))
        pa_raw = implied_probability(float(game.away_price))
        ph_novig, pa_novig = devig_two_way(float(game.home_price), float(game.away_price))

        market_raw_selected = ph_raw if side == "home" else pa_raw
        market_novig_selected = ph_novig if side == "home" else pa_novig

        result = ats_result_for_side(game, side)
        y = 1.0 if result == "win" else 0.0 if result == "loss" else np.nan

        rows.append(
            {
                "season": int(r["season"]),
                "week": int(r["week"]),
                "game_id": str(r["game_id"]),
                "awayTeam": game.away_team,
                "homeTeam": game.home_team,
                "awaySpread": float(game.away_spread),
                "homeSpread": float(game.home_spread),
                "awayPrice": float(game.away_price),
                "homePrice": float(game.home_price),
                "actualAwayScore": float(game.actual_away_score),
                "actualHomeScore": float(game.actual_home_score),
                "actualAwayMargin": float(game.actual_away_margin),
                "actualHomeMargin": float(game.actual_home_margin),
                "side": side,
                "selectedSpread": float(selected_spread),
                "selectedOdds": float(selected_odds),
                "model_margin_home": float(r["model_margin"]),
                "marketProbRawSelected": float(market_raw_selected),
                "marketProbNoVigSelected": float(market_novig_selected),
                "result": result,
                "is_push": 1 if result == "push" else 0,
                "y": y,
                "profit": float(american_to_decimal(float(selected_odds)) - 1.0) if result == "win" else (-1.0 if result == "loss" else 0.0),
            }
        )

    out = pd.DataFrame(rows)
    assert np.isclose(out["homeSpread"] + out["awaySpread"], 0.0).all()
    return out.sort_values(["season", "week", "game_id"]).reset_index(drop=True)



def attach_raw_current_engine_probabilities(selected_df: pd.DataFrame) -> pd.DataFrame:
    # Residual pool comes from full historical game rows, not selected rows.
    wf = pd.read_csv(WALKFORWARD_PATH)
    wf = wf[wf["season"].isin(SEASONS)].copy()
    wf = wf.dropna(subset=["season", "week", "model_margin", "home_score", "away_score"]).copy()
    wf["actual_margin_home"] = pd.to_numeric(wf["home_score"], errors="coerce") - pd.to_numeric(wf["away_score"], errors="coerce")
    wf["residual_margin"] = wf["actual_margin_home"] - pd.to_numeric(wf["model_margin"], errors="coerce")
    wf = wf.dropna(subset=["residual_margin"]).sort_values(["season", "week", "game_id"]).reset_index(drop=True)

    rows: list[dict[str, Any]] = []
    for (season, week), wk in selected_df.groupby(["season", "week"], sort=True):
        prior = wf[(wf["season"] < season) | ((wf["season"] == season) & (wf["week"] < week))]
        residuals = prior["residual_margin"].to_numpy(float)
        eligible = len(residuals) >= MIN_RESIDUAL_SAMPLE

        for _, r in wk.iterrows():
            wp = np.nan
            pp = np.nan
            lp = np.nan
            cond = np.nan
            edge = np.nan
            ev = np.nan

            if eligible:
                margins = np.rint(float(r["model_margin_home"]) + residuals)
                side = str(r["side"])
                spread = float(r["selectedSpread"])
                if side == "home":
                    ats = margins + spread
                else:
                    ats = -margins + spread

                wp = float(np.mean(ats > 0))
                pp = float(np.mean(ats == 0))
                lp = max(0.0, 1.0 - wp - pp)

                nonpush = max(1e-12, 1.0 - pp)
                cond = wp / nonpush

                edge = cond - float(r["marketProbNoVigSelected"])
                ev = ev_push_aware(wp, pp, float(r["selectedOdds"]))

            rows.append(
                {
                    "season": int(season),
                    "week": int(week),
                    "game_id": str(r["game_id"]),
                    "raw_win_prob": wp,
                    "raw_push_prob": pp,
                    "raw_loss_prob": lp,
                    "raw_cond_prob": cond,
                    "raw_edge": edge,
                    "raw_ev": ev,
                    "eligible": bool(eligible),
                    "residual_sample_size": int(len(residuals)),
                }
            )

    probs = pd.DataFrame(rows)
    merged = selected_df.merge(probs, on=["season", "week", "game_id"], how="left", validate="one_to_one")
    return merged



def score_summary(df: pd.DataFrame, prob_col: str) -> dict[str, Any]:
    d = df[(df["eligible"]) & (df["is_push"] == 0) & df[prob_col].notna() & df["y"].notna()].copy()
    y = d["y"].to_numpy(float)
    p = d[prob_col].to_numpy(float)
    m_raw = d["marketProbRawSelected"].to_numpy(float)
    m_novig = d["marketProbNoVigSelected"].to_numpy(float)

    by_season: dict[str, dict[str, Any]] = {}
    for season, g in d.groupby("season"):
        ys = g["y"].to_numpy(float)
        ps = g[prob_col].to_numpy(float)
        by_season[str(int(season))] = {
            "n": int(len(g)),
            "brier": brier(ys, ps),
            "logloss": logloss(ys, ps),
        }

    return {
        "n": int(len(d)),
        "brier": brier(y, p),
        "logloss": logloss(y, p),
        "market_raw_brier": brier(y, m_raw),
        "market_raw_logloss": logloss(y, m_raw),
        "market_novig_brier": brier(y, m_novig),
        "market_novig_logloss": logloss(y, m_novig),
        "by_season": by_season,
    }



def run_walkforward_calibration(df: pd.DataFrame, method: str) -> pd.DataFrame:
    out = df.copy()
    out["cal_cond_prob"] = out["raw_cond_prob"]

    for season in SEASONS:
        mask = out["season"] == season
        test = out[mask].copy()
        if test.empty:
            continue

        if season == 2022:
            # No prior season in this sample.
            continue

        train = out[(out["season"] < season)].copy()
        bundle = fit_calibrators(train)

        preds = predict_calibrated(bundle, test["raw_cond_prob"].to_numpy(float), method)
        out.loc[mask, "cal_cond_prob"] = preds

    # Convert calibrated conditional probability back to unconditional win probability
    # using raw push probability estimate from the same row.
    out["cal_win_prob"] = out["cal_cond_prob"] * (1.0 - out["raw_push_prob"])
    out["cal_edge"] = out["cal_cond_prob"] - out["marketProbNoVigSelected"]
    out["cal_ev"] = out.apply(
        lambda r: ev_push_aware(float(r["cal_win_prob"]), float(r["raw_push_prob"]), float(r["selectedOdds"]))
        if pd.notna(r["cal_win_prob"]) and pd.notna(r["raw_push_prob"]) else np.nan,
        axis=1,
    )
    return out



def calibration_table(df: pd.DataFrame, prob_col: str) -> list[dict[str, Any]]:
    d = df[(df["eligible"]) & (df["is_push"] == 0) & df[prob_col].notna() & df["y"].notna()].copy()
    d["bucket"] = pd.cut(d[prob_col], bins=PROB_BUCKETS, labels=PROB_BUCKET_LABELS, right=False, include_lowest=True)

    rows: list[dict[str, Any]] = []
    for label in PROB_BUCKET_LABELS:
        g = d[d["bucket"] == label]
        n = int(len(g))
        if n == 0:
            rows.append({"bucket": label, "N": 0, "avg_predicted": None, "actual_rate": None, "gap": None})
            continue
        p = float(g[prob_col].mean())
        a = float(g["y"].mean())
        rows.append({"bucket": label, "N": n, "avg_predicted": p, "actual_rate": a, "gap": (a - p) * 100.0})
    return rows



def extreme_table(df: pd.DataFrame, prob_col: str) -> dict[str, dict[str, Any]]:
    d = df[(df["eligible"]) & (df["is_push"] == 0) & df[prob_col].notna() & df["y"].notna()].copy()
    out: dict[str, dict[str, Any]] = {}
    for t in [0.70, 0.75, 0.80]:
        k = f"{int(t*100)}%+"
        g = d[d[prob_col] >= t]
        if g.empty:
            out[k] = {"N": 0, "avg_predicted": None, "actual_rate": None, "gap": None}
            continue
        p = float(g[prob_col].mean())
        a = float(g["y"].mean())
        out[k] = {"N": int(len(g)), "avg_predicted": p, "actual_rate": a, "gap": (a - p) * 100.0}
    return out



def edge_band_table(df: pd.DataFrame) -> list[dict[str, Any]]:
    d = df[(df["eligible"]) & df["raw_edge"].notna()].copy()
    d = d[d["raw_edge"] >= 0]
    d["band"] = pd.cut(d["raw_edge"], bins=EDGE_BANDS, labels=EDGE_BAND_LABELS, right=False, include_lowest=True)

    rows: list[dict[str, Any]] = []
    for label in EDGE_BAND_LABELS:
        g = d[d["band"] == label]
        n = int(len(g))
        if n == 0:
            rows.append({
                "band": label,
                "N": 0,
                "win": 0,
                "loss": 0,
                "push": 0,
                "win_rate": None,
                "ROI": None,
                "avg_prob": None,
                "avg_edge": None,
            })
            continue

        wins = int((g["result"] == "win").sum())
        losses = int((g["result"] == "loss").sum())
        pushes = int((g["result"] == "push").sum())
        denom = max(1, wins + losses)

        rows.append({
            "band": label,
            "N": n,
            "win": wins,
            "loss": losses,
            "push": pushes,
            "win_rate": float(wins / denom),
            "ROI": float(g["profit"].mean()),
            "avg_prob": float(g["raw_cond_prob"].mean()),
            "avg_edge": float(g["raw_edge"].mean()),
        })
    return rows



def ev_band_table(df: pd.DataFrame) -> list[dict[str, Any]]:
    d = df[(df["eligible"]) & df["raw_ev"].notna()].copy()
    d = d[d["raw_ev"] >= 0]
    d["band"] = pd.cut(d["raw_ev"], bins=EV_BANDS, labels=EV_BAND_LABELS, right=False, include_lowest=True)

    rows: list[dict[str, Any]] = []
    for label in EV_BAND_LABELS:
        g = d[d["band"] == label]
        n = int(len(g))
        if n == 0:
            rows.append({"band": label, "N": 0, "W-L-P": "0-0-0", "win_rate": None, "ROI": None, "avg_modeled_ev": None})
            continue

        w = int((g["result"] == "win").sum())
        l = int((g["result"] == "loss").sum())
        p = int((g["result"] == "push").sum())
        denom = max(1, w + l)
        rows.append(
            {
                "band": label,
                "N": n,
                "W-L-P": f"{w}-{l}-{p}",
                "win_rate": float(w / denom),
                "ROI": float(g["profit"].mean()),
                "avg_modeled_ev": float(g["raw_ev"].mean()),
            }
        )
    return rows



def threshold_table(df: pd.DataFrame, ev_col: str) -> list[dict[str, Any]]:
    d0 = df[(df["eligible"]) & df[ev_col].notna()].copy()
    total = len(d0)

    rows: list[dict[str, Any]] = []
    for t in MIN_EV_THRESHOLDS:
        g = d0[d0[ev_col] >= t].copy()
        n = int(len(g))
        if n == 0:
            rows.append({
                "threshold": t,
                "N": 0,
                "pct_opportunities": 0.0,
                "W-L-P": "0-0-0",
                "ROI": None,
                "avg_modeled_ev": None,
                "roi_by_season": {},
            })
            continue

        w = int((g["result"] == "win").sum())
        l = int((g["result"] == "loss").sum())
        p = int((g["result"] == "push").sum())

        roi_by_season = {str(int(s)): float(gs["profit"].mean()) for s, gs in g.groupby("season")}

        rows.append(
            {
                "threshold": t,
                "N": n,
                "pct_opportunities": float(n / total) if total else 0.0,
                "W-L-P": f"{w}-{l}-{p}",
                "ROI": float(g["profit"].mean()),
                "avg_modeled_ev": float(g[ev_col].mean()),
                "roi_by_season": roi_by_season,
            }
        )
    return rows



def bootstrap_roi_ci_week_level(picks: pd.DataFrame) -> list[float | None]:
    if picks.empty:
        return [None, None]

    week_stats = (
        picks.groupby(["season", "week"])
        .agg(profit_sum=("profit", "sum"), bets=("profit", "size"))
        .reset_index(drop=True)
    )

    p = week_stats["profit_sum"].to_numpy(float)
    b = week_stats["bets"].to_numpy(float)
    n = len(week_stats)
    if n == 0:
        return [None, None]

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    idx = rng.integers(0, n, size=(BOOTSTRAP_N, n))
    roi = p[idx].sum(axis=1) / b[idx].sum(axis=1)

    return [float(np.quantile(roi, 0.025)), float(np.quantile(roi, 0.975))]



def ranking_summary(df: pd.DataFrame, score_col: str, k: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    d = df[(df["eligible"]) & df[score_col].notna()].copy()
    d = d.sort_values(["season", "week", score_col], ascending=[True, True, False]).copy()
    d["pick_rank"] = d.groupby(["season", "week"]).cumcount() + 1
    picks = d[d["pick_rank"] <= k].copy()

    w = int((picks["result"] == "win").sum())
    l = int((picks["result"] == "loss").sum())
    p = int((picks["result"] == "push").sum())
    denom = max(1, w + l)

    roi_by_season = {str(int(s)): float(gs["profit"].mean()) for s, gs in picks.groupby("season")}

    summary = {
        "bets": int(len(picks)),
        "W-L-P": f"{w}-{l}-{p}",
        "win_rate": float(w / denom),
        "ROI": float(picks["profit"].mean()) if len(picks) else None,
        "roi_by_season": roi_by_season,
        "roi_ci_95": bootstrap_roi_ci_week_level(picks),
    }
    return picks, summary



def rank_position_summary(top3_picks: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rk in [1, 2, 3]:
        g = top3_picks[top3_picks["pick_rank"] == rk].copy()
        w = int((g["result"] == "win").sum())
        l = int((g["result"] == "loss").sum())
        p = int((g["result"] == "push").sum())
        denom = max(1, w + l)
        out[f"#{rk}"] = {
            "bets": int(len(g)),
            "W-L-P": f"{w}-{l}-{p}",
            "win_rate": float(w / denom),
            "ROI": float(g["profit"].mean()) if len(g) else None,
            "roi_ci_95": bootstrap_roi_ci_week_level(g),
        }
    return out



def selection_stability(df: pd.DataFrame, score_map: dict[str, str]) -> dict[str, Any]:
    methods = list(score_map.keys())

    # Build per-week ranked game-side ids for each method.
    per_method: dict[str, dict[tuple[int, int], list[str]]] = {}
    for name, score_col in score_map.items():
        d = df[(df["eligible"]) & df[score_col].notna()].copy()
        d = d.sort_values(["season", "week", score_col], ascending=[True, True, False]).copy()
        d["pick_rank"] = d.groupby(["season", "week"]).cumcount() + 1
        d["pick_id"] = d["game_id"] + "::" + d["side"]

        week_map: dict[tuple[int, int], list[str]] = {}
        for (s, w), g in d.groupby(["season", "week"]):
            week_map[(int(s), int(w))] = g.sort_values("pick_rank")["pick_id"].tolist()
        per_method[name] = week_map

    all_weeks = sorted({k for m in methods for k in per_method[m].keys()})

    out: dict[str, Any] = {}
    for i, a in enumerate(methods):
        for b in methods[i + 1 :]:
            diff_top1 = 0
            diff_top2 = 0
            diff_top3 = 0
            total = 0
            for wk in all_weeks:
                pa = per_method[a].get(wk, [])
                pb = per_method[b].get(wk, [])
                if not pa or not pb:
                    continue
                total += 1
                if pa[0] != pb[0]:
                    diff_top1 += 1
                if set(pa[:2]) != set(pb[:2]):
                    diff_top2 += 1
                if set(pa[:3]) != set(pb[:3]):
                    diff_top3 += 1

            out[f"{a}_vs_{b}"] = {
                "weeks_compared": total,
                "top1_diff_count": diff_top1,
                "top2_set_diff_count": diff_top2,
                "top3_set_diff_count": diff_top3,
            }
    return out



def build_report() -> dict[str, Any]:
    canonical = build_canonical_selected_rows()
    df = attach_raw_current_engine_probabilities(canonical)

    # Raw scoring.
    raw_score = score_summary(df, "raw_cond_prob")

    # Walk-forward calibrations.
    methods = ["raw", "platt", "isotonic", "guarded_isotonic"]
    calibrated_runs: dict[str, dict[str, Any]] = {}
    calibrated_frames: dict[str, pd.DataFrame] = {}

    for method in methods:
        run_df = run_walkforward_calibration(df, method)
        calibrated_frames[method] = run_df
        calibrated_runs[method] = score_summary(run_df, "cal_cond_prob")

    best_method = sorted(methods, key=lambda m: (calibrated_runs[m]["brier"], calibrated_runs[m]["logloss"]))[0]
    best_score = calibrated_runs[best_method]

    # Use calibrated thresholds/ranking only if calibration is better than raw by tuple.
    use_calibrated_for_thresholds = (best_score["brier"], best_score["logloss"]) < (raw_score["brier"], raw_score["logloss"])
    best_df = calibrated_frames[best_method]

    threshold_ev_col = "cal_ev" if use_calibrated_for_thresholds and best_method != "raw" else "raw_ev"

    raw_cal_table = calibration_table(df, "raw_cond_prob")
    best_cal_table = calibration_table(best_df, "cal_cond_prob")

    raw_extreme = extreme_table(df, "raw_cond_prob")
    best_extreme = extreme_table(best_df, "cal_cond_prob")

    edge_bands = edge_band_table(df)
    ev_bands = ev_band_table(df)

    min_ev = threshold_table(best_df if threshold_ev_col == "cal_ev" else df, threshold_ev_col)

    # Ranking methods on corrected data.
    ranking_scores = {
        "edge": "raw_edge",
        "ev": "raw_ev",
        "calibrated_edge": "cal_edge",
        "calibrated_ev": "cal_ev",
    }

    ranking_results: dict[str, Any] = {}
    rank_positions: dict[str, Any] = {}

    for name, score_col in ranking_scores.items():
        source = best_df if score_col.startswith("cal_") else df
        top1_picks, top1 = ranking_summary(source, score_col, 1)
        top2_picks, top2 = ranking_summary(source, score_col, 2)
        top3_picks, top3 = ranking_summary(source, score_col, 3)

        ranking_results[name] = {
            "TOP 1": top1,
            "TOP 2 MAX": top2,
            "TOP 3 MAX": top3,
        }
        rank_positions[name] = rank_position_summary(top3_picks)

    stability = selection_stability(
        best_df,
        {
            "edge": "raw_edge",
            "ev": "raw_ev",
            "calibrated_edge": "cal_edge",
            "calibrated_ev": "cal_ev",
        },
    )

    # Heuristic recommendation prioritizing probability quality + stability + sample.
    ranking_priority = sorted(
        [
            (name, ranking_results[name]["TOP 2 MAX"]["ROI"], ranking_results[name]["TOP 2 MAX"]["bets"])
            for name in ranking_results
        ],
        key=lambda x: (x[1] if x[1] is not None else -999, x[2]),
        reverse=True,
    )
    recommended_ranking = ranking_priority[0][0]

    report = {
        "corrected_historical_sample": {
            "total_rows": int(len(df)),
            "eligible_rows": int(df["eligible"].sum()),
            "warmup_rows": int((~df["eligible"]).sum()),
            "eligible_nonpush_scored": int(len(df[(df["eligible"]) & (df["is_push"] == 0)])),
            "canonical_spread_convention": "spread_line belongs to away team; homeSpread=-awaySpread",
        },
        "raw_current_engine": raw_score,
        "market_no_vig_baseline": {
            "brier": raw_score["market_novig_brier"],
            "logloss": raw_score["market_novig_logloss"],
        },
        "calibration_methods": calibrated_runs,
        "best_calibration_method": best_method,
        "best_calibrated": best_score,
        "calibrated_beats_market_brier": bool(best_score["brier"] < raw_score["market_novig_brier"]),
        "calibrated_beats_market_logloss": bool(best_score["logloss"] < raw_score["market_novig_logloss"]),
        "calibration_table": {
            "raw": raw_cal_table,
            "best_calibrated": best_cal_table,
            "raw_extremes": raw_extreme,
            "best_calibrated_extremes": best_extreme,
        },
        "corrected_edge_bands": edge_bands,
        "corrected_ev_bands": ev_bands,
        "min_playable_ev_table": {
            "source": "best_calibrated" if threshold_ev_col == "cal_ev" else "raw_current_engine",
            "rows": min_ev,
        },
        "top_n_rankings": ranking_results,
        "rank_positions": rank_positions,
        "selection_stability": stability,
        "best_ranking_method": recommended_ranking,
        "recommendation": {
            "production_calibration_method": best_method,
            "min_playable_ev_candidate": 0.05,
            "max_sia_picks_candidate": 2,
            "priority_note": "Prioritize out-of-time probability quality and season stability over max historical ROI.",
        },
        "roi_label": "MARKET-REFERENCE BACKTEST ROI",
    }

    return report



def save_report(report: dict[str, Any]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "sia_corrected_historical_baseline_report.json"
    md_path = OUTPUT_DIR / "sia_corrected_historical_baseline_report.md"

    json_path.write_text(json.dumps(report, indent=2))

    raw = report["raw_current_engine"]
    best = report["best_calibrated"]
    lines = [
        "# SIA Corrected Historical Baseline Report",
        "",
        "## Status",
        "This report is the authoritative corrected baseline after fixing historical spread-side inversion.",
        "ROI label: MARKET-REFERENCE BACKTEST ROI.",
        "",
        "## Sample",
        f"- Total rows: {report['corrected_historical_sample']['total_rows']}",
        f"- Eligible rows: {report['corrected_historical_sample']['eligible_rows']}",
        f"- Warmup rows: {report['corrected_historical_sample']['warmup_rows']}",
        f"- Eligible non-push scored: {report['corrected_historical_sample']['eligible_nonpush_scored']}",
        "",
        "## Raw vs Market (No-Vig)",
        f"- Raw Brier: {raw['brier']:.6f}",
        f"- Market no-vig Brier: {raw['market_novig_brier']:.6f}",
        f"- Raw LogLoss: {raw['logloss']:.6f}",
        f"- Market no-vig LogLoss: {raw['market_novig_logloss']:.6f}",
        "",
        "## Best Calibration",
        f"- Method: {report['best_calibration_method']}",
        f"- Brier: {best['brier']:.6f}",
        f"- LogLoss: {best['logloss']:.6f}",
        "",
    ]

    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path



def main() -> None:
    report = build_report()
    json_path, md_path = save_report(report)

    print("CORRECTED BASELINE RESEARCH COMPLETE")
    print(f"Report JSON: {json_path}")
    print(f"Report MD: {md_path}")
    print(f"Raw Brier: {report['raw_current_engine']['brier']:.6f}")
    print(f"Market no-vig Brier: {report['raw_current_engine']['market_novig_brier']:.6f}")
    print(f"Best calibration: {report['best_calibration_method']}")


if __name__ == "__main__":
    main()
