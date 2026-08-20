from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.services.probability_engine import fair_price_from_win_push
from app.services.shadow_markets import PHASE2B_MARKET_FAMILIES, _connect, _ensure_schema


MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"
OUTPUTS_ROOT = MODEL_ROOT / "outputs"
WALKFORWARD_PATH = OUTPUTS_ROOT / "walkforward_multiseason_predictions.csv"
GAME_PROJECTIONS_PATH = OUTPUTS_ROOT / "current_game_projections.csv"
RESEARCH_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "research_outputs"

EPS = 1e-9
PERCENTILES = [10, 25, 50, 75, 90]


@dataclass(frozen=True)
class MarginConvention:
    label: str
    margin_sign: int
    correlation_to_actual_home_margin: float


def _is_half_point(value: float) -> bool:
    return abs(float(value) - round(float(value))) > 1e-9


def _season_week_key(season: Any, week: Any) -> int:
    return int(season) * 100 + int(week)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
        if not math.isfinite(out):
            return None
        return out
    except (TypeError, ValueError):
        return None


def infer_margin_sign_convention(frame: pd.DataFrame) -> MarginConvention:
    actual = pd.to_numeric(frame["home_score"], errors="coerce") - pd.to_numeric(frame["away_score"], errors="coerce")
    model = pd.to_numeric(frame["model_margin"], errors="coerce")
    work = pd.DataFrame({"actual": actual, "model": model}).dropna()
    if work.empty:
        return MarginConvention("UNKNOWN", 1, float("nan"))

    corr_home = float(work["model"].corr(work["actual"]))
    corr_away = float((-work["model"]).corr(work["actual"]))

    if abs(corr_home) >= abs(corr_away):
        return MarginConvention(
            label="POSITIVE_MODEL_MARGIN_MEANS_HOME_FAVORED",
            margin_sign=1,
            correlation_to_actual_home_margin=corr_home,
        )

    return MarginConvention(
        label="POSITIVE_MODEL_MARGIN_MEANS_AWAY_FAVORED",
        margin_sign=-1,
        correlation_to_actual_home_margin=-corr_away,
    )


def derive_implied_team_scores(projected_game_total: float, projected_home_margin: float, margin_sign: int) -> tuple[float, float]:
    total = _safe_float(projected_game_total)
    margin = _safe_float(projected_home_margin)
    if total is None or margin is None:
        raise ValueError("non-finite projected total/margin")

    adjusted_margin = float(margin_sign) * margin
    home_expected = (total + adjusted_margin) / 2.0
    away_expected = (total - adjusted_margin) / 2.0

    if not math.isfinite(home_expected) or not math.isfinite(away_expected):
        raise ValueError("non-finite implied team projections")

    return float(home_expected), float(away_expected)


