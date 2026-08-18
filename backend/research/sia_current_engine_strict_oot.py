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
RNG_SEED = 7
BOOTSTRAP_N = 3000

PROB_BUCKETS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 1.01]
PROB_BUCKET_LABELS = ["50-55", "55-60", "60-65", "65-70", "70-75", "75-80", "80+"]

EDGE_BANDS = [0.0, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 99.0]
EDGE_BAND_LABELS = ["0-2pp", "2-5pp", "5-8pp", "8-10pp", "10-15pp", "15-20pp", "20pp+"]

EV_BANDS = [0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 99.0]
EV_BAND_LABELS = ["0-2%", "2-5%", "5-10%", "10-15%", "15-20%", "20%+"]


@dataclass
class OutcomeProbabilities:
    win: float
    push: float
    loss: float


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


def spread_probs_from_residual_pool(model_margin_home: float, spread_line_home: float, side: str, margin_residuals: np.ndarray) -> OutcomeProbabilities:
    margins = np.rint(model_margin_home + margin_residuals)

    side_key = str(side).strip().lower()
    if side_key == "home":
        ats_value = margins + spread_line_home
    elif side_key == "away":
        ats_value = -margins + spread_line_home
    else:
        raise ValueError(f"Unsupported side: {side}")

    win = float(np.mean(ats_value > 0))
    push = float(np.mean(ats_value == 0))
    loss = max(0.0, 1.0 - win - push)
    return OutcomeProbabilities(win=win, push=push, loss=loss)


def actual_result(model_side: str, actual_margin_home: float, spread_line_home: float) -> str:
    ats = actual_margin_home + spread_line_home if model_side == "home" else -actual_margin_home + spread_line_home
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


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not WALKFORWARD_PATH.exists():
        raise FileNotFoundError(f"Missing file: {WALKFORWARD_PATH}")
    if not VALIDATION_SPREAD_PATH.exists():
        raise FileNotFoundError(f"Missing file: {VALIDATION_SPREAD_PATH}")

    wf = pd.read_csv(WALKFORWARD_PATH)
    wf = wf[wf["season"].isin(SEASONS)].copy()

    needed = [
        "season",
        "week",
        "game_id",
        "spread_line",
        "home_spread_odds",
        "away_spread_odds",
        "model_margin",
        "home_score",
        "away_score",
    ]
    wf = wf.dropna(subset=needed)

    val = pd.read_csv(VALIDATION_SPREAD_PATH)
    val = val[val["season"].isin(SEASONS)].copy()

    val_needed = ["season", "week", "game_id", "side", "edge"]
    val = val.dropna(subset=val_needed)

    val = val[["season", "week", "game_id", "side", "edge"]].copy()
    val = val.rename(columns={"side": "production_side", "edge": "production_rank_score"})

    merged = wf.merge(val, on=["season", "week", "game_id"], how="left", validate="one_to_one")

    merged["actual_margin_home"] = pd.to_numeric(merged["home_score"], errors="coerce") - pd.to_numeric(merged["away_score"], errors="coerce")
    merged["residual_margin"] = merged["actual_margin_home"] - pd.to_numeric(merged["model_margin"], errors="coerce")

    merged = merged.dropna(subset=["actual_margin_home", "residual_margin", "production_side", "production_rank_score"]).copy()
    merged["production_side"] = merged["production_side"].astype(str).str.lower().str.strip()
    merged = merged[merged["production_side"].isin(["home", "away"])].copy()

    merged = merged.sort_values(["season", "week", "game_id"]).reset_index(drop=True)
    return merged, val


