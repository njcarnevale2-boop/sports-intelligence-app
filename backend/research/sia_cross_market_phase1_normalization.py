from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sia_multimarket_phase2a_validation import _fit_calibrators, ev_push_aware


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "research_outputs"
MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"
WALKFORWARD_PATH = MODEL_ROOT / "outputs" / "walkforward_multiseason_predictions.csv"
ML_PATH = OUTPUT_DIR / "phase2a_moneyline_validation_dataset.csv"
TOTAL_PATH = OUTPUT_DIR / "phase2a_total_validation_dataset.csv"
SPREAD_BASELINE_PATH = OUTPUT_DIR / "sia_corrected_historical_baseline_report.json"
DB_PATH = REPO_ROOT / "sports_intelligence.db"

EPS = 1e-6
SEED = 2026


METHODS = {
    "A_RAW_EV": "METHOD A - RAW EV",
    "B_CAL_EDGE": "METHOD B - CALIBRATED EDGE",
    "C_ZSCORE": "METHOD C - Z-SCORED WITHIN MARKET",
    "D_PERCENTILE": "METHOD D - PERCENTILE WITHIN MARKET",
    "E_REL_EV": "METHOD E - RELIABILITY-ADJUSTED EV",
    "F_UNCERT": "METHOD F - UNCERTAINTY-PENALIZED",
    "G_SURPRISE": "METHOD G - MARKET-RELATIVE SURPRISE",
}


@dataclass(frozen=True)
class MarketReliability:
    market: str
    weight: float
    uncertainty: float


def implied_prob_american(odds: float) -> float:
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def american_to_decimal(odds: float) -> float:
    return 1.0 + (100.0 / abs(odds) if odds < 0 else odds / 100.0)


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


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    q = np.clip(p, 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, bins + 1)
    bucket = np.clip(np.digitize(q, edges, right=True) - 1, 0, bins - 1)
    out = 0.0
    for b in range(bins):
        m = bucket == b
        if not np.any(m):
            continue
        out += float(m.mean()) * abs(float(q[m].mean()) - float(y[m].mean()))
    return float(out)


def bootstrap_roi_ci(profits: np.ndarray, n_boot: int = 4000) -> tuple[float, float]:
    if len(profits) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(profits), size=(n_boot, len(profits)))
    vals = profits[idx].mean(axis=1)
    return float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _profit(odds: float, result: str) -> float:
    if result == "PUSH":
        return 0.0
    if result == "LOSS":
        return -1.0
    return float(american_to_decimal(odds) - 1.0)


