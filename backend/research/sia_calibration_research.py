from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


DATA_PATH = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9" / "outputs" / "walkforward_multiseason_predictions.csv"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "research_outputs"

CALIBRATION_TEST_SEASONS = [2022, 2023, 2024, 2025]

PROB_BUCKETS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 1.01]
PROB_BUCKET_LABELS = ["50-55", "55-60", "60-65", "65-70", "70-75", "75-80", "80+"]

EDGE_BANDS = [0.0, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 99.0]
EDGE_BAND_LABELS = ["0-2pp", "2-5pp", "5-8pp", "8-10pp", "10-15pp", "15-20pp", "20pp+"]

EV_BANDS = [0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 99.0]
EV_BAND_LABELS = ["0-2%", "2-5%", "5-10%", "10-15%", "15-20%", "20%+"]

MIN_EV_THRESHOLDS = [0.0, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20]

MIN_GROUP_TRAIN = 120
GUARD_K = 60.0


@dataclass
class CalibratorBundle:
    platt: LogisticRegression
    isotonic: IsotonicRegression
    bin_edges: np.ndarray
    bin_counts: np.ndarray


def american_to_decimal(odds: float) -> float:
    return 1.0 + (100.0 / abs(odds) if odds < 0 else odds / 100.0)


def implied_probability(odds: float) -> float:
    if odds < 0:
        return (-odds) / ((-odds) + 100.0)
    return 100.0 / (odds + 100.0)


def devig_two_way(home_odds: float, away_odds: float) -> tuple[float, float]:
    ph = implied_probability(home_odds)
    pa = implied_probability(away_odds)
    s = ph + pa
    return ph / s, pa / s


def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def ev_push_aware(win_prob: float, push_prob: float, odds: float) -> float:
    dec = american_to_decimal(odds)
    profit_if_win = dec - 1.0
    loss_prob = max(0.0, 1.0 - win_prob - push_prob)
    return float(win_prob * profit_if_win - loss_prob)


def fit_calibrators(train_df: pd.DataFrame) -> CalibratorBundle | None:
    t = train_df[(train_df["is_push"] == 0) & train_df["raw_prob"].notna() & train_df["y"].notna()].copy()
    if len(t) < 80:
        return None

    x = np.clip(t["raw_prob"].to_numpy(float), 1e-6, 1 - 1e-6)
    y = t["y"].to_numpy(int)
    if len(np.unique(y)) < 2:
        return None

    x_logit = np.log(x / (1 - x)).reshape(-1, 1)
    platt = LogisticRegression(C=1.0, max_iter=2000)
    platt.fit(x_logit, y)

    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(x, y)

    # Adaptive guardrails: sparse bin -> heavier shrink toward platt.
    q = np.linspace(0, 1, 11)
    bin_edges = np.quantile(x, q)
    bin_edges[0] = 0.0
    bin_edges[-1] = 1.0
    bin_counts = np.zeros(len(bin_edges) - 1, dtype=float)
    for i in range(len(bin_edges) - 1):
        lo = bin_edges[i]
        hi = bin_edges[i + 1]
        if i == len(bin_edges) - 2:
            mask = (x >= lo) & (x <= hi)
        else:
            mask = (x >= lo) & (x < hi)
        bin_counts[i] = float(mask.sum())

    return CalibratorBundle(
        platt=platt,
        isotonic=iso,
        bin_edges=bin_edges,
        bin_counts=bin_counts,
    )


def predict_with_bundle(bundle: CalibratorBundle | None, raw_prob: np.ndarray, method: str) -> np.ndarray:
    raw_prob = np.clip(raw_prob, 1e-6, 1 - 1e-6)
    if method == "raw" or bundle is None:
        return raw_prob

    x_logit = np.log(raw_prob / (1 - raw_prob)).reshape(-1, 1)
    p_platt = np.clip(bundle.platt.predict_proba(x_logit)[:, 1], 1e-6, 1 - 1e-6)

    if method == "platt":
        return p_platt

    p_iso = np.clip(bundle.isotonic.predict(raw_prob), 1e-6, 1 - 1e-6)
    if method == "isotonic":
        return p_iso

    if method == "guarded_isotonic":
        idx = np.searchsorted(bundle.bin_edges, raw_prob, side="right") - 1
        idx = np.clip(idx, 0, len(bundle.bin_counts) - 1)
        n_bin = bundle.bin_counts[idx]
        w = n_bin / (n_bin + GUARD_K)
        p_guard = w * p_iso + (1.0 - w) * p_platt
        return np.clip(p_guard, 1e-6, 1 - 1e-6)

    raise ValueError(f"Unknown method: {method}")