def build_strict_oot_dataset() -> pd.DataFrame:
    df, _ = load_data()

    rows: list[dict[str, Any]] = []
    week_keys = sorted(df[["season", "week"]].drop_duplicates().itertuples(index=False, name=None))

    for season, week in week_keys:
        prior = df[(df["season"] < season) | ((df["season"] == season) & (df["week"] < week))]
        residual_pool = prior["residual_margin"].dropna().to_numpy(float)

        wk = df[(df["season"] == season) & (df["week"] == week)]

        eligible = len(residual_pool) >= MIN_RESIDUAL_SAMPLE
        warmup_reason = None if eligible else f"WARMUP_INELIGIBLE_RESIDUAL_SAMPLE_LT_{MIN_RESIDUAL_SAMPLE}"

        for _, r in wk.iterrows():
            spread_line = float(r["spread_line"])
            home_odds = float(r["home_spread_odds"])
            away_odds = float(r["away_spread_odds"])
            model_margin = float(r["model_margin"])
            side = str(r["production_side"])

            if side == "home":
                odds = home_odds
            else:
                odds = away_odds

            ph_mkt, pa_mkt = devig_two_way(home_odds, away_odds)
            market_prob = ph_mkt if side == "home" else pa_mkt

            result = actual_result(side, float(r["actual_margin_home"]), spread_line)
            y = 1.0 if result == "win" else 0.0 if result == "loss" else np.nan

            win_prob = np.nan
            push_prob = np.nan
            loss_prob = np.nan
            current_ev = np.nan
            edge = np.nan

            if eligible:
                probs = spread_probs_from_residual_pool(
                    model_margin_home=model_margin,
                    spread_line_home=spread_line,
                    side=side,
                    margin_residuals=residual_pool,
                )
                win_prob = probs.win
                push_prob = probs.push
                loss_prob = probs.loss
                current_ev = ev_push_aware(win_prob, push_prob, odds)
                edge = win_prob - market_prob

            rows.append(
                {
                    "season": int(season),
                    "week": int(week),
                    "game_id": str(r["game_id"]),
                    "side": side,
                    "spread_line_home": spread_line,
                    "odds": odds,
                    "market_prob": market_prob,
                    "production_rank_score": float(r["production_rank_score"]),
                    "eligible": bool(eligible),
                    "warmup_reason": warmup_reason,
                    "residual_sample_size": int(len(residual_pool)),
                    "current_win_prob": win_prob,
                    "current_push_prob": push_prob,
                    "current_loss_prob": loss_prob,
                    "current_ev": current_ev,
                    "current_edge": edge,
                    "result": result,
                    "is_push": 1 if result == "push" else 0,
                    "y": y,
                    "flat_profit": flat_profit(result, odds),
                }
            )

    return pd.DataFrame(rows)


def calibration_table(df: pd.DataFrame, prob_col: str) -> list[dict[str, Any]]:
    d = df[(df["is_push"] == 0) & df[prob_col].notna() & df["y"].notna()].copy()
    d["bucket"] = pd.cut(d[prob_col], bins=PROB_BUCKETS, labels=PROB_BUCKET_LABELS, right=False, include_lowest=True)

    rows: list[dict[str, Any]] = []
    for label in PROB_BUCKET_LABELS:
        g = d[d["bucket"] == label]
        n = int(len(g))
        if n == 0:
            rows.append({"bucket": label, "N": 0, "avg_predicted": None, "actual_rate": None, "gap_pp": None})
        else:
            p = float(g[prob_col].mean())
            a = float(g["y"].mean())
            rows.append({"bucket": label, "N": n, "avg_predicted": p, "actual_rate": a, "gap_pp": (a - p) * 100.0})
    return rows


def extreme_table(df: pd.DataFrame, prob_col: str) -> dict[str, dict[str, Any]]:
    d = df[(df["is_push"] == 0) & df[prob_col].notna() & df["y"].notna()].copy()
    out: dict[str, dict[str, Any]] = {}
    for t in [0.70, 0.75, 0.80]:
        k = f">={int(t*100)}"
        g = d[d[prob_col] >= t]
        if g.empty:
            out[k] = {"N": 0, "avg_prob": None, "actual_rate": None, "gap_pp": None}
        else:
            p = float(g[prob_col].mean())
            a = float(g["y"].mean())
            out[k] = {"N": int(len(g)), "avg_prob": p, "actual_rate": a, "gap_pp": (a - p) * 100.0}
    return out


def edge_band_table(df: pd.DataFrame) -> list[dict[str, Any]]:
    d = df[df["current_edge"].notna()].copy()
    d = d[d["current_edge"] >= 0]
    d["band"] = pd.cut(d["current_edge"], bins=EDGE_BANDS, labels=EDGE_BAND_LABELS, right=False, include_lowest=True)

    rows: list[dict[str, Any]] = []
    for label in EDGE_BAND_LABELS:
        g = d[d["band"] == label]
        n = int(len(g))
        if n == 0:
            rows.append(
                {
                    "band": label,
                    "N": 0,
                    "win_rate": None,
                    "push_rate": None,
                    "roi": None,
                    "avg_modeled_probability": None,
                    "avg_modeled_ev": None,
                }
            )
            continue

        nonpush = g[g["is_push"] == 0]
        rows.append(
            {
                "band": label,
                "N": n,
                "win_rate": float(nonpush["y"].mean()) if len(nonpush) else None,
                "push_rate": float(g["is_push"].mean()),
                "roi": float(g["flat_profit"].mean()),
                "avg_modeled_probability": float(g["current_win_prob"].mean()),
                "avg_modeled_ev": float(g["current_ev"].mean()),
            }
        )
    return rows


