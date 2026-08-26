from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from app.config import settings
from app.services.shadow_markets import (
    append_shadow_outcomes,
    build_shadow_boards,
    canonical_quote_contract,
    capture_prospective_from_line_board,
    correlation_metadata_design,
    discover_expanded_markets,
    discover_player_props,
    expanded_market_collection_status,
    ingest_expanded_market_snapshots,
    ingest_player_prop_market_snapshots,
    live_sia_future_schema_compatibility,
    player_identity_mapping_plan,
    prospective_data_integrity_audit,
    prospective_market_capture_report,
    publish_shadow_snapshot,
    line_shopping_market_view,
    player_prop_coverage_report,
    player_prop_grading_source_audit,
    player_prop_market_contract,
    player_prop_model_interface_contract,
    shadow_performance_report,
    shadow_promotion_gates,
    sportsbook_coverage_audit,
    universal_candidate_contract_design,
)
from app.services.pregame_collection_manager import (
    build_pregame_collection_plan,
    pregame_collection_status_report,
    run_pregame_collection_manager,
)


router = APIRouter(prefix="/api/admin/shadow", tags=["admin-shadow"])


def _require_admin_token(x_admin_token: str | None) -> None:
    if not x_admin_token or x_admin_token != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Admin token required")


class BuildRequest(BaseModel):
    season: Optional[int] = None
    week: Optional[int] = None


class PublishRequest(BaseModel):
    season: Optional[int] = None
    week: Optional[int] = None
    runId: Optional[str] = None
    publicationType: str = "SHADOW_MULTI_MARKET"
    isOfficial: bool = True
    officialCadence: Optional[str] = None


class SettlementRequest(BaseModel):
    # Optional manual score injection map for testing/ops.
    scoreByEventId: Optional[dict[str, dict[str, int]]] = None


class SnapshotIngestionRequest(BaseModel):
    runDiscovery: bool = True


class ProspectiveCaptureRequest(BaseModel):
    season: Optional[int] = None
    week: Optional[int] = None
    includeExpanded: bool = True


class LineShoppingMarketViewRequest(BaseModel):
    eventId: str
    marketFamily: str
    side: str
    period: Optional[str] = None
    phase: str = "PREGAME"
    teamCode: Optional[str] = None
    selection: Optional[str] = None
    playableToLine: Optional[float] = None
    playableToPrice: Optional[float] = None


class PlayerPropIngestionRequest(BaseModel):
    runDiscovery: bool = True


class PregameCollectionRunRequest(BaseModel):
    week: Optional[int] = None
    dryRun: bool = True
    maxRequestsPerRun: Optional[int] = None
    maxEstimatedCreditsPerRun: Optional[float] = None
    dailyEstimatedCreditBudget: Optional[float] = None
    estimatedCreditsPerRequest: Optional[float] = None
    deterministicCreditRuleVerified: bool = False
    allowUnknownCreditCost: bool = False
    propAllowlist: Optional[list[str]] = None


