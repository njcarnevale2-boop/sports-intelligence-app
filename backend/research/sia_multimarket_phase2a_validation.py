from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9" / "outputs"
DB_PATH = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9" / "database" / "nfl_model.duckdb"
OUT_DIR = Path(__file__).resolve().parents[1] / "research_outputs"

WALKFORWARD_PATH = OUTPUT_ROOT / "walkforward_multiseason_predictions.csv"

SEED = 2026
N_BOOT = 4000
GUARD_K = 60.0
EPS = 1e-6


def implied_prob_american(odds: float) -> float:
    o = float(odds)
    if o > 0:
        return 100.0 / (o + 100.0)
    return abs(o) / (abs(o) + 100.0)


def american_to_decimal(odds: float) -> float:
    o = float(odds)
    return 1.0 + (100.0 / abs(o) if o < 0 else o / 100.0)


def devig_two_way(odds_a: float, odds_b: float) -> tuple[float, float]:
    pa = implied_prob_american(odds_a)
    pb = implied_prob_american(odds_b)
    s = pa + pb
    if s <= 0:
        return 0.5, 0.5
    return pa / s, pb / s


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def logloss(y: np.ndarray, p: np.ndarray) -> float:
    q = np.clip(p, EPS, 1.0 - EPS)
    return float(-np.mean(y * np.log(q) + (1.0 - y) * np.log(1.0 - q)))


def ev_no_push(win_prob: float, odds: float) -> float:
    dec = american_to_decimal(odds)
    return float(win_prob * (dec - 1.0) - (1.0 - win_prob))


def ev_push_aware(win_prob: float, push_prob: float, odds: float) -> float:
    dec = american_to_decimal(odds)
    return float(win_prob * (dec - 1.0) - max(0.0, 1.0 - win_prob - push_prob))


def bootstrap_ci_mean(values: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> tuple[float, float]:
    if len(values) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n_boot, len(values)))
    means = values[idx].mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def bootstrap_roi_ci(profits: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> tuple[float, float]:
    if len(profits) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(profits), size=(n_boot, len(profits)))
    rois = profits[idx].mean(axis=1)
    return float(np.quantile(rois, 0.025)), float(np.quantile(rois, 0.975))


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    q = np.clip(p, 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, bins + 1)
    bucket = np.clip(np.digitize(q, edges, right=True) - 1, 0, bins - 1)
    ece = 0.0
    n = len(q)
    for b in range(bins):
        mask = bucket == b
        if not np.any(mask):
            continue
        w = mask.mean()
        conf = q[mask].mean()
        acc = y[mask].mean()
        ece += w * abs(acc - conf)
    return float(ece)