def build_team_total_research_dataset(frame: pd.DataFrame, convention: MarginConvention) -> tuple[pd.DataFrame, dict[str, int]]:
    required = [
        "season",
        "week",
        "game_id",
        "home_team",
        "away_team",
        "model_total",
        "model_margin",
        "home_score",
        "away_score",
    ]

    exclusions = {
        "missing_required_field": 0,
        "non_finite_projection": 0,
    }

    rows: list[dict[str, Any]] = []
    for _, raw in frame.iterrows():
        missing = [k for k in required if k not in raw or pd.isna(raw[k])]
        if missing:
            exclusions["missing_required_field"] += 1
            continue

        projected_total = _safe_float(raw["model_total"])
        projected_margin = _safe_float(raw["model_margin"])
        actual_home = _safe_float(raw["home_score"])
        actual_away = _safe_float(raw["away_score"])
        if projected_total is None or projected_margin is None or actual_home is None or actual_away is None:
            exclusions["non_finite_projection"] += 1
            continue

        try:
            projected_home, projected_away = derive_implied_team_scores(projected_total, projected_margin, convention.margin_sign)
        except ValueError:
            exclusions["non_finite_projection"] += 1
            continue

        row = {
            "season": int(raw["season"]),
            "week": int(raw["week"]),
            "eventId": str(raw["game_id"]),
            "homeTeam": str(raw["home_team"]),
            "awayTeam": str(raw["away_team"]),
            "projectedGameTotal": projected_total,
            "projectedHomeMargin": float(convention.margin_sign) * projected_margin,
            "projectedHomePoints": projected_home,
            "projectedAwayPoints": projected_away,
            "actualHomePoints": actual_home,
            "actualAwayPoints": actual_away,
            "homeResidual": actual_home - projected_home,
            "awayResidual": actual_away - projected_away,
        }

        spread_line = _safe_float(raw.get("spread_line"))
        total_line = _safe_float(raw.get("total_line"))
        if spread_line is not None:
            row["marketHomeMarginFromSpread"] = spread_line
            row["isHomeFavorite"] = spread_line > 0
        else:
            row["marketHomeMarginFromSpread"] = None
            row["isHomeFavorite"] = None
        row["marketGameTotalLine"] = total_line

        rows.append(row)

    dataset = pd.DataFrame(rows)
    if dataset.empty:
        return dataset, exclusions

    dataset = dataset.sort_values(by=["season", "week", "eventId"]).reset_index(drop=True)
    dataset["projectedTeamScoreBucket"] = pd.cut(
        pd.concat([dataset["projectedHomePoints"], dataset["projectedAwayPoints"]], ignore_index=True),
        bins=[-1e9, 17, 21, 24, 28, 1e9],
        labels=["<=17", "17-21", "21-24", "24-28", "28+"],
    )
    return dataset, exclusions


def _metrics(errors: pd.Series) -> dict[str, Any]:
    abs_err = errors.abs()
    out = {
        "bias": float(errors.mean()),
        "mae": float(abs_err.mean()),
        "rmse": float(np.sqrt(np.mean(np.square(errors)))),
        "medae": float(abs_err.median()),
        "residualStd": float(errors.std(ddof=0)),
    }
    for p in PERCENTILES:
        out[f"P{p}"] = float(np.percentile(abs_err, p))
    return out


def compute_prediction_diagnostics(dataset: pd.DataFrame) -> dict[str, Any]:
    home_err = dataset["homeResidual"]
    away_err = dataset["awayResidual"]
    combined = pd.concat([home_err, away_err], ignore_index=True)

    diag = {
        "sampleSizeGames": int(len(dataset)),
        "sampleSizeTeamObservations": int(len(combined)),
        "home": _metrics(home_err),
        "away": _metrics(away_err),
        "combined": _metrics(combined),
    }

    fav_residuals = []
    dog_residuals = []
    for _, r in dataset.iterrows():
        if r["isHomeFavorite"] is True:
            fav_residuals.append(float(r["homeResidual"]))
            dog_residuals.append(float(r["awayResidual"]))
        elif r["isHomeFavorite"] is False:
            fav_residuals.append(float(r["awayResidual"]))
            dog_residuals.append(float(r["homeResidual"]))

    diag["favoriteVsUnderdog"] = {
        "favorite": _metrics(pd.Series(fav_residuals)) if fav_residuals else None,
        "underdog": _metrics(pd.Series(dog_residuals)) if dog_residuals else None,
    }

    buckets = [
        ("projectedTeamScoreBucket", ["<=17", "17-21", "21-24", "24-28", "28+"]),
        ("projectedTotalBucket", ["<=40", "40-45", "45-50", "50+"]),
    ]

    dataset = dataset.copy()
    dataset["projectedTotalBucket"] = pd.cut(
        dataset["projectedGameTotal"],
        bins=[-1e9, 40, 45, 50, 1e9],
        labels=["<=40", "40-45", "45-50", "50+"],
    )

    diag["bucketDiagnostics"] = {}
    for col, labels in buckets:
        col_out: dict[str, Any] = {}
        for label in labels:
            if col == "projectedTeamScoreBucket":
                # Build team-level rows for this bucket.
                home_rows = dataset[dataset["projectedHomePoints"].between(-1e9, 1e9)].copy()
                away_rows = dataset[dataset["projectedAwayPoints"].between(-1e9, 1e9)].copy()
                team_df = pd.DataFrame(
                    {
                        "bucket": list(pd.cut(home_rows["projectedHomePoints"], [-1e9, 17, 21, 24, 28, 1e9], labels=labels))
                        + list(pd.cut(away_rows["projectedAwayPoints"], [-1e9, 17, 21, 24, 28, 1e9], labels=labels)),
                        "residual": list(home_rows["homeResidual"]) + list(away_rows["awayResidual"]),
                    }
                )
                subset = team_df[team_df["bucket"].astype(str) == str(label)]
                if len(subset):
                    col_out[str(label)] = _metrics(subset["residual"])
            else:
                subset = dataset[dataset[col].astype(str) == str(label)]
                if len(subset):
                    combined_subset = pd.concat([subset["homeResidual"], subset["awayResidual"]], ignore_index=True)
                    col_out[str(label)] = _metrics(combined_subset)
        diag["bucketDiagnostics"][col] = col_out

    return diag