def structure_group(row: pd.Series) -> str:
    favdog = "fav" if bool(row["is_favorite_pick"]) else "dog"
    abs_spread = abs(float(row["spread_line"]))
    if abs_spread < 3:
        band = "s0_3"
    elif abs_spread < 7:
        band = "s3_7"
    else:
        band = "s7p"
    return f"{favdog}_{band}"


def apply_walk_forward_calibration(decisions: pd.DataFrame, method: str, structural: bool) -> tuple[pd.DataFrame, dict[str, Any]]:
    out = decisions.copy()
    out["calibrated_prob"] = out["raw_prob"].to_numpy(float)

    fallback_stats = {
        "method": method,
        "structural": structural,
        "group_fallback_count": 0,
        "group_used_count": 0,
    }

    for season in CALIBRATION_TEST_SEASONS:
        mask_test = out["season"] == season
        if season == 2022:
            # Warm-up year has no prior OOS season in this research design.
            continue

        train = out[(out["season"] >= 2022) & (out["season"] < season)].copy()
        test = out[mask_test].copy()
        if test.empty:
            continue

        global_bundle = fit_calibrators(train)

        if not structural:
            preds = predict_with_bundle(global_bundle, test["raw_prob"].to_numpy(float), method)
            out.loc[mask_test, "calibrated_prob"] = preds
            continue

        # Structural mode with guardrails and global fallback.
        test_preds = np.zeros(len(test), dtype=float)
        test_idx = test.index.to_numpy()
        for gname, gtest in test.groupby("structure_group"):
            gtrain = train[train["structure_group"] == gname]
            eligible = gtrain[(gtrain["is_push"] == 0) & gtrain["y"].notna()]
            if len(eligible) >= MIN_GROUP_TRAIN and len(eligible["y"].unique()) >= 2:
                gbundle = fit_calibrators(gtrain)
                preds = predict_with_bundle(gbundle, gtest["raw_prob"].to_numpy(float), method)
                fallback_stats["group_used_count"] += len(gtest)
            else:
                preds = predict_with_bundle(global_bundle, gtest["raw_prob"].to_numpy(float), method)
                fallback_stats["group_fallback_count"] += len(gtest)
            test_preds[np.isin(test_idx, gtest.index.to_numpy())] = preds

        out.loc[mask_test, "calibrated_prob"] = test_preds

    return out, fallback_stats


def calibration_table(df: pd.DataFrame, prob_col: str) -> list[dict[str, Any]]:
    d = df[(df["is_push"] == 0) & df[prob_col].notna() & df["y"].notna()].copy()
    d["bucket"] = pd.cut(d[prob_col], bins=PROB_BUCKETS, labels=PROB_BUCKET_LABELS, right=False, include_lowest=True)
    rows: list[dict[str, Any]] = []
    for b, g in d.groupby("bucket", observed=False):
        if b is None:
            continue
        n = int(len(g))
        if n == 0:
            rows.append({"bucket": str(b), "N": 0, "avg_prob": None, "actual_rate": None, "cal_error_pp": None})
        else:
            p = float(g[prob_col].mean())
            a = float(g["y"].mean())
            rows.append({"bucket": str(b), "N": n, "avg_prob": p, "actual_rate": a, "cal_error_pp": (a - p) * 100.0})
    return rows