@router.post("/boards/build")
def build_shadow(request: BuildRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    try:
        return build_shadow_boards(week=request.week, season=request.season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/publish")
def publish_shadow(request: PublishRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    try:
        return publish_shadow_snapshot(
            season=request.season,
            week=request.week,
            run_id=request.runId,
            publication_type=request.publicationType,
            is_official=request.isOfficial,
            official_cadence=request.officialCadence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/outcomes/append")
def append_outcomes(request: SettlementRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)

    lookup = request.scoreByEventId or {}

    def _fetch(event_id: str) -> Optional[dict[str, Any]]:
        entry = lookup.get(str(event_id))
        if not entry:
            return None
        away = entry.get("finalAwayScore")
        home = entry.get("finalHomeScore")
        if away is None or home is None:
            return None
        return {"finalAwayScore": int(away), "finalHomeScore": int(home)}

    return append_shadow_outcomes(fetch_scores_fn=_fetch if lookup else None)


@router.get("/performance")
def performance_report(x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return shadow_performance_report()


@router.get("/promotion-gates")
def promotion_gates(x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return shadow_promotion_gates()


@router.get("/discovery/expanded-markets")
def expanded_market_discovery(x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return discover_expanded_markets()


@router.post("/discovery/expanded-markets/ingest")
def expanded_market_ingest(request: SnapshotIngestionRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    discovery = discover_expanded_markets() if request.runDiscovery else None
    result = ingest_expanded_market_snapshots(discovery=discovery)
    return {
        "ingested": result,
        "discovery": discovery,
        "collectionStatus": expanded_market_collection_status(),
        "capturedAtUTC": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/discovery/expanded-markets/status")
def expanded_market_status(x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return expanded_market_collection_status()


@router.post("/capture/prospective")
def capture_prospective(request: ProspectiveCaptureRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    core = capture_prospective_from_line_board(week=request.week, season=request.season)
    expanded = ingest_expanded_market_snapshots(discovery=discover_expanded_markets()) if request.includeExpanded else None
    return {
        "core": core,
        "expanded": expanded,
        "capturedAtUTC": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/capture/prospective/report")
def prospective_report(
    season: Optional[int] = Query(default=None),
    week: Optional[int] = Query(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_admin_token)
    return prospective_market_capture_report(season=season, week=week)


@router.get("/capture/prospective/integrity")
def prospective_integrity(
    season: Optional[int] = Query(default=None),
    week: Optional[int] = Query(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_admin_token)
    return prospective_data_integrity_audit(season=season, week=week)


@router.get("/capture/prospective/live-compatibility")
def prospective_live_compatibility(x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return live_sia_future_schema_compatibility()


@router.get("/line-shopping/coverage-audit")
def line_shopping_coverage_audit(
    max_events: int = Query(default=6, ge=1, le=16),
    x_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_admin_token)
    return sportsbook_coverage_audit(max_events=max_events)


@router.get("/line-shopping/contract")
def line_shopping_contract(x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return canonical_quote_contract()


@router.post("/line-shopping/market-view")
def line_shopping_market(request: LineShoppingMarketViewRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return line_shopping_market_view(
        event_id=request.eventId,
        market_family=request.marketFamily,
        side=request.side,
        period=request.period,
        phase=request.phase,
        team_code=request.teamCode,
        selection=request.selection,
        playable_to_line=request.playableToLine,
        playable_to_price=request.playableToPrice,
    )


@router.get("/discovery/player-props")
def player_prop_discovery(x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    discovery = discover_player_props()
    mapping = player_identity_mapping_plan(discovery.get("sampledPlayers") or [])
    return {
        "discovery": discovery,
        "mappingPlan": mapping,
    }


@router.post("/discovery/player-props/ingest")
def player_prop_ingest(request: PlayerPropIngestionRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    discovery = discover_player_props() if request.runDiscovery else None
    ingested = ingest_player_prop_market_snapshots(discovery=discovery)
    return {
        "discovery": discovery,
        "ingested": ingested,
        "coverage": player_prop_coverage_report(),
        "capturedAtUTC": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/discovery/player-props/status")
def player_prop_status(x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return {
        "contract": player_prop_market_contract(),
        "grading": player_prop_grading_source_audit(),
        "coverage": player_prop_coverage_report(),
        "futureModelInterface": player_prop_model_interface_contract(),
        "liveCompatibility": live_sia_future_schema_compatibility(),
    }


@router.get("/design/universal-candidate-contract")
def universal_contract(x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return universal_candidate_contract_design()


@router.get("/design/correlation-metadata")
def correlation_design(x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return correlation_metadata_design()


@router.post("/capture/pregame-manager/plan")
def pregame_collection_plan(request: PregameCollectionRunRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return build_pregame_collection_plan(
        week=request.week,
        dry_run=request.dryRun,
        max_requests_per_run=request.maxRequestsPerRun,
        max_estimated_credits_per_run=request.maxEstimatedCreditsPerRun,
        daily_estimated_credit_budget=request.dailyEstimatedCreditBudget,
        estimated_credits_per_request=request.estimatedCreditsPerRequest,
        deterministic_credit_rule_verified=request.deterministicCreditRuleVerified,
        allow_unknown_credit_cost=request.allowUnknownCreditCost,
        prop_allowlist=request.propAllowlist,
    )


@router.post("/capture/pregame-manager/run")
def pregame_collection_run(request: PregameCollectionRunRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    return run_pregame_collection_manager(
        week=request.week,
        dry_run=request.dryRun,
        max_requests_per_run=request.maxRequestsPerRun,
        max_estimated_credits_per_run=request.maxEstimatedCreditsPerRun,
        daily_estimated_credit_budget=request.dailyEstimatedCreditBudget,
        estimated_credits_per_request=request.estimatedCreditsPerRequest,
        deterministic_credit_rule_verified=request.deterministicCreditRuleVerified,
        allow_unknown_credit_cost=request.allowUnknownCreditCost,
        prop_allowlist=request.propAllowlist,
    )


@router.get("/capture/pregame-manager/status")
def pregame_collection_status(
    week: Optional[int] = Query(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_admin_token)
    return pregame_collection_status_report(week=week)