def _team_level_rows(dataset: pd.DataFrame) -> pd.DataFrame:
    home = pd.DataFrame(
        {
            "season": dataset["season"],
            "week": dataset["week"],
            "eventId": dataset["eventId"],
            "team": dataset["homeTeam"],
            "projected": dataset["projectedHomePoints"],
            "actual": dataset["actualHomePoints"],
            "residual": dataset["homeResidual"],
            "marketLine": (dataset["marketGameTotalLine"] + dataset["marketHomeMarginFromSpread"]) / 2.0,
        }
    )
    away = pd.DataFrame(
        {
            "season": dataset["season"],
            "week": dataset["week"],
            "eventId": dataset["eventId"],
            "team": dataset["awayTeam"],
            "projected": dataset["projectedAwayPoints"],
            "actual": dataset["actualAwayPoints"],
            "residual": dataset["awayResidual"],
            "marketLine": (dataset["marketGameTotalLine"] - dataset["marketHomeMarginFromSpread"]) / 2.0,
        }
    )
    out = pd.concat([home, away], ignore_index=True)
    out["orderKey"] = out.apply(lambda r: (_season_week_key(r["season"], r["week"]), str(r["eventId"]), str(r["team"])), axis=1)
    out = out.sort_values(by=["season", "week", "eventId", "team"]).reset_index(drop=True)
    return out


def compute_baseline_comparison(dataset: pd.DataFrame) -> dict[str, Any]:
    team_df = _team_level_rows(dataset)

    # A) leakage-safe league-average baseline: prior expanding mean of team points.
    prior_mean = team_df["actual"].expanding().mean().shift(1)
    league_mask = prior_mean.notna()
    league_mae = float(np.mean(np.abs(team_df.loc[league_mask, "actual"] - prior_mean[league_mask]))) if league_mask.any() else None

    # B) market-implied team-score baseline from pregame spread+total if present.
    market_mask = team_df["marketLine"].notna()
    market_mae = float(np.mean(np.abs(team_df.loc[market_mask, "actual"] - team_df.loc[market_mask, "marketLine"]))) if market_mask.any() else None

    # C) leakage-safe per-team naive baseline.
    naive_values = []
    history: dict[str, list[float]] = {}
    for _, r in team_df.iterrows():
        team = str(r["team"])
        prev = history.get(team, [])
        naive_values.append(float(np.mean(prev)) if prev else np.nan)
        history.setdefault(team, []).append(float(r["actual"]))
    naive_series = pd.Series(naive_values)
    naive_mask = naive_series.notna()
    naive_mae = float(np.mean(np.abs(team_df.loc[naive_mask, "actual"] - naive_series[naive_mask]))) if naive_mask.any() else None

    sia_mae = float(np.mean(np.abs(team_df["actual"] - team_df["projected"]))) if len(team_df) else None

    def _improve(base: Optional[float]) -> Optional[float]:
        if base is None or sia_mae is None or base <= 0:
            return None
        return float((base - sia_mae) / base)

    return {
        "siaMae": sia_mae,
        "leagueBaselineMae": league_mae,
        "marketImpliedMae": market_mae,
        "naiveTeamPriorMae": naive_mae,
        "siaVsLeagueImprovement": _improve(league_mae),
        "siaVsMarketImpliedImprovement": _improve(market_mae),
        "siaVsNaiveTeamPriorImprovement": _improve(naive_mae),
        "marketBaselineAvailable": bool(market_mask.any()),
    }