def extreme_table(df: pd.DataFrame, prob_col: str) -> dict[str, dict[str, Any]]:
    d = df[(df["is_push"] == 0) & df[prob_col].notna() & df["y"].notna()].copy()
    out: dict[str, dict[str, Any]] = {}
    for t in [0.70, 0.75, 0.80]:
        g = d[d[prob_col] >= t]
        if g.empty:
            out[f">={int(t*100)}"] = {"N": 0, "avg_prob": None, "actual_rate": None, "gap_pp": None}
        else:
            p = float(g[prob_col].mean())
            a = float(g["y"].mean())
            out[f">={int(t*100)}"] = {"N": int(len(g)), "avg_prob": p, "actual_rate": a, "gap_pp": (a - p) * 100.0}
    return out


def edge_band_table(df: pd.DataFrame, prob_col: str) -> list[dict[str, Any]]:
    d = df.copy()
    d["calibrated_edge"] = d[prob_col] - d["market_prob"]
    d["band"] = pd.cut(d["calibrated_edge"], bins=EDGE_BANDS, labels=EDGE_BAND_LABELS, right=False, include_lowest=True)
    rows: list[dict[str, Any]] = []
    for b, g in d.groupby("band", observed=False):
        n = int(len(g))
        if n == 0:
            rows.append({"band": str(b), "N": 0, "avg_prob": None, "actual_win": None, "avg_edge": None, "roi": None})
            continue
        nonpush = g[g["is_push"] == 0]
        rows.append(
            {
                "band": str(b),
                "N": n,
                "avg_prob": float(g[prob_col].mean()),
                "actual_win": float(nonpush["y"].mean()) if len(nonpush) else None,
                "avg_edge": float(g["calibrated_edge"].mean()),
                "roi": float(g["flat_profit"].mean()),
            }
        )
    return rows


def build_push_lookup(train_df: pd.DataFrame) -> dict[int, float]:
    lookup: dict[int, float] = {}
    t = train_df.copy()
    t = t[t["line_key_int"].notna()]
    for lk, g in t.groupby("line_key_int"):
        if len(g) >= 40:
            lookup[int(lk)] = float(g["is_push"].mean())
    return lookup


def ev_band_table(df: pd.DataFrame, prob_col: str) -> list[dict[str, Any]]:
    d = df[df["calibrated_ev"].notna()].copy()
    d = d[d["calibrated_ev"] >= 0]
    d["band"] = pd.cut(d["calibrated_ev"], bins=EV_BANDS, labels=EV_BAND_LABELS, right=False, include_lowest=True)
    rows: list[dict[str, Any]] = []
    for b, g in d.groupby("band", observed=False):
        n = int(len(g))
        if n == 0:
            rows.append({"band": str(b), "N": 0, "win_rate": None, "push_rate": None, "avg_calibrated_ev": None, "roi": None})
            continue
        nonpush = g[g["is_push"] == 0]
        rows.append(
            {
                "band": str(b),
                "N": n,
                "win_rate": float(nonpush["y"].mean()) if len(nonpush) else None,
                "push_rate": float(g["is_push"].mean()),
                "avg_calibrated_ev": float(g["calibrated_ev"].mean()),
                "roi": float(g["flat_profit"].mean()),
            }
        )
    return rows