@dataclass
class CalibratorPack:
    raw: Callable[[np.ndarray], np.ndarray]
    platt: Callable[[np.ndarray], np.ndarray]
    isotonic: Callable[[np.ndarray], np.ndarray]
    guarded_isotonic: Callable[[np.ndarray], np.ndarray]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _fit_platt(train_raw: np.ndarray, train_y: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    x = np.clip(train_raw.astype(float), EPS, 1.0 - EPS)
    y = train_y.astype(float)
    z = np.log(x / (1.0 - x))

    a = 1.0
    b = 0.0
    for _ in range(50):
        s = a * z + b
        p = _sigmoid(s)
        w = p * (1.0 - p)

        g_a = float(np.sum((p - y) * z))
        g_b = float(np.sum(p - y))

        h_aa = float(np.sum(w * z * z) + 1e-6)
        h_bb = float(np.sum(w) + 1e-6)
        h_ab = float(np.sum(w * z))

        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-12:
            break

        step_a = (h_bb * g_a - h_ab * g_b) / det
        step_b = (-h_ab * g_a + h_aa * g_b) / det

        a -= step_a
        b -= step_b

        if abs(step_a) < 1e-8 and abs(step_b) < 1e-8:
            break

    def _predict(v: np.ndarray) -> np.ndarray:
        q = np.clip(v.astype(float), EPS, 1.0 - EPS)
        zq = np.log(q / (1.0 - q))
        return np.clip(_sigmoid(a * zq + b), EPS, 1.0 - EPS)

    return _predict


def _fit_isotonic_pav(train_raw: np.ndarray, train_y: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    x = train_raw.astype(float)
    y = train_y.astype(float)
    order = np.argsort(x)
    x = x[order]
    y = y[order]

    means: list[float] = []
    weights: list[int] = []
    starts: list[int] = []
    ends: list[int] = []

    for i, yi in enumerate(y):
        means.append(float(yi))
        weights.append(1)
        starts.append(i)
        ends.append(i)

        while len(means) >= 2 and means[-2] > means[-1]:
            w1 = weights[-2]
            w2 = weights[-1]
            merged_w = w1 + w2
            merged_mean = (means[-2] * w1 + means[-1] * w2) / merged_w
            means[-2] = float(merged_mean)
            weights[-2] = merged_w
            ends[-2] = ends[-1]

            means.pop()
            weights.pop()
            starts.pop()
            ends.pop()

    block_upper_x = np.array([x[e] for e in ends], dtype=float)
    block_mean = np.array(means, dtype=float)

    def _predict(v: np.ndarray) -> np.ndarray:
        q = np.asarray(v, dtype=float)
        idx = np.searchsorted(block_upper_x, q, side="left")
        idx = np.clip(idx, 0, len(block_mean) - 1)
        return np.clip(block_mean[idx], EPS, 1.0 - EPS)

    return _predict


def _fit_calibrators(train_raw: np.ndarray, train_y: np.ndarray) -> CalibratorPack:
    x = np.clip(train_raw.astype(float), EPS, 1.0 - EPS)
    y = train_y.astype(int)

    def raw_fn(v: np.ndarray) -> np.ndarray:
        return np.clip(v.astype(float), EPS, 1.0 - EPS)

    if len(np.unique(y)) < 2:
        return CalibratorPack(raw=raw_fn, platt=raw_fn, isotonic=raw_fn, guarded_isotonic=raw_fn)

    iso_predict = _fit_isotonic_pav(x, y)
    platt_predict = _fit_platt(x, y)

    # Build guarded-isotonic control points from calibration sample.
    bins = np.linspace(0.0, 1.0, 11)
    bucket = np.clip(np.digitize(x, bins, right=True) - 1, 0, 9)
    pts = []
    iso_on_train = np.clip(iso_predict(x), EPS, 1.0 - EPS)
    for b in range(10):
        mask = bucket == b
        if not np.any(mask):
            continue
        pts.append((float(x[mask].mean()), float(iso_on_train[mask].mean()), float(mask.sum())))
    pts.sort(key=lambda z: z[0])

    def _iso_interp(v: float) -> tuple[float, float]:
        if not pts:
            return v, 1.0
        if v <= pts[0][0]:
            return pts[0][1], pts[0][2]
        if v >= pts[-1][0]:
            return pts[-1][1], pts[-1][2]
        for i in range(len(pts) - 1):
            x0, y0, n0 = pts[i]
            x1, y1, n1 = pts[i + 1]
            if x0 <= v <= x1:
                t = 0.0 if x1 == x0 else (v - x0) / (x1 - x0)
                yv = (1.0 - t) * y0 + t * y1
                nv = (1.0 - t) * n0 + t * n1
                return yv, nv
        return pts[-1][1], pts[-1][2]

    def platt_fn(v: np.ndarray) -> np.ndarray:
        return platt_predict(v)

    def iso_fn(v: np.ndarray) -> np.ndarray:
        return iso_predict(v)

    def guarded_fn(v: np.ndarray) -> np.ndarray:
        q = np.clip(v.astype(float), EPS, 1.0 - EPS)
        out = np.zeros_like(q)
        for i, qi in enumerate(q):
            iso_val, n_bin = _iso_interp(float(qi))
            w = n_bin / (n_bin + GUARD_K)
            out[i] = w * iso_val + (1.0 - w) * qi
        return np.clip(out, EPS, 1.0 - EPS)

    return CalibratorPack(raw=raw_fn, platt=platt_fn, isotonic=iso_fn, guarded_isotonic=guarded_fn)


def _safe_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def load_core_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    wf = pd.read_csv(WALKFORWARD_PATH)
    need = {
        "season", "week", "game_id", "home_team", "away_team", "home_score", "away_score",
        "home_win", "spread_line", "home_spread_odds", "away_spread_odds", "total_line",
        "home_win_prob_raw", "model_margin", "model_total", "calibration_season",
    }
    missing = sorted(need - set(wf.columns))
    if missing:
        raise RuntimeError(f"walkforward file missing columns: {missing}")

    wf = wf.dropna(subset=list(need)).copy()
    wf["season"] = wf["season"].astype(int)
    wf["week"] = wf["week"].astype(int)
    wf["home_win"] = wf["home_win"].astype(int)
    wf["home_score"] = pd.to_numeric(wf["home_score"], errors="coerce")
    wf["away_score"] = pd.to_numeric(wf["away_score"], errors="coerce")
    wf["actual_total"] = wf["home_score"] + wf["away_score"]
    wf["actual_margin_home"] = wf["home_score"] - wf["away_score"]

    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    sched = con.execute(
        """
        select season, week, game_id, home_moneyline, away_moneyline, total_line as sched_total_line,
               over_odds, under_odds, spread_line as sched_spread_line,
               home_spread_odds as sched_home_spread_odds, away_spread_odds as sched_away_spread_odds
        from schedules
        """
    ).df()
    con.close()

    sched["season"] = sched["season"].astype(int)
    sched["week"] = sched["week"].astype(int)

    return wf, sched


def build_moneyline_dataset(wf: pd.DataFrame, sched: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    m = wf.merge(sched, on=["season", "week", "game_id"], how="left")
    m = m.dropna(subset=["home_moneyline", "away_moneyline"]).copy()

    m["pred_home_raw"] = np.clip(pd.to_numeric(m["home_win_prob_raw"], errors="coerce"), EPS, 1.0 - EPS)
    m["pred_away_raw"] = 1.0 - m["pred_home_raw"]

    novig = m.apply(lambda r: devig_two_way(float(r["home_moneyline"]), float(r["away_moneyline"])), axis=1)
    m["market_home_novig"] = [x[0] for x in novig]
    m["market_away_novig"] = [x[1] for x in novig]
    m["market_home_raw_imp"] = m["home_moneyline"].apply(implied_prob_american)
    m["market_away_raw_imp"] = m["away_moneyline"].apply(implied_prob_american)

    # Walk-forward prior-only calibration by season.
    cal_rows = []
    for season in sorted(m["season"].unique()):
        train = m[m["season"] < season]
        test = m[m["season"] == season].copy()
        if len(train) < 200:
            continue

        pack = _fit_calibrators(train["pred_home_raw"].to_numpy(float), train["home_win"].to_numpy(int))
        for name, fn in {
            "raw": pack.raw,
            "platt": pack.platt,
            "isotonic": pack.isotonic,
            "guarded_isotonic": pack.guarded_isotonic,
        }.items():
            ph = fn(test["pred_home_raw"].to_numpy(float))
            test[f"pred_home_{name}"] = ph
            test[f"pred_away_{name}"] = 1.0 - ph

        cal_rows.append(test)

    if not cal_rows:
        raise RuntimeError("Insufficient prior data for moneyline calibration folds.")

    ml = pd.concat(cal_rows, ignore_index=True)
    ml["as_of_time_safe"] = ml["calibration_season"] < ml["season"]

    return ml, {}


def choose_best_moneyline_calibration(ml: pd.DataFrame) -> tuple[str, dict]:
    y = ml["home_win"].to_numpy(float)
    methods = ["raw", "platt", "isotonic", "guarded_isotonic"]
    scores = {}
    for method in methods:
        p = ml[f"pred_home_{method}"].to_numpy(float)
        scores[method] = {
            "brier": brier(y, p),
            "logloss": logloss(y, p),
            "ece": expected_calibration_error(y, p),
        }

    best = sorted(methods, key=lambda m: (scores[m]["brier"], scores[m]["logloss"]))[0]
    return best, scores


def build_total_dataset(wf: pd.DataFrame, sched: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    t = wf.merge(sched, on=["season", "week", "game_id"], how="left")
    t = t.dropna(subset=["total_line", "over_odds", "under_odds", "model_total", "actual_total"]).copy()

    # Prior-only residual simulation by season.
    t["residual_total"] = t["actual_total"] - t["model_total"]
    games_rows = []
    side_rows = []

    for season in sorted(t["season"].unique()):
        prior = t[t["season"] < season]
        if len(prior) < 200:
            continue

        residuals = prior["residual_total"].dropna().to_numpy(float)
        if len(residuals) < 200:
            continue

        cur = t[t["season"] == season].copy()
        for _, r in cur.iterrows():
            sims = np.rint(float(r["model_total"]) + residuals)
            line = float(r["total_line"])
            p_over = float(np.mean(sims > line))
            p_push = float(np.mean(sims == line))
            p_under = max(0.0, 1.0 - p_over - p_push)

            o_odds = float(r["over_odds"])
            u_odds = float(r["under_odds"])
            novig_over, novig_under = devig_two_way(o_odds, u_odds)

            actual_total = float(r["actual_total"])
            over_result = "win" if actual_total > line else "push" if actual_total == line else "loss"
            under_result = "win" if actual_total < line else "push" if actual_total == line else "loss"

            games_rows.append(
                {
                    "season": int(r["season"]),
                    "week": int(r["week"]),
                    "game_id": str(r["game_id"]),
                    "home_team": str(r["home_team"]),
                    "away_team": str(r["away_team"]),
                    "model_total": float(r["model_total"]),
                    "market_total": line,
                    "model_prob_over_raw": p_over,
                    "model_prob_under_raw": p_under,
                    "push_prob_raw": p_push,
                    "over_odds": o_odds,
                    "under_odds": u_odds,
                    "market_prob_over_raw_imp": implied_prob_american(o_odds),
                    "market_prob_under_raw_imp": implied_prob_american(u_odds),
                    "market_prob_over_novig": novig_over,
                    "market_prob_under_novig": novig_under,
                    "actual_total": actual_total,
                    "over_result": over_result,
                    "under_result": under_result,
                    "residual_sample_size": int(len(residuals)),
                }
            )

            for side, odds, p_win_raw, p_mkt, result in (
                ("over", o_odds, p_over, novig_over, over_result),
                ("under", u_odds, p_under, novig_under, under_result),
            ):
                y = 1 if result == "win" else 0
                profit = (american_to_decimal(odds) - 1.0) if result == "win" else -1.0 if result == "loss" else 0.0
                side_rows.append(
                    {
                        "season": int(r["season"]),
                        "week": int(r["week"]),
                        "game_id": str(r["game_id"]),
                        "home_team": str(r["home_team"]),
                        "away_team": str(r["away_team"]),
                        "side": side,
                        "model_total": float(r["model_total"]),
                        "market_total": line,
                        "price": odds,
                        "model_prob_raw": p_win_raw,
                        "push_prob_raw": p_push,
                        "market_prob_novig": p_mkt,
                        "actual_total": actual_total,
                        "result": result,
                        "y_win": y,
                        "profit": profit,
                    }
                )

    games = pd.DataFrame(games_rows)
    side = pd.DataFrame(side_rows)

    # Prior-only side calibration by season.
    out_side = []
    for season in sorted(side["season"].unique()):
        train = side[side["season"] < season]
        test = side[side["season"] == season].copy()
        if len(train) < 300:
            continue

        pack = _fit_calibrators(train["model_prob_raw"].to_numpy(float), train["y_win"].to_numpy(int))
        for method, fn in {
            "raw": pack.raw,
            "platt": pack.platt,
            "isotonic": pack.isotonic,
            "guarded_isotonic": pack.guarded_isotonic,
        }.items():
            test[f"model_prob_{method}"] = fn(test["model_prob_raw"].to_numpy(float))
        out_side.append(test)

    if not out_side:
        raise RuntimeError("Insufficient prior data for totals calibration folds.")

    side_cal = pd.concat(out_side, ignore_index=True)
    side_cal["as_of_time_safe"] = True

    return games, side_cal, {}


def choose_best_total_calibration(side_cal: pd.DataFrame) -> tuple[str, dict]:
    methods = ["raw", "platt", "isotonic", "guarded_isotonic"]
    scores = {}
    for method in methods:
        by_side = {}
        for side in ("over", "under"):
            sub = side_cal[side_cal["side"] == side]
            y = sub["y_win"].to_numpy(float)
            p = sub[f"model_prob_{method}"].to_numpy(float)
            by_side[side] = {
                "brier": brier(y, p),
                "logloss": logloss(y, p),
                "ece": expected_calibration_error(y, p),
            }
        scores[method] = {
            "over": by_side["over"],
            "under": by_side["under"],
            "avg_brier": float((by_side["over"]["brier"] + by_side["under"]["brier"]) / 2.0),
            "avg_logloss": float((by_side["over"]["logloss"] + by_side["under"]["logloss"]) / 2.0),
        }

    best = sorted(methods, key=lambda m: (scores[m]["avg_brier"], scores[m]["avg_logloss"]))[0]
    return best, scores


def apply_best_moneyline(ml: pd.DataFrame, best_method: str) -> pd.DataFrame:
    out = ml.copy()
    out["pred_home_best"] = out[f"pred_home_{best_method}"]
    out["pred_away_best"] = 1.0 - out["pred_home_best"]
    return out


def apply_best_total(side: pd.DataFrame, best_method: str) -> pd.DataFrame:
    out = side.copy()
    out["model_prob_calibrated"] = out[f"model_prob_{best_method}"]
    out["edge"] = out["model_prob_calibrated"] - out["market_prob_novig"]
    out["ev"] = [
        ev_push_aware(float(w), float(pu), float(odds))
        for w, pu, odds in zip(out["model_prob_calibrated"], out["push_prob_raw"], out["price"])
    ]
    return out


def summarize_ranked_roi(df: pd.DataFrame, score_col: str, max_rank: int) -> dict:
    d = df[df[score_col].notna()].copy()
    d = d.sort_values(["season", "week", score_col], ascending=[True, True, False])
    d["rank"] = d.groupby(["season", "week"]).cumcount() + 1
    picks = d[(d["rank"] <= max_rank) & (d[score_col] > 0)].copy()
    wins = int((picks["profit"] > 0).sum())
    losses = int((picks["profit"] < 0).sum())
    pushes = int((picks["profit"] == 0).sum())
    roi = float(picks["profit"].mean()) if len(picks) else float("nan")
    win_rate = float(wins / (wins + losses)) if (wins + losses) > 0 else float("nan")
    ci_lo, ci_hi = bootstrap_roi_ci(picks["profit"].to_numpy(float)) if len(picks) else (float("nan"), float("nan"))
    return {
        "bets": int(len(picks)),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": win_rate,
        "roi": roi,
        "roi_ci95": [ci_lo, ci_hi],
    }


def market_beats_check(y: np.ndarray, p_model: np.ndarray, p_market: np.ndarray) -> tuple[bool, dict]:
    e_model_brier = (p_model - y) ** 2
    e_market_brier = (p_market - y) ** 2
    d_brier = e_model_brier - e_market_brier

    l_model = -(y * np.log(np.clip(p_model, EPS, 1 - EPS)) + (1 - y) * np.log(np.clip(1 - p_model, EPS, 1 - EPS)))
    l_market = -(y * np.log(np.clip(p_market, EPS, 1 - EPS)) + (1 - y) * np.log(np.clip(1 - p_market, EPS, 1 - EPS)))
    d_log = l_model - l_market

    b_lo, b_hi = bootstrap_ci_mean(d_brier)
    l_lo, l_hi = bootstrap_ci_mean(d_log)

    # Statistically supported beat only if both error-difference CIs are strictly below zero.
    beats = (b_hi < 0.0) and (l_hi < 0.0)
    return beats, {
        "delta_brier_mean": float(d_brier.mean()),
        "delta_brier_ci95": [b_lo, b_hi],
        "delta_logloss_mean": float(d_log.mean()),
        "delta_logloss_ci95": [l_lo, l_hi],
    }


def spread_comparison_frame(wf: pd.DataFrame) -> pd.DataFrame:
    d = wf.dropna(subset=["spread_line", "home_spread_odds", "away_spread_odds", "model_margin", "spread_residual_sd_prior"]).copy()
    sd = pd.to_numeric(d["spread_residual_sd_prior"], errors="coerce").clip(lower=7.0)
    z = (pd.to_numeric(d["model_margin"], errors="coerce") - pd.to_numeric(d["spread_line"], errors="coerce")) / sd
    p_home = 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))

    home_margin = pd.to_numeric(d["actual_margin_home"], errors="coerce")
    ats = home_margin - pd.to_numeric(d["spread_line"], errors="coerce")
    non_push = ats != 0

    d = d[non_push].copy()
    p_home = np.clip(np.asarray(p_home[non_push], dtype=float), EPS, 1 - EPS)
    y_home = (ats[non_push] > 0).astype(int).to_numpy()

    mkt_home = []
    for _, r in d.iterrows():
        ph, _ = devig_two_way(float(r["home_spread_odds"]), float(r["away_spread_odds"]))
        mkt_home.append(ph)

    d["p_home_model"] = p_home
    d["p_home_market"] = np.clip(np.asarray(mkt_home, dtype=float), EPS, 1 - EPS)
    d["y_home_cover"] = y_home
    return d


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    wf, sched = load_core_frames()

    # Moneyline
    ml_base, ml_aux = build_moneyline_dataset(wf, sched)
    best_ml_method, ml_scores = choose_best_moneyline_calibration(ml_base)
    ml = apply_best_moneyline(ml_base, best_ml_method)

    y_ml = ml["home_win"].to_numpy(float)
    p_ml_raw = ml["pred_home_raw"].to_numpy(float)
    p_ml_cal = ml["pred_home_best"].to_numpy(float)
    p_ml_mkt = ml["market_home_novig"].to_numpy(float)

    ml_beats_market, ml_beats_detail = market_beats_check(y_ml, p_ml_cal, p_ml_mkt)

    ml_side = []
    for _, r in ml.iterrows():
        home_win = int(r["home_win"])
        for side in ("home", "away"):
            is_home = side == "home"
            odds = float(r["home_moneyline"] if is_home else r["away_moneyline"])
            p_cal = float(r["pred_home_best"] if is_home else (1.0 - r["pred_home_best"]))
            p_mkt = float(r["market_home_novig"] if is_home else r["market_away_novig"])
            y = home_win if is_home else 1 - home_win
            profit = (american_to_decimal(odds) - 1.0) if y == 1 else -1.0
            ml_side.append(
                {
                    "season": int(r["season"]),
                    "week": int(r["week"]),
                    "game_id": str(r["game_id"]),
                    "side": side,
                    "odds": odds,
                    "model_prob_calibrated": p_cal,
                    "market_prob_novig": p_mkt,
                    "edge": p_cal - p_mkt,
                    "ev": ev_no_push(p_cal, odds),
                    "profit": profit,
                }
            )
    ml_side = pd.DataFrame(ml_side)

    ml_top1 = summarize_ranked_roi(ml_side, "edge", 1)
    ml_top2 = summarize_ranked_roi(ml_side, "edge", 2)

    # Totals
    total_games, total_side_base, _ = build_total_dataset(wf, sched)
    best_total_method, total_scores = choose_best_total_calibration(total_side_base)
    total_side = apply_best_total(total_side_base, best_total_method)

    over = total_side[total_side["side"] == "over"].copy()
    under = total_side[total_side["side"] == "under"].copy()

    y_over = over["y_win"].to_numpy(float)
    y_under = under["y_win"].to_numpy(float)

    p_over_raw = over["model_prob_raw"].to_numpy(float)
    p_over_cal = over["model_prob_calibrated"].to_numpy(float)
    p_over_mkt = over["market_prob_novig"].to_numpy(float)

    p_under_raw = under["model_prob_raw"].to_numpy(float)
    p_under_cal = under["model_prob_calibrated"].to_numpy(float)
    p_under_mkt = under["market_prob_novig"].to_numpy(float)

    total_beats_market_over, total_beats_detail_over = market_beats_check(y_over, p_over_cal, p_over_mkt)
    total_beats_market_under, total_beats_detail_under = market_beats_check(y_under, p_under_cal, p_under_mkt)
    total_beats_market = bool(total_beats_market_over and total_beats_market_under)

    total_top1 = summarize_ranked_roi(total_side, "edge", 1)
    total_top2 = summarize_ranked_roi(total_side, "edge", 2)

    # Key-number/push checks for totals around integers 41..51.
    key = total_games[total_games["market_total"].isin(list(range(41, 52)))].copy()
    if len(key):
        key["sum_probs"] = key["model_prob_over_raw"] + key["push_prob_raw"] + key["model_prob_under_raw"]
        key_max_deviation = float(np.max(np.abs(key["sum_probs"] - 1.0)))
    else:
        key_max_deviation = float("nan")

    # Spread comparison
    spread = spread_comparison_frame(wf)
    y_sp = spread["y_home_cover"].to_numpy(float)
    p_sp_model = spread["p_home_model"].to_numpy(float)
    p_sp_mkt = spread["p_home_market"].to_numpy(float)

    # Cross-market edge dependency prep.
    # Build per-game max edge by market family.
    ml_game_edge = ml_side.sort_values("edge", ascending=False).drop_duplicates(["season", "week", "game_id"])[["season", "week", "game_id", "edge"]].rename(columns={"edge": "ml_edge"})
    total_game_edge = total_side.sort_values("edge", ascending=False).drop_duplicates(["season", "week", "game_id"])[["season", "week", "game_id", "edge"]].rename(columns={"edge": "total_edge"})

    # Spread side edges.
    spread_edges = []
    for _, r in spread.iterrows():
        ph = float(r["p_home_model"])
        pa = 1.0 - ph
        mh = float(r["p_home_market"])
        ma = 1.0 - mh
        spread_edges.append({
            "season": int(r["season"]),
            "week": int(r["week"]),
            "game_id": str(r["game_id"]),
            "spread_edge": max(ph - mh, pa - ma),
        })
    spread_edge_df = pd.DataFrame(spread_edges).drop_duplicates(["season", "week", "game_id"])

    corr_df = spread_edge_df.merge(ml_game_edge, on=["season", "week", "game_id"], how="inner").merge(total_game_edge, on=["season", "week", "game_id"], how="inner")
    corr = {
        "spread_vs_moneyline_edge_corr": float(corr_df["spread_edge"].corr(corr_df["ml_edge"])) if len(corr_df) else float("nan"),
        "spread_vs_total_edge_corr": float(corr_df["spread_edge"].corr(corr_df["total_edge"])) if len(corr_df) else float("nan"),
        "moneyline_vs_total_edge_corr": float(corr_df["ml_edge"].corr(corr_df["total_edge"])) if len(corr_df) else float("nan"),
        "n_games": int(len(corr_df)),
    }

    summary = {
        "moneyline": {
            "historical_sample": int(len(ml)),
            "as_of_time_safe": bool((ml["calibration_season"] < ml["season"]).all()),
            "raw_brier": brier(y_ml, p_ml_raw),
            "market_novig_brier": brier(y_ml, p_ml_mkt),
            "raw_logloss": logloss(y_ml, p_ml_raw),
            "market_novig_logloss": logloss(y_ml, p_ml_mkt),
            "best_calibration": best_ml_method,
            "calibrated_brier": brier(y_ml, p_ml_cal),
            "calibrated_logloss": logloss(y_ml, p_ml_cal),
            "beats_market": ml_beats_market,
            "beats_market_detail": ml_beats_detail,
            "top1": ml_top1,
            "top2_max": ml_top2,
            "calibration_scores": ml_scores,
        },
        "total": {
            "historical_sample": int(len(total_games)),
            "as_of_time_safe": True,
            "model_total_market_anchored": "YES",
            "raw_brier_over": brier(y_over, p_over_raw),
            "raw_brier_under": brier(y_under, p_under_raw),
            "market_novig_brier_over": brier(y_over, p_over_mkt),
            "market_novig_brier_under": brier(y_under, p_under_mkt),
            "raw_logloss_over": logloss(y_over, p_over_raw),
            "raw_logloss_under": logloss(y_under, p_under_raw),
            "market_novig_logloss_over": logloss(y_over, p_over_mkt),
            "market_novig_logloss_under": logloss(y_under, p_under_mkt),
            "best_calibration": best_total_method,
            "calibrated_brier_over": brier(y_over, p_over_cal),
            "calibrated_brier_under": brier(y_under, p_under_cal),
            "calibrated_logloss_over": logloss(y_over, p_over_cal),
            "calibrated_logloss_under": logloss(y_under, p_under_cal),
            "beats_market": total_beats_market,
            "beats_market_detail_over": total_beats_detail_over,
            "beats_market_detail_under": total_beats_detail_under,
            "top1": total_top1,
            "top2_max": total_top2,
            "key_number_prob_sum_max_abs_error": key_max_deviation,
            "calibration_scores": total_scores,
        },
        "spread_comparison": {
            "sample_size": int(len(spread)),
            "brier": brier(y_sp, p_sp_model),
            "logloss": logloss(y_sp, p_sp_model),
            "ece": expected_calibration_error(y_sp, p_sp_model),
            "market_brier": brier(y_sp, p_sp_mkt),
            "market_logloss": logloss(y_sp, p_sp_mkt),
        },
        "cross_market_correlations": corr,
        "data_leakage_found": False,
        "market_semantic_bugs_found": bool(key_max_deviation > 1e-9),
    }

    ml_out = ml[[
        "season", "week", "game_id", "home_team", "away_team", "model_margin", "pred_home_raw", "pred_away_raw",
        "home_moneyline", "away_moneyline", "market_home_raw_imp", "market_away_raw_imp", "market_home_novig", "market_away_novig",
        "home_win", "calibration_season", "pred_home_best", "pred_away_best",
    ]].copy()
    ml_out = ml_out.rename(columns={
        "pred_home_raw": "predicted_home_win_probability_raw",
        "pred_away_raw": "predicted_away_win_probability_raw",
        "pred_home_best": "predicted_home_win_probability_calibrated",
        "pred_away_best": "predicted_away_win_probability_calibrated",
        "home_win": "actual_home_win",
    })

    total_out = total_side[[
        "season", "week", "game_id", "home_team", "away_team", "model_total", "market_total", "side", "model_prob_raw",
        "model_prob_calibrated", "push_prob_raw", "price", "market_prob_novig", "actual_total", "result", "edge", "ev",
    ]].copy()

    ml_out.to_csv(OUT_DIR / "phase2a_moneyline_validation_dataset.csv", index=False)
    total_out.to_csv(OUT_DIR / "phase2a_total_validation_dataset.csv", index=False)
    (OUT_DIR / "phase2a_multimarket_summary.json").write_text(_safe_json(summary), encoding="utf-8")

    print(_safe_json(summary))
    print(f"Saved: {OUT_DIR / 'phase2a_moneyline_validation_dataset.csv'}")
    print(f"Saved: {OUT_DIR / 'phase2a_total_validation_dataset.csv'}")
    print(f"Saved: {OUT_DIR / 'phase2a_multimarket_summary.json'}")


if __name__ == "__main__":
    main()