def fit_residual_methods(dataset: pd.DataFrame) -> dict[str, Any]:
    residuals = pd.concat([dataset["homeResidual"], dataset["awayResidual"]], ignore_index=True).dropna().to_numpy(dtype=float)
    if len(residuals) < 100:
        return {
            "selected": "UNAVAILABLE",
            "methods": {},
            "residualCount": int(len(residuals)),
        }

    probs = np.array([0.1, 0.25, 0.5, 0.75, 0.9], dtype=float)
    empirical_q = np.quantile(residuals, probs)

    mu = float(np.mean(residuals))
    sigma = float(np.std(residuals, ddof=0))
    rng = np.random.default_rng(2026)
    gauss_draw = rng.normal(loc=mu, scale=max(sigma, 1e-6), size=200000)

    excess_kurt = float(pd.Series(residuals).kurt())
    if not math.isfinite(excess_kurt):
        excess_kurt = 0.0
    if excess_kurt > 0:
        nu = max(4.5, min(60.0, 6.0 / max(excess_kurt, 1e-6) + 4.0))
    else:
        nu = 60.0
    scale = max(sigma * math.sqrt(max((nu - 2.0) / nu, 1e-6)), 1e-6)
    t_draw = mu + scale * rng.standard_t(df=nu, size=200000)

    def _fit_score(draws: np.ndarray) -> float:
        q = np.quantile(draws, probs)
        return float(np.mean(np.abs(q - empirical_q)))

    scores = {
        "EMPIRICAL": 0.0,
        "GAUSSIAN": _fit_score(gauss_draw),
        "STUDENT_T": _fit_score(t_draw),
    }

    selected = "EMPIRICAL"
    if scores["GAUSSIAN"] + 0.05 < scores["EMPIRICAL"]:
        selected = "GAUSSIAN"
    if scores["STUDENT_T"] + 0.05 < scores[selected]:
        selected = "STUDENT_T"

    return {
        "selected": selected,
        "methods": {
            "EMPIRICAL": {"fitScore": scores["EMPIRICAL"]},
            "GAUSSIAN": {"fitScore": scores["GAUSSIAN"], "mu": mu, "sigma": sigma},
            "STUDENT_T": {"fitScore": scores["STUDENT_T"], "mu": mu, "scale": scale, "nu": nu},
        },
        "residualCount": int(len(residuals)),
    }


def team_total_probability(projected_team_points: float, line: float, method_pack: dict[str, Any], residuals: np.ndarray) -> dict[str, float]:
    proj = _safe_float(projected_team_points)
    total_line = _safe_float(line)
    if proj is None or total_line is None:
        raise ValueError("non-finite projected points or line")

    method = str(method_pack.get("selected") or "EMPIRICAL")
    rng = np.random.default_rng(2026)

    if method == "GAUSSIAN":
        m = method_pack.get("methods", {}).get("GAUSSIAN", {})
        mu = float(m.get("mu", 0.0))
        sigma = max(float(m.get("sigma", 7.0)), 1e-6)
        sims = np.rint(proj + rng.normal(loc=mu, scale=sigma, size=120000))
    elif method == "STUDENT_T":
        m = method_pack.get("methods", {}).get("STUDENT_T", {})
        mu = float(m.get("mu", 0.0))
        nu = max(float(m.get("nu", 8.0)), 2.1)
        scale = max(float(m.get("scale", 7.0)), 1e-6)
        sims = np.rint(proj + mu + scale * rng.standard_t(df=nu, size=120000))
    else:
        sims = np.rint(proj + residuals)

    over = float(np.mean(sims > total_line))
    push = float(np.mean(sims == total_line))
    under = float(np.mean(sims < total_line))

    s = over + push + under
    if s <= 0:
        return {"over": 0.0, "push": 0.0, "under": 0.0}
    return {"over": over / s, "push": push / s, "under": under / s}


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.square(p - y)))