def threshold_table(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in MIN_EV_THRESHOLDS:
        g = df[df["calibrated_ev"] >= t].copy()
        n = int(len(g))
        if n == 0:
            rows.append(
                {
                    "threshold": t,
                    "N": 0,
                    "pct_total": 0.0,
                    "win_rate": None,
                    "push_rate": None,
                    "roi": None,
                    "avg_calibrated_ev": None,
                    "roi_by_season": {},
                }
            )
            continue

        nonpush = g[g["is_push"] == 0]
        roi_by_season = {
            str(int(s)): float(gs["flat_profit"].mean())
            for s, gs in g.groupby("season")
        }
        rows.append(
            {
                "threshold": t,
                "N": n,
                "pct_total": float(n / len(df)),
                "win_rate": float(nonpush["y"].mean()) if len(nonpush) else None,
                "push_rate": float(g["is_push"].mean()),
                "roi": float(g["flat_profit"].mean()),
                "avg_calibrated_ev": float(g["calibrated_ev"].mean()),
                "roi_by_season": roi_by_season,
            }
        )
    return rows


def simulate_sia(df: pd.DataFrame, rank_col: str, max_picks: int) -> dict[str, Any]:
    d = df[df["calibrated_ev"] >= 0].copy()
    d = d.sort_values(["season", "week", rank_col], ascending=[True, True, False])
    d["pick_rank"] = d.groupby(["season", "week"]).cumcount() + 1
    d = d[d["pick_rank"] <= max_picks].copy()

    wins = int((d["result"] == "win").sum())
    losses = int((d["result"] == "loss").sum())
    pushes = int((d["result"] == "push").sum())
    nonpush = max(1, wins + losses)

    by_season = (
        d.groupby("season")
        .agg(
            bets=("game_id", "size"),
            wins=("result", lambda s: int((s == "win").sum())),
            losses=("result", lambda s: int((s == "loss").sum())),
            pushes=("result", lambda s: int((s == "push").sum())),
            roi=("flat_profit", "mean"),
            avg_calibrated_ev=("calibrated_ev", "mean"),
        )
        .reset_index()
        .to_dict("records")
    )

    by_rank = (
        d.groupby("pick_rank")
        .agg(
            bets=("game_id", "size"),
            wins=("result", lambda s: int((s == "win").sum())),
            losses=("result", lambda s: int((s == "loss").sum())),
            pushes=("result", lambda s: int((s == "push").sum())),
            roi=("flat_profit", "mean"),
            avg_calibrated_ev=("calibrated_ev", "mean"),
        )
        .reset_index()
        .to_dict("records")
    )

    return {
        "weeks": int(df[["season", "week"]].drop_duplicates().shape[0]),
        "weeks_with_picks": int(d[["season", "week"]].drop_duplicates().shape[0]),
        "bets": int(len(d)),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate_ex_push": float(wins / nonpush),
        "roi": float(d["flat_profit"].mean()) if len(d) else None,
        "avg_calibrated_ev": float(d["calibrated_ev"].mean()) if len(d) else None,
        "by_season": by_season,
        "by_rank": by_rank,
    }


def build_research_dataset() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing walk-forward dataset: {DATA_PATH}")

    pred = pd.read_csv(DATA_PATH)
    pred = pred[pred["season"].isin(CALIBRATION_TEST_SEASONS)].copy()

    rows: list[dict[str, Any]] = []
    for _, r in pred.iterrows():
        if pd.isna(r.get("spread_line")):
            continue

        spread = float(r["spread_line"])
        sd = float(r.get("spread_residual_sd_prior", np.nan))
        if not np.isfinite(sd) or sd <= 0:
            continue

        model_margin = float(r["model_margin"])
        p_home = norm_cdf((model_margin - spread) / sd)
        side = "home" if p_home >= 0.5 else "away"
        raw_prob = p_home if side == "home" else 1.0 - p_home

        home_odds = r.get("home_spread_odds")
        away_odds = r.get("away_spread_odds")
        odds = float(home_odds if side == "home" else away_odds) if pd.notna(home_odds if side == "home" else away_odds) else -110.0

        if pd.notna(home_odds) and pd.notna(away_odds):
            ph, pa = devig_two_way(float(home_odds), float(away_odds))
            market_prob = ph if side == "home" else pa
        else:
            market_prob = implied_probability(odds)

        actual_margin = float(r["home_score"] - r["away_score"])
        ats = actual_margin - spread
        if side == "home":
            result = "win" if ats > 0 else "loss" if ats < 0 else "push"
            is_favorite_pick = spread > 0
        else:
            result = "win" if ats < 0 else "loss" if ats > 0 else "push"
            is_favorite_pick = spread < 0

        flat_profit = (american_to_decimal(odds) - 1.0) if result == "win" else -1.0 if result == "loss" else 0.0

        rows.append(
            {
                "season": int(r["season"]),
                "week": int(r["week"]),
                "game_id": str(r["game_id"]),
                "home_team": str(r["home_team"]),
                "away_team": str(r["away_team"]),
                "spread_line": spread,
                "odds": odds,
                "raw_prob": raw_prob,
                "market_prob": market_prob,
                "result": result,
                "is_push": 1 if result == "push" else 0,
                "y": 1.0 if result == "win" else 0.0 if result == "loss" else np.nan,
                "flat_profit": flat_profit,
                "is_favorite_pick": bool(is_favorite_pick),
                "structure_group": "",
                "line_key_int": int(round(abs(spread))) if abs(spread - round(spread)) < 1e-9 else np.nan,
                "raw_edge": raw_prob - market_prob,
            }
        )

    df = pd.DataFrame(rows)
    df["structure_group"] = df.apply(structure_group, axis=1)
    return df


def season_metrics(df: pd.DataFrame, prob_col: str) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for season, g in df[df["is_push"] == 0].groupby("season"):
        y = g["y"].to_numpy(float)
        p = g[prob_col].to_numpy(float)
        rows[str(int(season))] = {
            "n": int(len(g)),
            "brier": brier(y, p),
            "logloss": logloss(y, p),
        }
    return rows


def evaluate_method(base_df: pd.DataFrame, method: str, structural: bool) -> dict[str, Any]:
    calibrated, fallback = apply_walk_forward_calibration(base_df, method=method, structural=structural)

    # Push-aware EV recomputation using out-of-time push-rate lookup by integer line.
    calibrated["calibrated_ev"] = np.nan
    calibrated["push_prob_est"] = np.nan

    for season in CALIBRATION_TEST_SEASONS:
        train = calibrated[(calibrated["season"] >= 2022) & (calibrated["season"] < season)]
        test_mask = calibrated["season"] == season
        if season == 2022:
            # Warm-up: use all prior available rows in warm-up season itself for lookup only.
            train = calibrated[calibrated["season"] == 2022]

        push_lookup = build_push_lookup(train)
        test = calibrated[test_mask].copy()
        if test.empty:
            continue

        p_nonpush = test["calibrated_prob"].to_numpy(float)
        p_push = []
        p_win = []
        p_loss = []
        ev = []
        for _, row in test.iterrows():
            line_key = row["line_key_int"]
            pp = push_lookup.get(int(line_key), float(train["is_push"].mean()) if len(train) else 0.0) if pd.notna(line_key) else float(train["is_push"].mean()) if len(train) else 0.0
            wp = (1.0 - pp) * float(row["calibrated_prob"])
            lp = max(0.0, 1.0 - pp - wp)
            e = ev_push_aware(wp, pp, float(row["odds"]))
            p_push.append(pp)
            p_win.append(wp)
            p_loss.append(lp)
            ev.append(e)

        calibrated.loc[test_mask, "push_prob_est"] = np.array(p_push)
        calibrated.loc[test_mask, "win_prob_est"] = np.array(p_win)
        calibrated.loc[test_mask, "loss_prob_est"] = np.array(p_loss)
        calibrated.loc[test_mask, "calibrated_ev"] = np.array(ev)

    scored = calibrated[(calibrated["is_push"] == 0) & calibrated["calibrated_prob"].notna() & calibrated["y"].notna()].copy()
    y = scored["y"].to_numpy(float)
    p = scored["calibrated_prob"].to_numpy(float)

    # Raw and market baselines from same rows.
    p_raw = scored["raw_prob"].to_numpy(float)
    p_market = scored["market_prob"].to_numpy(float)

    summary = {
        "name": f"{method}_{'structural' if structural else 'global'}",
        "method": method,
        "structural": structural,
        "fallback": fallback,
        "n_scored": int(len(scored)),
        "brier": brier(y, p),
        "logloss": logloss(y, p),
        "raw_brier": brier(y, p_raw),
        "raw_logloss": logloss(y, p_raw),
        "market_brier": brier(y, p_market),
        "market_logloss": logloss(y, p_market),
        "by_season": season_metrics(calibrated, "calibrated_prob"),
        "calibration_table": calibration_table(calibrated, "calibrated_prob"),
        "extreme": extreme_table(calibrated, "calibrated_prob"),
        "edge_bands": edge_band_table(calibrated, "calibrated_prob"),
        "ev_bands": ev_band_table(calibrated, "calibrated_prob"),
        "thresholds": threshold_table(calibrated),
        "sia_top1": simulate_sia(calibrated, rank_col="calibrated_ev", max_picks=1),
        "sia_top2": simulate_sia(calibrated, rank_col="calibrated_ev", max_picks=2),
        "sia_top3": simulate_sia(calibrated, rank_col="calibrated_ev", max_picks=3),
        "ranking_research": {
            "by_calibrated_ev_top3": simulate_sia(calibrated, rank_col="calibrated_ev", max_picks=3),
            "by_calibrated_edge_top3": simulate_sia(
                calibrated.assign(calibrated_edge=calibrated["calibrated_prob"] - calibrated["market_prob"]),
                rank_col="calibrated_edge",
                max_picks=3,
            ),
            "by_raw_ev_top3": simulate_sia(
                calibrated.assign(raw_ev=calibrated.apply(lambda r: ev_push_aware((1.0 - r["push_prob_est"]) * r["raw_prob"], r["push_prob_est"], r["odds"]), axis=1)),
                rank_col="raw_ev",
                max_picks=3,
            ),
            "by_raw_edge_top3": simulate_sia(calibrated.assign(raw_edge_rank=calibrated["raw_prob"] - calibrated["market_prob"]), rank_col="raw_edge_rank", max_picks=3),
        },
    }

    return {
        "summary": summary,
        "calibrated_rows": calibrated,
    }


def residual_distribution(df_path: Path) -> dict[str, Any]:
    pred = pd.read_csv(df_path)
    pred = pred[pred["season"].isin(CALIBRATION_TEST_SEASONS)].copy()
    residual = (pred["home_score"] - pred["away_score"]) - pred["model_margin"]

    pred["residual"] = residual
    pred["fav_bucket"] = np.where(pred["spread_line"] > 0, "home_fav", np.where(pred["spread_line"] < 0, "home_dog", "pickem"))
    pred["margin_mag_bucket"] = pd.cut(np.abs(pred["model_margin"]), bins=[0, 3, 7, 14, 99], labels=["0-3", "3-7", "7-14", "14+"], right=False)
    pred["spread_range_bucket"] = pd.cut(np.abs(pred["spread_line"]), bins=[0, 3, 7, 10, 99], labels=["0-3", "3-7", "7-10", "10+"], right=False)

    return {
        "N": int(residual.notna().sum()),
        "mean": float(residual.mean()),
        "median": float(residual.median()),
        "std": float(residual.std(ddof=1)),
        "mae": float(np.abs(residual).mean()),
        "rmse": float(np.sqrt(np.mean(np.square(residual)))),
        "q05": float(residual.quantile(0.05)),
        "q10": float(residual.quantile(0.10)),
        "q25": float(residual.quantile(0.25)),
        "q75": float(residual.quantile(0.75)),
        "q90": float(residual.quantile(0.90)),
        "q95": float(residual.quantile(0.95)),
        "min": float(residual.min()),
        "max": float(residual.max()),
        "by_season": pred.groupby("season")["residual"].agg(["count", "mean", "median", "std"]).reset_index().to_dict("records"),
        "by_favorite_status": pred.groupby("fav_bucket")["residual"].agg(["count", "mean", "median", "std"]).reset_index().to_dict("records"),
        "by_margin_magnitude": pred.groupby("margin_mag_bucket", observed=False)["residual"].agg(["count", "mean", "median", "std"]).reset_index().to_dict("records"),
        "by_spread_range": pred.groupby("spread_range_bucket", observed=False)["residual"].agg(["count", "mean", "median", "std"]).reset_index().to_dict("records"),
    }


def build_report() -> dict[str, Any]:
    df = build_research_dataset()

    oos = {
        "sample_size": int(len(df)),
        "seasons": sorted([int(x) for x in df["season"].unique().tolist()]),
        "push_count": int(df["is_push"].sum()),
        "nonpush_count": int((df["is_push"] == 0).sum()),
    }

    experiments: list[dict[str, Any]] = []
    methods = ["raw", "platt", "isotonic", "guarded_isotonic"]
    for method in methods:
        experiments.append(evaluate_method(df, method=method, structural=False)["summary"])
        if method != "raw":
            experiments.append(evaluate_method(df, method=method, structural=True)["summary"])

    # Choose best by Brier with tie-break on log loss.
    best = sorted(experiments, key=lambda x: (x["brier"], x["logloss"]))[0]

    raw_global = next(e for e in experiments if e["name"] == "raw_global")

    report = {
        "methodology": {
            "design": "strict out-of-time walk-forward calibration",
            "schedule": {
                "2022": "raw warm-up (no prior OOS season)",
                "2023": "calibrate using 2022 only",
                "2024": "calibrate using 2022-2023",
                "2025": "calibrate using 2022-2024",
            },
            "structural_groups": "favorite/underdog x spread-range buckets with minimum-sample guardrails and global fallback",
            "min_group_train": MIN_GROUP_TRAIN,
            "guarded_isotonic": "isotonic probabilities shrunk toward platt based on per-bin sample size",
            "production_modified": False,
        },
        "oos": oos,
        "residual_distribution": residual_distribution(DATA_PATH),
        "experiments": experiments,
        "best_method": {
            "name": best["name"],
            "brier": best["brier"],
            "logloss": best["logloss"],
            "beats_market_brier": bool(best["brier"] < raw_global["market_brier"]),
            "beats_market_logloss": bool(best["logloss"] < raw_global["market_logloss"]),
        },
        "raw_baseline": {
            "brier": raw_global["brier"],
            "logloss": raw_global["logloss"],
            "market_brier": raw_global["market_brier"],
            "market_logloss": raw_global["market_logloss"],
            "calibration_table": raw_global["calibration_table"],
        },
        "best_outputs": {
            "calibration_table": best["calibration_table"],
            "extreme": best["extreme"],
            "edge_bands": best["edge_bands"],
            "ev_bands": best["ev_bands"],
            "thresholds": best["thresholds"],
            "sia_top1": best["sia_top1"],
            "sia_top2": best["sia_top2"],
            "sia_top3": best["sia_top3"],
            "ranking_research": best["ranking_research"],
            "by_season": best["by_season"],
        },
        "limitations": [
            "No untouched post-2025 holdout season exists in this 2022-2025 OOS sample.",
            "Current dataset is spread decisions only; totals and moneyline calibration are out of scope here.",
            "Historical SI Score / production ranking signal is not present in walkforward_multiseason_predictions.csv, so ranking research uses available probability/EV/edge signals only.",
        ],
    }
    return report


def save_report(report: dict[str, Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "sia_calibration_research_report.json"
    json_path.write_text(json.dumps(report, indent=2))

    md_path = OUTPUT_DIR / "sia_calibration_research_report.md"
    best = report["best_method"]
    raw = report["raw_baseline"]

    lines = [
        "# SIA Out-of-Time Calibration Research Report",
        "",
        "## Scope",
        "Read-only research pipeline. No production recommendation logic, UI, thresholds, or API behavior modified.",
        "",
        "## OOS Sample",
        f"- Sample size: {report['oos']['sample_size']}",
        f"- Seasons: {', '.join(str(x) for x in report['oos']['seasons'])}",
        f"- Pushes: {report['oos']['push_count']}",
        "",
        "## Baselines",
        f"- Raw Brier: {raw['brier']:.6f}",
        f"- Market Brier: {raw['market_brier']:.6f}",
        f"- Raw Log Loss: {raw['logloss']:.6f}",
        f"- Market Log Loss: {raw['market_logloss']:.6f}",
        "",
        "## Best Calibration",
        f"- Method: {best['name']}",
        f"- Brier: {best['brier']:.6f}",
        f"- Log Loss: {best['logloss']:.6f}",
        f"- Beats market Brier: {best['beats_market_brier']}",
        f"- Beats market Log Loss: {best['beats_market_logloss']}",
        "",
        "## Limitations",
    ]
    for item in report["limitations"]:
        lines.append(f"- {item}")

    md_path.write_text("\n".join(lines) + "\n")
    return json_path


def main() -> None:
    report = build_report()
    out_path = save_report(report)

    print("RESEARCH PIPELINE COMPLETE")
    print(f"Report JSON: {out_path}")
    print(f"Best method: {report['best_method']['name']}")
    print(f"Best Brier: {report['best_method']['brier']:.6f}")
    print(f"Best Log Loss: {report['best_method']['logloss']:.6f}")


if __name__ == "__main__":
    main()