def load_spread_candidates() -> pd.DataFrame:
    wf = pd.read_csv(WALKFORWARD_PATH)
    need = [
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
    wf = wf.dropna(subset=need).copy()
    wf["season"] = wf["season"].astype(int)
    wf["week"] = wf["week"].astype(int)
    wf["actual_margin_home"] = pd.to_numeric(wf["home_score"], errors="coerce") - pd.to_numeric(wf["away_score"], errors="coerce")
    wf = wf.dropna(subset=["actual_margin_home"]).copy()

    rows = []
    for season in sorted(wf["season"].unique()):
        prior = wf[wf["season"] < season]
        if len(prior) < 200:
            continue
        residuals = (prior["actual_margin_home"] - pd.to_numeric(prior["model_margin"], errors="coerce")).dropna().to_numpy(float)
        if len(residuals) < 200:
            continue

        cur = wf[wf["season"] == season].copy()
        for _, r in cur.iterrows():
            model_margin = float(r["model_margin"])
            away_spread = float(r["spread_line"])
            home_spread = -away_spread
            sims = np.rint(model_margin + residuals)

            p_home = float(np.mean(sims > home_spread))
            p_push = float(np.mean(sims == home_spread))
            p_away = max(0.0, 1.0 - p_home - p_push)

            h_odds = float(r["home_spread_odds"])
            a_odds = float(r["away_spread_odds"])
            h_novig, a_novig = devig_two_way(h_odds, a_odds)

            actual = float(r["actual_margin_home"])
            home_result = "WIN" if actual > home_spread else "LOSS" if actual < home_spread else "PUSH"
            away_result = "WIN" if actual < home_spread else "LOSS" if actual > home_spread else "PUSH"

            for side, odds, p_win, p_mkt, result in (
                ("home", h_odds, p_home, h_novig, home_result),
                ("away", a_odds, p_away, a_novig, away_result),
            ):
                rows.append(
                    {
                        "season": int(r["season"]),
                        "week": int(r["week"]),
                        "game_id": str(r["game_id"]),
                        "away_team": str(r["away_team"]),
                        "home_team": str(r["home_team"]),
                        "marketFamily": "SPREAD",
                        "marketKey": "spread",
                        "side": side,
                        "line": home_spread if side == "home" else away_spread,
                        "price": odds,
                        "model_prob_raw": p_win,
                        "push_prob": p_push,
                        "market_prob_novig": p_mkt,
                        "result": result,
                        "y_win": 1 if result == "WIN" else 0,
                        "profit": _profit(odds, result),
                    }
                )

    side = pd.DataFrame(rows)

    calibrated = []
    for season in sorted(side["season"].unique()):
        train = side[(side["season"] < season) & (side["result"] != "PUSH")]
        test = side[side["season"] == season].copy()
        if len(train) < 300:
            continue

        pack = _fit_calibrators(train["model_prob_raw"].to_numpy(float), train["y_win"].to_numpy(int))
        test["model_prob_calibrated"] = pack.guarded_isotonic(test["model_prob_raw"].to_numpy(float))
        calibrated.append(test)

    out = pd.concat(calibrated, ignore_index=True)
    out["edge"] = out["model_prob_calibrated"] - out["market_prob_novig"]
    out["ev"] = [
        ev_push_aware(float(p), float(push), float(odds))
        for p, push, odds in zip(out["model_prob_calibrated"], out["push_prob"], out["price"])
    ]
    return out


def load_moneyline_candidates() -> pd.DataFrame:
    ml = pd.read_csv(ML_PATH)
    rows = []
    for _, r in ml.iterrows():
        home_win = int(r["actual_home_win"])
        for side in ("home", "away"):
            is_home = side == "home"
            price = float(r["home_moneyline"] if is_home else r["away_moneyline"])
            p_cal = float(r["predicted_home_win_probability_calibrated"] if is_home else (1.0 - r["predicted_home_win_probability_calibrated"]))
            p_mkt = float(r["market_home_novig"] if is_home else r["market_away_novig"])
            y = home_win if is_home else 1 - home_win
            result = "WIN" if y == 1 else "LOSS"
            rows.append(
                {
                    "season": int(r["season"]),
                    "week": int(r["week"]),
                    "game_id": str(r["game_id"]),
                    "away_team": str(r["away_team"]),
                    "home_team": str(r["home_team"]),
                    "marketFamily": "MONEYLINE",
                    "marketKey": "moneyline",
                    "side": side,
                    "line": np.nan,
                    "price": price,
                    "model_prob_raw": p_cal,
                    "model_prob_calibrated": p_cal,
                    "push_prob": 0.0,
                    "market_prob_novig": p_mkt,
                    "result": result,
                    "y_win": int(y),
                    "profit": _profit(price, result),
                }
            )

    out = pd.DataFrame(rows)
    out["edge"] = out["model_prob_calibrated"] - out["market_prob_novig"]
    out["ev"] = [ev_push_aware(float(p), 0.0, float(odds)) for p, odds in zip(out["model_prob_calibrated"], out["price"])]
    return out


def load_total_candidates() -> pd.DataFrame:
    total = pd.read_csv(TOTAL_PATH)
    if "profit" not in total.columns:
        total["profit"] = [
            _profit(float(odds), str(result).upper())
            for odds, result in zip(total.get("price", []), total.get("result", []))
        ]
    total = total.rename(columns={"model_prob_calibrated": "model_prob_calibrated"}).copy()
    out = pd.DataFrame(
        {
            "season": total["season"].astype(int),
            "week": total["week"].astype(int),
            "game_id": total["game_id"].astype(str),
            "away_team": total["away_team"].astype(str),
            "home_team": total["home_team"].astype(str),
            "marketFamily": "TOTAL",
            "marketKey": "total",
            "side": total["side"].astype(str),
            "line": pd.to_numeric(total["market_total"], errors="coerce"),
            "price": pd.to_numeric(total["price"], errors="coerce"),
            "model_prob_raw": pd.to_numeric(total["model_prob_raw"], errors="coerce"),
            "model_prob_calibrated": pd.to_numeric(total["model_prob_calibrated"], errors="coerce"),
            "push_prob": pd.to_numeric(total["push_prob_raw"], errors="coerce").fillna(0.0),
            "market_prob_novig": pd.to_numeric(total["market_prob_novig"], errors="coerce"),
            "result": total["result"].astype(str).str.upper(),
            "y_win": (total["result"].astype(str).str.lower() == "win").astype(int),
            "profit": pd.to_numeric(total["profit"], errors="coerce"),
            "edge": pd.to_numeric(total["edge"], errors="coerce"),
            "ev": pd.to_numeric(total["ev"], errors="coerce"),
        }
    )
    return out


def _market_rank_frame(cands: pd.DataFrame) -> pd.DataFrame:
    d = cands.copy()
    d = d.sort_values(["season", "week", "marketFamily", "edge", "ev", "game_id"], ascending=[True, True, True, False, False, True])
    d["marketRank"] = d.groupby(["season", "week", "marketFamily"]).cumcount() + 1
    return d


def _historical_reliability(cands: pd.DataFrame) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for market in ["SPREAD", "MONEYLINE", "TOTAL"]:
        m = cands[cands["marketFamily"] == market].copy()
        non_push = m[m["result"] != "PUSH"].copy()

        y = non_push["y_win"].to_numpy(float)
        p_model = non_push["model_prob_calibrated"].to_numpy(float)
        p_mkt = non_push["market_prob_novig"].to_numpy(float)

        model_brier = brier(y, p_model) if len(non_push) else float("nan")
        mkt_brier = brier(y, p_mkt) if len(non_push) else float("nan")
        model_ll = logloss(y, p_model) if len(non_push) else float("nan")
        mkt_ll = logloss(y, p_mkt) if len(non_push) else float("nan")

        roi = float(m["profit"].mean()) if len(m) else float("nan")
        roi_ci = bootstrap_roi_ci(m["profit"].to_numpy(float)) if len(m) else (float("nan"), float("nan"))

        season_roi = (
            m.groupby("season")["profit"].mean().to_dict() if len(m) else {}
        )
        season_std = float(np.nanstd(list(season_roi.values()))) if season_roi else float("nan")

        clv_cov = float(m["clv"].notna().mean()) if "clv" in m.columns and len(m) else 0.0

        rank_perf: dict[str, dict[str, Any]] = {}
        for r in [1, 2, 3]:
            rr = m[m["marketRank"] == r]
            rank_perf[f"rank{r}"] = {
                "bets": int(len(rr)),
                "roi": float(rr["profit"].mean()) if len(rr) else float("nan"),
                "winRate": float((rr["result"] == "WIN").sum() / max(1, ((rr["result"] != "PUSH").sum()))) if len(rr) else float("nan"),
            }

        # Data-driven reliability components.
        imp_brier = (mkt_brier - model_brier) / max(abs(mkt_brier), EPS) if not math.isnan(model_brier) else -1.0
        imp_ll = (mkt_ll - model_ll) / max(abs(mkt_ll), EPS) if not math.isnan(model_ll) else -1.0
        quality = float(np.clip(0.5 + 0.5 * ((imp_brier + imp_ll) / 2.0), 0.05, 1.0))
        sample_strength = float(np.clip(len(non_push) / (len(non_push) + 300.0), 0.05, 1.0))
        stability = float(np.clip(1.0 / (1.0 + max(0.0, season_std if not math.isnan(season_std) else 1.0)), 0.05, 1.0))

        profiles[market] = {
            "historicalSampleSize": int(len(non_push)),
            "historicalTotalBets": int(len(m)),
            "brier": model_brier,
            "marketNoVigBrier": mkt_brier,
            "brierDelta": model_brier - mkt_brier if len(non_push) else float("nan"),
            "logLoss": model_ll,
            "marketNoVigLogLoss": mkt_ll,
            "logLossDelta": model_ll - mkt_ll if len(non_push) else float("nan"),
            "ece": ece(y, p_model) if len(non_push) else float("nan"),
            "roi": roi,
            "roiCI95": [roi_ci[0], roi_ci[1]],
            "clvCoverage": clv_cov,
            "rankPerformance": rank_perf,
            "seasonROI": {str(k): float(v) for k, v in season_roi.items()},
            "seasonStabilityStd": season_std,
            "reliabilityComponents": {
                "quality": quality,
                "sampleStrength": sample_strength,
                "stability": stability,
            },
            "derivedReliabilityWeight": float((quality * sample_strength * stability) ** (1.0 / 3.0)),
            "uncertainty": float(np.nanstd(m["profit"].to_numpy(float))) if len(m) else float("nan"),
        }
    return profiles


def _prospective_reliability() -> dict[str, dict[str, Any]]:
    if not DB_PATH.exists():
        return {
            "SPREAD": {"prospectiveSampleSize": 0, "prospectiveROI": float("nan"), "prospectiveCLVCoverage": 0.0},
            "MONEYLINE": {"prospectiveSampleSize": 0, "prospectiveROI": float("nan"), "prospectiveCLVCoverage": 0.0},
            "TOTAL": {"prospectiveSampleSize": 0, "prospectiveROI": float("nan"), "prospectiveCLVCoverage": 0.0},
        }

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT i.market_family, o.result, o.profit_per_dollar, o.clv
            FROM shadow_publication_items i
            LEFT JOIN shadow_outcomes o ON o.candidate_id = i.candidate_id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        con.close()
        return {
            "SPREAD": {"prospectiveSampleSize": 0, "prospectiveROI": float("nan"), "prospectiveCLVCoverage": 0.0},
            "MONEYLINE": {"prospectiveSampleSize": 0, "prospectiveROI": float("nan"), "prospectiveCLVCoverage": 0.0},
            "TOTAL": {"prospectiveSampleSize": 0, "prospectiveROI": float("nan"), "prospectiveCLVCoverage": 0.0},
        }
    con.close()

    out: dict[str, dict[str, Any]] = {}
    for market in ["SPREAD", "MONEYLINE", "TOTAL"]:
        m = [r for r in rows if str(r["market_family"]).upper() == market and str(r["result"] or "") in {"WIN", "LOSS", "PUSH"}]
        profits = [float(r["profit_per_dollar"]) for r in m if r["profit_per_dollar"] is not None]
        clv_cov = (sum(1 for r in m if r["clv"] is not None) / len(m)) if m else 0.0
        out[market] = {
            "prospectiveSampleSize": int(len(m)),
            "prospectiveROI": float(np.mean(profits)) if profits else float("nan"),
            "prospectiveCLVCoverage": float(clv_cov),
        }
    return out


def _attach_history_normalizers(cands: pd.DataFrame) -> pd.DataFrame:
    d = cands.sort_values(["season", "week", "game_id", "marketFamily", "side"]).reset_index(drop=True).copy()
    d["zEdge"] = 0.0
    d["zEV"] = 0.0
    d["pctStrength"] = 0.5
    d["surprise"] = 0.0

    history: dict[str, list[tuple[float, float]]] = {"SPREAD": [], "MONEYLINE": [], "TOTAL": []}

    for idx, row in d.iterrows():
        fam = str(row["marketFamily"])
        edge = float(row["edge"])
        ev = float(row["ev"])

        past = history[fam]
        if len(past) >= 20:
            edges = np.array([x[0] for x in past], dtype=float)
            evs = np.array([x[1] for x in past], dtype=float)
            edge_mean = float(edges.mean())
            edge_std = float(edges.std()) if float(edges.std()) > 1e-12 else 1.0
            ev_mean = float(evs.mean())
            ev_std = float(evs.std()) if float(evs.std()) > 1e-12 else 1.0
            pct = float((edges <= edge).mean())
        else:
            edge_mean = float(d[d["marketFamily"] == fam]["edge"].mean())
            edge_std = float(d[d["marketFamily"] == fam]["edge"].std())
            edge_std = edge_std if edge_std > 1e-12 else 1.0
            ev_mean = float(d[d["marketFamily"] == fam]["ev"].mean())
            ev_std = float(d[d["marketFamily"] == fam]["ev"].std())
            ev_std = ev_std if ev_std > 1e-12 else 1.0
            pct = 0.5

        d.at[idx, "zEdge"] = (edge - edge_mean) / edge_std
        d.at[idx, "zEV"] = (ev - ev_mean) / ev_std
        d.at[idx, "pctStrength"] = float(np.clip(pct, 0.0, 1.0))
        d.at[idx, "surprise"] = (edge - edge_mean) / edge_std

        history[fam].append((edge, ev))

    return d


def _method_scored(cands: pd.DataFrame, reliab: dict[str, MarketReliability]) -> dict[str, pd.DataFrame]:
    d = _attach_history_normalizers(cands)
    median_abs_ev = float(np.median(np.abs(d["ev"].to_numpy(float)))) if len(d) else 0.0
    lambda_uncert = median_abs_ev

    out: dict[str, pd.DataFrame] = {}

    a = d.copy()
    a["score"] = a["ev"]
    out["A_RAW_EV"] = a

    b = d.copy()
    b["score"] = b["edge"]
    out["B_CAL_EDGE"] = b

    c = d.copy()
    c["score"] = 0.5 * c["zEdge"] + 0.5 * c["zEV"]
    out["C_ZSCORE"] = c

    dd = d.copy()
    dd["score"] = dd["pctStrength"]
    out["D_PERCENTILE"] = dd

    e = d.copy()
    e["score"] = [float(ev) * reliab[str(fam)].weight for ev, fam in zip(e["ev"], e["marketFamily"])]
    out["E_REL_EV"] = e

    f = d.copy()
    f["score"] = [
        float(ev) - lambda_uncert * reliab[str(fam)].uncertainty
        for ev, fam in zip(f["ev"], f["marketFamily"])
    ]
    out["F_UNCERT"] = f

    g = d.copy()
    g["score"] = g["surprise"]
    out["G_SURPRISE"] = g

    for frame in out.values():
        frame["score"] = pd.to_numeric(frame["score"], errors="coerce").fillna(-999.0)
    return out


def _topk_metrics(scored: pd.DataFrame, k: int) -> dict[str, Any]:
    picks = []
    for (season, week), g in scored.groupby(["season", "week"], sort=True):
        gg = g.sort_values(["score", "edge", "ev"], ascending=[False, False, False])
        gg = gg[gg["score"] > 0].head(k)
        if not gg.empty:
            picks.append(gg)

    if not picks:
        return {
            "bets": 0,
            "W-L-P": "0-0-0",
            "winRate": float("nan"),
            "roi": float("nan"),
            "roiCI95": [float("nan"), float("nan")],
            "seasonROI": {},
            "maxDrawdown": float("nan"),
            "marketComposition": {},
        }

    p = pd.concat(picks, ignore_index=True)
    wins = int((p["result"] == "WIN").sum())
    losses = int((p["result"] == "LOSS").sum())
    pushes = int((p["result"] == "PUSH").sum())

    non_push = max(1, wins + losses)
    roi = float(p["profit"].mean())
    roi_ci = bootstrap_roi_ci(p["profit"].to_numpy(float))

    season_roi = p.groupby("season")["profit"].mean().to_dict()

    eq = p.sort_values(["season", "week"]).copy()
    eq["cum"] = eq["profit"].cumsum()
    eq["peak"] = eq["cum"].cummax()
    eq["dd"] = eq["peak"] - eq["cum"]
    max_dd = float(eq["dd"].max()) if len(eq) else float("nan")

    comp = p["marketFamily"].value_counts(normalize=True).to_dict()

    return {
        "bets": int(len(p)),
        "W-L-P": f"{wins}-{losses}-{pushes}",
        "winRate": float(wins / non_push),
        "roi": roi,
        "roiCI95": [roi_ci[0], roi_ci[1]],
        "seasonROI": {str(k): float(v) for k, v in season_roi.items()},
        "maxDrawdown": max_dd,
        "marketComposition": {k: float(v) for k, v in comp.items()},
    }


def _dominance_metrics(scored: pd.DataFrame) -> dict[str, Any]:
    top3 = []
    for _, g in scored.groupby(["season", "week"], sort=True):
        gg = g.sort_values(["score", "edge", "ev"], ascending=[False, False, False]).head(3)
        if not gg.empty:
            top3.append(gg)

    if not top3:
        return {
            "shareByMarketFamily": {},
            "weeksAllThreeSameMarket": 0,
            "weeksAllPicksSameGame": 0,
            "weeksAnalyzed": 0,
        }

    t = pd.concat(top3, ignore_index=True)
    share = t["marketFamily"].value_counts(normalize=True).to_dict()

    weeks_all_same_market = 0
    weeks_all_same_game = 0
    weeks = 0
    for _, w in t.groupby(["season", "week"]):
        weeks += 1
        if len(w) >= 3 and len(set(w["marketFamily"].tolist())) == 1:
            weeks_all_same_market += 1
        if len(w) >= 2 and len(set(w["game_id"].tolist())) == 1:
            weeks_all_same_game += 1

    return {
        "shareByMarketFamily": {k: float(v) for k, v in share.items()},
        "weeksAllThreeSameMarket": int(weeks_all_same_market),
        "weeksAllPicksSameGame": int(weeks_all_same_game),
        "weeksAnalyzed": int(weeks),
    }


def _correlation_report(cands: pd.DataFrame) -> dict[str, Any]:
    pairs = []
    best = cands.sort_values(["season", "week", "game_id", "marketFamily", "edge"], ascending=[True, True, True, True, False]).drop_duplicates(["season", "week", "game_id", "marketFamily"])

    for (a, b) in [("SPREAD", "MONEYLINE"), ("SPREAD", "TOTAL"), ("MONEYLINE", "TOTAL")]:
        xa = best[best["marketFamily"] == a][["season", "week", "game_id", "y_win", "profit"]].rename(columns={"y_win": "y_a", "profit": "p_a"})
        xb = best[best["marketFamily"] == b][["season", "week", "game_id", "y_win", "profit"]].rename(columns={"y_win": "y_b", "profit": "p_b"})
        m = xa.merge(xb, on=["season", "week", "game_id"], how="inner")
        if len(m) < 10:
            pairs.append({"pair": f"{a}+{b}", "n": int(len(m)), "outcomeCorrelation": float("nan"), "returnCorrelation": float("nan")})
            continue
        pairs.append(
            {
                "pair": f"{a}+{b}",
                "n": int(len(m)),
                "outcomeCorrelation": float(m["y_a"].corr(m["y_b"])),
                "returnCorrelation": float(m["p_a"].corr(m["p_b"])),
            }
        )

    corr_issue = any(abs(float(p["returnCorrelation"])) > 0.30 for p in pairs if not math.isnan(float(p["returnCorrelation"])))
    return {"pairwise": pairs, "correlationIssue": corr_issue}


def _spread_only_control(cands: pd.DataFrame) -> dict[str, Any]:
    spread = cands[cands["marketFamily"] == "SPREAD"].copy()
    spread["score"] = spread["edge"]
    return {
        "Top1": _topk_metrics(spread, 1),
        "Top2": _topk_metrics(spread, 2),
        "Top3": _topk_metrics(spread, 3),
    }


def _build_reliability_objects(profiles: dict[str, dict[str, Any]]) -> dict[str, MarketReliability]:
    out = {}
    for market in ["SPREAD", "MONEYLINE", "TOTAL"]:
        p = profiles[market]
        out[market] = MarketReliability(
            market=market,
            weight=float(np.clip(p["derivedReliabilityWeight"], 0.05, 1.0)),
            uncertainty=float(np.clip(_safe_float(p["uncertainty"], 1.0), 0.01, 2.0)),
        )
    return out


def _pre_registered_promotion_criteria() -> list[str]:
    return [
        "Cross-market method must match or beat spread-only Top1 ROI with non-overlapping 95% ROI CI downside no worse than -2pp.",
        "Brier and log loss deltas versus market no-vig must not degrade beyond +0.005 in MONEYLINE or TOTAL.",
        "Prospective shadow sample per non-spread market must exceed 300 graded bets with CLV coverage >= 70%.",
        "Rank #1 and #2 must remain stable across at least two consecutive seasons/prospective windows.",
        "No method may allocate >85% of Top3 picks to one market family over the evaluation window.",
        "Same-game correlation controls must reduce return correlation magnitude to <= 0.25 on average.",
        "Normalization methodology must be fixed before the next prospective window and versioned in snapshots.",
        "crossMarketComparable may only flip after a shadow-only go/no-go review with signed evidence report.",
    ]


def run() -> dict[str, Any]:
    spread = load_spread_candidates()
    ml = load_moneyline_candidates()
    total = load_total_candidates()

    cands = pd.concat([spread, ml, total], ignore_index=True)
    cands = _market_rank_frame(cands)

    hist_profiles = _historical_reliability(cands)
    pro_profiles = _prospective_reliability()

    for market in ["SPREAD", "MONEYLINE", "TOTAL"]:
        hist_profiles[market].update(pro_profiles.get(market, {}))

    reliab = _build_reliability_objects(hist_profiles)
    method_frames = _method_scored(cands, reliab)

    method_results: dict[str, Any] = {}
    best_method = None
    best_top1_roi = -999.0

    for key, frame in method_frames.items():
        top1 = _topk_metrics(frame, 1)
        top2 = _topk_metrics(frame, 2)
        top3 = _topk_metrics(frame, 3)
        dominance = _dominance_metrics(frame)
        method_results[key] = {
            "label": METHODS[key],
            "Top1": top1,
            "Top2": top2,
            "Top3": top3,
            "dominance": dominance,
        }
        roi1 = _safe_float(top1["roi"], -999.0)
        if roi1 > best_top1_roi:
            best_top1_roi = roi1
            best_method = key

    spread_control = _spread_only_control(cands)
    corr = _correlation_report(cands)

    best = method_results[str(best_method)] if best_method else None
    spread_top1_roi = _safe_float(spread_control["Top1"]["roi"], float("nan"))
    beats_control = "INCONCLUSIVE"
    if best is not None:
        best_roi = _safe_float(best["Top1"]["roi"], float("nan"))
        if not math.isnan(best_roi) and not math.isnan(spread_top1_roi):
            beats_control = "YES" if best_roi > spread_top1_roi else "NO"

    cross_market_ready = False
    if best is not None:
        dom = best["dominance"]
        max_share = max(dom["shareByMarketFamily"].values()) if dom["shareByMarketFamily"] else 1.0
        cross_market_ready = bool(
            beats_control == "YES"
            and max_share < 0.85
            and not corr["correlationIssue"]
            and all(hist_profiles[m]["prospectiveSampleSize"] >= 300 for m in ["MONEYLINE", "TOTAL"])
        )

    baseline_spread_report = json.loads(SPREAD_BASELINE_PATH.read_text()) if SPREAD_BASELINE_PATH.exists() else {}

    summary = {
        "datasetLabel": "MARKET-REFERENCE CROSS-MARKET BACKTEST",
        "historicalCrossMarketSample": {
            "rows": int(len(cands)),
            "seasons": sorted([int(x) for x in cands["season"].unique().tolist()]),
            "weeks": int(cands[["season", "week"]].drop_duplicates().shape[0]),
        },
        "spreadReliabilityProfile": hist_profiles["SPREAD"],
        "moneylineReliabilityProfile": hist_profiles["MONEYLINE"],
        "totalReliabilityProfile": hist_profiles["TOTAL"],
        "methods": method_results,
        "spreadOnlyControl": spread_control,
        "bestCrossMarketMethod": {
            "methodKey": best_method,
            "label": METHODS[best_method] if best_method else None,
            "results": best,
        },
        "crossMarketMethodBeatsSpreadControl": beats_control,
        "marketCompositionOfBestMethod": best["Top3"]["marketComposition"] if best else {},
        "marketDominanceIssue": bool(best and max(best["dominance"]["shareByMarketFamily"].values()) > 0.85) if best and best["dominance"]["shareByMarketFamily"] else False,
        "correlation": corr,
        "rankReliability": {
            "rank1": {
                "spread": hist_profiles["SPREAD"]["rankPerformance"]["rank1"],
                "moneyline": hist_profiles["MONEYLINE"]["rankPerformance"]["rank1"],
                "total": hist_profiles["TOTAL"]["rankPerformance"]["rank1"],
            },
            "rank2": {
                "spread": hist_profiles["SPREAD"]["rankPerformance"]["rank2"],
                "moneyline": hist_profiles["MONEYLINE"]["rankPerformance"]["rank2"],
                "total": hist_profiles["TOTAL"]["rankPerformance"]["rank2"],
            },
            "rank3": {
                "spread": hist_profiles["SPREAD"]["rankPerformance"]["rank3"],
                "moneyline": hist_profiles["MONEYLINE"]["rankPerformance"]["rank3"],
                "total": hist_profiles["TOTAL"]["rankPerformance"]["rank3"],
            },
        },
        "recommendedMaxFutureSIAPicks": "variable (2-3) until rank3 reliability improves",
        "globalShadowScoreReady": True,
        "prospectiveValidationPlan": "Store experimental globalResearchScore/globalResearchRank per shadow candidate snapshot and validate on 300+ graded prospective bets per market.",
        "promotionCriteria": _pre_registered_promotion_criteria(),
        "crossMarketComparabilityReady": cross_market_ready,
        "safeToEnableUniversalSIA3": False,
        "guardrails": {
            "productionEligibilityChanged": False,
            "productionSIA3Changed": False,
            "spreadEngineChanged": False,
            "configPyTouched": False,
        },
        "spreadBaselineReference": baseline_spread_report.get("best_calibrated", {}),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "phase1_cross_market_normalization_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    for method_key, frame in method_frames.items():
        cols = [
            "season",
            "week",
            "game_id",
            "marketFamily",
            "side",
            "line",
            "price",
            "model_prob_calibrated",
            "market_prob_novig",
            "edge",
            "push_prob",
            "ev",
            "marketRank",
            "score",
            "result",
            "profit",
        ]
        frame[cols].to_csv(OUTPUT_DIR / f"phase1_cross_market_{method_key.lower()}_rankings.csv", index=False)

    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == "__main__":
    run()
