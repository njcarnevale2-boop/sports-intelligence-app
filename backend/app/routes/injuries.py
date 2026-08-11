from pathlib import Path
import json

from fastapi import APIRouter, Query

from app.services.injuries import InjuryAnalyzer

router = APIRouter(
    prefix="/api/injuries",
    tags=["injuries"],
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
INJURY_FILE = DATA_DIR / "injuries.json"


def load_injuries():
    """
    Load normalized injury data if a live provider
    or ingestion process has created injuries.json.

    We intentionally return an empty list when no
    provider is configured rather than creating
    fake injury information.
    """

    if not INJURY_FILE.exists():
        return []

    try:
        with open(INJURY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        injuries = data.get("injuries", [])

        if isinstance(injuries, list):
            return injuries

    return []


@router.get("")
def get_injuries(
    team: str | None = Query(
        default=None,
        description="Optional NFL team abbreviation, e.g. BUF",
    ),
    event_id: str | None = Query(
        default=None,
        description="Optional sportsbook/API event ID",
    ),
):
    """
    Return injury intelligence for the current game context.

    When no provider-backed injury file exists, the endpoint falls back to the
    mock injury analyzer so the UI and downstream services can still consume
    a realistic payload immediately.
    """

    injuries = load_injuries()

    if not injuries:
        injury_analysis = InjuryAnalyzer().analyze()

        return {
            "status": "mock",
            "count": 5,
            "source": "mock",
            "injuryAnalysis": injury_analysis,
        }

    filtered = injuries

    if team:
        normalized_team = team.upper().strip()

        filtered = [
            injury
            for injury in filtered
            if str(
                injury.get("team", "")
            ).upper()
            == normalized_team
        ]

    if event_id:
        filtered = [
            injury
            for injury in filtered
            if str(
                injury.get("eventId", "")
            )
            == event_id
        ]

    return {
        "status": (
            "live"
            if injuries
            else "provider_not_configured"
        ),
        "count": len(filtered),
        "source": (
            str(INJURY_FILE)
            if INJURY_FILE.exists()
            else None
        ),
        "injuries": filtered,
    }


@router.get("/health")
def injury_health():
    injuries = load_injuries()

    return {
        "status": "ok",
        "providerConfigured": bool(injuries),
        "injuryCount": len(injuries),
        "dataFile": str(INJURY_FILE),
    }