def _log_loss(y: np.ndarray, p: np.ndarray) -> float:
    q = np.clip(p, 1e-6, 1.0 - 1e-6)
    return float(-np.mean(y * np.log(q) + (1.0 - y) * np.log(1.0 - q)))


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    bucket = np.clip(np.digitize(p, edges, right=True) - 1, 0, bins - 1)
    val = 0.0
    for b in range(bins):
        m = bucket == b
        if not np.any(m):
            continue
        val += float(np.mean(m)) * abs(float(np.mean(y[m])) - float(np.mean(p[m])))
    return float(val)


def walk_forward_validation(dataset: pd.DataFrame, method_pack: dict[str, Any]) -> dict[str, Any]:
    # Team-total sportsbook lines are not present in canonical walkforward artifact today.
    # Keep behavior explicit instead of fabricating labels.
    home_line_exists = "home_team_total_line" in dataset.columns
    away_line_exists = "away_team_total_line" in dataset.columns
    if not (home_line_exists or away_line_exists):
        return {
            "status": "INSUFFICIENT_DATA",
            "trainSample": 0,
            "validationSample": 0,
            "oosSample": 0,
            "brier": None,
            "logLoss": None,
            "ece": None,
        }

    # Placeholder for future sprint when historical team-total lines are available leakage-safe.
    return {
        "status": "INSUFFICIENT_DATA",
        "trainSample": 0,
        "validationSample": 0,
        "oosSample": 0,
        "brier": None,
        "logLoss": None,
        "ece": None,
    }