def ev_band_table(df: pd.DataFrame) -> list[dict[str, Any]]:
    d = df[df["current_ev"].notna()].copy()
    d = d[d["current_ev"] >= 0]
    d["band"] = pd.cut(d["current_ev"], bins=EV_BANDS, labels=EV_BAND_LABELS, right=False, include_lowest=True)

    rows: list[dict[str, Any]] = []
    for label in EV_BAND_LABELS:
        g = d[d["band"] == label]
        n = int(len(g))
        if n == 0:
            rows.append(
                {
                    "band": label,
                    "N": 0,
                    "win_rate": None,
                    "push_rate": None,
                    "roi": None,
                    "avg_modeled_probability": None,
                    "avg_modeled_ev": None,
                }
            )
            continue

        nonpush = g[g["is_push"] == 0]
        rows.append(
            {
                "band": label,
                "N": n,
                "win_rate": float(nonpush["y"].mean()) if len(nonpush) else None,
                "push_rate": float(g["is_push"].mean()),
                "roi": float(g["flat_profit"].mean()),
                "avg_modeled_probability": float(g["current_win_prob"].mean()),
                "avg_modeled_ev": float(g["current_ev"].mean()),
            }
        )
    return rows


def simulate_ranking(df: pd.DataFrame, score_col: str, max_picks: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    d = df[df[score_col].notna()].copy()
    d = d.sort_values(["season", "week", score_col], ascending=[True, True, False]).copy()
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

    summary = {
        "weeks": int(df[["season", "week"]].drop_duplicates().shape[0]),
        "weeks_with_picks": int(picks[["season", "week"]].drop_duplicates().shape[0]),
        "bets": int(len(picks)),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate_ex_push": float(wins / denom),
        "roi": float(picks["flat_profit"].mean()) if len(picks) else None,
        "by_season": by_season,
        "by_rank": by_rank,
    }

    return picks, summary


def bootstrap_ci_week_level(
    picks_df: pd.DataFrame,
    n_bootstrap: int = BOOTSTRAP_N,
    seed: int = RNG_SEED,
) -> dict[str, Any]:
    if picks_df.empty:
        return {"roi_ci_95": [None, None], "win_rate_ci_95": [None, None], "replicates": 0}

    week_keys = picks_df[["season", "week"]].drop_duplicates().reset_index(drop=True)
    n_weeks = len(week_keys)
    if n_weeks == 0:
        return {"roi_ci_95": [None, None], "win_rate_ci_95": [None, None], "replicates": 0}

    week_stats = (
        picks_df.groupby(["season", "week"])
        .agg(
            profit_sum=("flat_profit", "sum"),
            bets=("flat_profit", "size"),
            wins=("y", lambda s: int((s == 1.0).sum())),
            nonpush=("is_push", lambda s: int((s == 0).sum())),
        )
        .reset_index(drop=True)
    )

    profit_sum = week_stats["profit_sum"].to_numpy(float)
    bets = week_stats["bets"].to_numpy(float)
    wins = week_stats["wins"].to_numpy(float)
    nonpush = week_stats["nonpush"].to_numpy(float)

    rng = np.random.default_rng(seed)
    sampled_idx = rng.integers(low=0, high=n_weeks, size=(n_bootstrap, n_weeks))

    roi_num = profit_sum[sampled_idx].sum(axis=1)
    roi_den = bets[sampled_idx].sum(axis=1)
    wr_num = wins[sampled_idx].sum(axis=1)
    wr_den = nonpush[sampled_idx].sum(axis=1)

    valid = wr_den > 0
    if not np.any(valid):
        return {"roi_ci_95": [None, None], "win_rate_ci_95": [None, None], "replicates": 0}

    roi_vals = roi_num[valid] / roi_den[valid]
    wr_vals = wr_num[valid] / wr_den[valid]

    roi_ci = [float(np.quantile(roi_vals, 0.025)), float(np.quantile(roi_vals, 0.975))]
    wr_ci = [float(np.quantile(wr_vals, 0.025)), float(np.quantile(wr_vals, 0.975))]

    return {"roi_ci_95": roi_ci, "win_rate_ci_95": wr_ci, "replicates": int(valid.sum())}


def ci_for_ranking_method(df: pd.DataFrame, score_col: str) -> dict[str, Any]:
    out: dict[str, Any] = {}

    picks_top1, _ = simulate_ranking(df, score_col=score_col, max_picks=1)
    picks_top2, _ = simulate_ranking(df, score_col=score_col, max_picks=2)
    picks_top3, _ = simulate_ranking(df, score_col=score_col, max_picks=3)

    out["top1"] = bootstrap_ci_week_level(picks_top1)
    out["top2_max"] = bootstrap_ci_week_level(picks_top2)
    out["top3_max"] = bootstrap_ci_week_level(picks_top3)

    for rank in [1, 2, 3]:
        rank_df = picks_top3[picks_top3["pick_rank"] == rank].copy()
        out[f"rank_{rank}"] = bootstrap_ci_week_level(rank_df)

    return out


def build_report() -> dict[str, Any]:
    full = build_strict_oot_dataset()

    warmup = full[~full["eligible"]].copy()
    eligible = full[full["eligible"]].copy()

    scored = eligible[(eligible["is_push"] == 0) & eligible["current_win_prob"].notna() & eligible["y"].notna()].copy()

    y = scored["y"].to_numpy(float)
    p_cur = scored["current_win_prob"].to_numpy(float)
    p_mkt = scored["market_prob"].to_numpy(float)

    current_brier = brier(y, p_cur)
    market_brier = brier(y, p_mkt)
    current_logloss = logloss(y, p_cur)
    market_logloss = logloss(y, p_mkt)

    production_top1_picks, production_top1 = simulate_ranking(eligible, "production_rank_score", 1)
    production_top2_picks, production_top2 = simulate_ranking(eligible, "production_rank_score", 2)
    production_top3_picks, production_top3 = simulate_ranking(eligible, "production_rank_score", 3)

    current_ev_top1_picks, current_ev_top1 = simulate_ranking(eligible, "current_ev", 1)
    current_ev_top2_picks, current_ev_top2 = simulate_ranking(eligible, "current_ev", 2)
    current_ev_top3_picks, current_ev_top3 = simulate_ranking(eligible, "current_ev", 3)

    current_edge_top1_picks, current_edge_top1 = simulate_ranking(eligible, "current_edge", 1)
    current_edge_top2_picks, current_edge_top2 = simulate_ranking(eligible, "current_edge", 2)
    current_edge_top3_picks, current_edge_top3 = simulate_ranking(eligible, "current_edge", 3)

    uncertainty = {
        "production_ranking": {
            "top1": bootstrap_ci_week_level(production_top1_picks),
            "top2_max": bootstrap_ci_week_level(production_top2_picks),
            "top3_max": bootstrap_ci_week_level(production_top3_picks),
            "rank_1": bootstrap_ci_week_level(production_top3_picks[production_top3_picks["pick_rank"] == 1]),
            "rank_2": bootstrap_ci_week_level(production_top3_picks[production_top3_picks["pick_rank"] == 2]),
            "rank_3": bootstrap_ci_week_level(production_top3_picks[production_top3_picks["pick_rank"] == 3]),
        },
        "current_ev_ranking": {
            "top1": bootstrap_ci_week_level(current_ev_top1_picks),
            "top2_max": bootstrap_ci_week_level(current_ev_top2_picks),
            "top3_max": bootstrap_ci_week_level(current_ev_top3_picks),
            "rank_1": bootstrap_ci_week_level(current_ev_top3_picks[current_ev_top3_picks["pick_rank"] == 1]),
            "rank_2": bootstrap_ci_week_level(current_ev_top3_picks[current_ev_top3_picks["pick_rank"] == 2]),
            "rank_3": bootstrap_ci_week_level(current_ev_top3_picks[current_ev_top3_picks["pick_rank"] == 3]),
        },
        "current_edge_ranking": {
            "top1": bootstrap_ci_week_level(current_edge_top1_picks),
            "top2_max": bootstrap_ci_week_level(current_edge_top2_picks),
            "top3_max": bootstrap_ci_week_level(current_edge_top3_picks),
            "rank_1": bootstrap_ci_week_level(current_edge_top3_picks[current_edge_top3_picks["pick_rank"] == 1]),
            "rank_2": bootstrap_ci_week_level(current_edge_top3_picks[current_edge_top3_picks["pick_rank"] == 2]),
            "rank_3": bootstrap_ci_week_level(current_edge_top3_picks[current_edge_top3_picks["pick_rank"] == 3]),
        },
    }

    report = {
        "methodology": {
            "objective": "strict out-of-time validation of current production empirical residual spread engine",
            "no_lookahead": "week-by-week walk-forward; each test week uses only residuals from prior weeks",
            "min_residual_sample": MIN_RESIDUAL_SAMPLE,
            "eligible_seasons": SEASONS,
            "production_modified": False,
            "config_touched": False,
            "production_ranking_definition": "proxy from historical production validation file using production_rank_score=edge from validation_spread_bets",
        },
        "sample": {
            "total_rows": int(len(full)),
            "eligible_rows": int(len(eligible)),
            "warmup_ineligible_rows": int(len(warmup)),
            "eligible_nonpush_scored": int(len(scored)),
            "weeks_total": int(full[["season", "week"]].drop_duplicates().shape[0]),
            "weeks_eligible": int(eligible[["season", "week"]].drop_duplicates().shape[0]),
            "weeks_warmup": int(warmup[["season", "week"]].drop_duplicates().shape[0]),
        },
        "quality": {
            "current_engine_brier": current_brier,
            "market_brier": market_brier,
            "current_engine_logloss": current_logloss,
            "market_logloss": market_logloss,
            "beats_market_brier": bool(current_brier < market_brier),
            "beats_market_logloss": bool(current_logloss < market_logloss),
        },
        "calibration_table": calibration_table(eligible, "current_win_prob"),
        "extreme_probabilities": extreme_table(eligible, "current_win_prob"),
        "edge_bands": edge_band_table(eligible),
        "ev_bands": ev_band_table(eligible),
        "rankings": {
            "production_ranking": {
                "top1": production_top1,
                "top2_max": production_top2,
                "top3_max": production_top3,
            },
            "current_ev_ranking": {
                "top1": current_ev_top1,
                "top2_max": current_ev_top2,
                "top3_max": current_ev_top3,
            },
            "current_edge_ranking": {
                "top1": current_edge_top1,
                "top2_max": current_edge_top2,
                "top3_max": current_edge_top3,
            },
        },
        "uncertainty": uncertainty,
        "notes": [
            "This study is research-only and does not modify any production threshold, ranking, API, or UI logic.",
            "Historical file lacks direct per-row Sports Intelligence Score; production ranking is represented by the available historical production rank proxy score in validation_spread_bets.",
        ],
    }

    return report


def save_report(report: dict[str, Any]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "sia_current_engine_strict_oot_report.json"
    md_path = OUTPUT_DIR / "sia_current_engine_strict_oot_report.md"

    json_path.write_text(json.dumps(report, indent=2))

    q = report["quality"]
    s = report["sample"]

    lines = [
        "# SIA Strict OOT Validation (Current Production Engine)",
        "",
        "## Sample",
        f"- Total rows: {s['total_rows']}",
        f"- Eligible rows: {s['eligible_rows']}",
        f"- Warmup rows: {s['warmup_ineligible_rows']}",
        f"- Eligible non-push scored: {s['eligible_nonpush_scored']}",
        "",
        "## Scoring",
        f"- Current engine Brier: {q['current_engine_brier']:.6f}",
        f"- Market Brier: {q['market_brier']:.6f}",
        f"- Current engine LogLoss: {q['current_engine_logloss']:.6f}",
        f"- Market LogLoss: {q['market_logloss']:.6f}",
        f"- Beats market Brier: {q['beats_market_brier']}",
        f"- Beats market LogLoss: {q['beats_market_logloss']}",
        "",
        "## Notes",
    ]
    for n in report["notes"]:
        lines.append(f"- {n}")

    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


def main() -> None:
    report = build_report()
    json_path, md_path = save_report(report)

    print("STRICT CURRENT-ENGINE OOT RESEARCH COMPLETE")
    print(f"Report JSON: {json_path}")
    print(f"Report MD: {md_path}")
    print(f"Eligible scored sample: {report['sample']['eligible_nonpush_scored']}")
    print(f"Current Brier: {report['quality']['current_engine_brier']:.6f}")
    print(f"Market Brier: {report['quality']['market_brier']:.6f}")
    print(f"Current LogLoss: {report['quality']['current_engine_logloss']:.6f}")
    print(f"Market LogLoss: {report['quality']['market_logloss']:.6f}")


if __name__ == "__main__":
    main()