def live_team_total_mapping_check(dataset: pd.DataFrame, method_pack: dict[str, Any]) -> dict[str, Any]:
    _ensure_schema()
    con = _connect()
    rows = con.execute(
        """
        SELECT event_id, team_code, side, line, price, bookmaker, market_timestamp
        FROM shadow_market_snapshots
        WHERE market_family = 'TEAM_TOTAL'
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()
    con.close()

    residuals = pd.concat([dataset["homeResidual"], dataset["awayResidual"]], ignore_index=True).dropna().to_numpy(float)

    mapped = 0
    for r in rows:
        team_code = str(r["team_code"] or "").strip()
        side = str(r["side"] or "").strip().lower()
        line = _safe_float(r["line"])
        price = _safe_float(r["price"])
        if not team_code or side not in {"over", "under"} or line is None or price is None:
            continue

        # Structural compatibility check: if we can compute probabilities and fair price from projected points,
        # this row shape is compatible with future model-backed mapping.
        projected_team_points = float(np.mean(dataset["projectedHomePoints"]))
        probs = team_total_probability(projected_team_points, line, method_pack, residuals)
        win_prob = probs["over"] if side == "over" else probs["under"]
        fair_odds = fair_price_from_win_push(win_prob, probs["push"])
        prob_sum = probs["over"] + probs["push"] + probs["under"]
        if abs(prob_sum - 1.0) > 1e-6:
            continue
        _ = fair_odds  # fair price is part of mapping payload when numerically defined.
        mapped += 1

    return {
        "rowsChecked": int(len(rows)),
        "rowsMappingCompatible": int(mapped),
        "status": "PASS" if mapped > 0 else "FAIL",
    }


def run_phase1_research() -> dict[str, Any]:
    if not WALKFORWARD_PATH.exists():
        raise FileNotFoundError(f"walkforward file missing: {WALKFORWARD_PATH}")

    raw = pd.read_csv(WALKFORWARD_PATH)
    convention = infer_margin_sign_convention(raw)
    dataset, exclusions = build_team_total_research_dataset(raw, convention)
    if dataset.empty:
        raise ValueError("team total research dataset is empty after filtering")

    diagnostics = compute_prediction_diagnostics(dataset)
    baselines = compute_baseline_comparison(dataset)
    residual_methods = fit_residual_methods(dataset)
    walk = walk_forward_validation(dataset, residual_methods)

    residuals = pd.concat([dataset["homeResidual"], dataset["awayResidual"]], ignore_index=True).dropna().to_numpy(float)
    integer_line_probs = team_total_probability(float(np.mean(dataset["projectedHomePoints"])), 24.0, residual_methods, residuals)
    half_line_probs = team_total_probability(float(np.mean(dataset["projectedHomePoints"])), 24.5, residual_methods, residuals)

    market_lines_available = bool("home_team_total_line" in raw.columns or "away_team_total_line" in raw.columns)
    market_prices_available = bool("home_team_total_price" in raw.columns or "away_team_total_price" in raw.columns)

    research_state = "RESEARCH_ONLY"
    model_validated = False

    live_mapping = live_team_total_mapping_check(dataset, residual_methods)

    out = {
        "dataset": {
            "sampleSize": int(len(dataset)),
            "period": f"{int(dataset['season'].min())}-W{int(dataset['week'].min())} to {int(dataset['season'].max())}-W{int(dataset['week'].max())}",
            "exclusions": exclusions,
            "marginSignConvention": convention.label,
            "marginCorrelation": convention.correlation_to_actual_home_margin,
        },
        "diagnostics": diagnostics,
        "baselines": baselines,
        "residualMethods": residual_methods,
        "probabilityChecks": {
            "integerLine": integer_line_probs,
            "halfPointLine": half_line_probs,
            "integerPushModel": "EXPLICIT_DISCRETE_PUSH",
            "halfPointPushBehavior": "ZERO_PUSH_EXPECTED",
        },
        "walkForward": walk,
        "marketValidation": {
            "historicalTeamTotalLines": "AVAILABLE" if market_lines_available else "UNAVAILABLE",
            "historicalTeamTotalPrices": "AVAILABLE" if market_prices_available else "UNAVAILABLE",
            "marketEdgeValidation": "AVAILABLE" if market_lines_available and market_prices_available else "UNAVAILABLE",
        },
        "modelState": {
            "state": research_state,
            "validated": model_validated,
            "shadowRecommendationsEnabled": False,
            "productionEligible": False,
        },
        "liveMapping": live_mapping,
        "invariants": {
            "teamTotalShadowEligible": bool(PHASE2B_MARKET_FAMILIES["TEAM_TOTAL"]["shadowEligible"]),
            "teamTotalProductionEligible": bool(PHASE2B_MARKET_FAMILIES["TEAM_TOTAL"]["productionEligible"]),
            "teamTotalCrossMarketComparable": False,
            "universalSia3": "DISABLED",
        },
    }

    RESEARCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = RESEARCH_OUTPUT_DIR / "team_total_phase1_validation_report.json"
    out_md = RESEARCH_OUTPUT_DIR / "TEAM_TOTAL_PHASE1_VALIDATION.md"
    out_json.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# SIA Team Total Historical Validation Phase 1",
        "",
        f"Dataset period: {out['dataset']['period']}",
        f"Sample size: {out['dataset']['sampleSize']} games",
        f"Margin sign convention: {out['dataset']['marginSignConvention']}",
        "",
        "## Accuracy",
        f"- Home MAE: {out['diagnostics']['home']['mae']:.4f}",
        f"- Away MAE: {out['diagnostics']['away']['mae']:.4f}",
        f"- Combined MAE: {out['diagnostics']['combined']['mae']:.4f}",
        f"- Combined RMSE: {out['diagnostics']['combined']['rmse']:.4f}",
        "",
        "## Baselines",
        f"- SIA vs league MAE improvement: {out['baselines']['siaVsLeagueImprovement']}",
        f"- SIA vs market-implied MAE improvement: {out['baselines']['siaVsMarketImpliedImprovement']}",
        "",
        "## Residual Method",
        f"- Selected: {out['residualMethods']['selected']}",
        "",
        "## Walk-Forward",
        f"- Status: {out['walkForward']['status']}",
        "",
        "## Market Validation Availability",
        f"- Historical team total lines: {out['marketValidation']['historicalTeamTotalLines']}",
        f"- Historical team total prices: {out['marketValidation']['historicalTeamTotalPrices']}",
        f"- Market edge validation: {out['marketValidation']['marketEdgeValidation']}",
        "",
        "## Recommendation",
        "Keep TEAM_TOTAL as RESEARCH_ONLY and continue collecting live team-total market history before any shadow recommendation enablement.",
    ]
    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> None:
    out = run_phase1_research()
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
