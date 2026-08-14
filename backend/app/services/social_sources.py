from __future__ import annotations

from typing import Any, Dict, List, Optional


SOURCE_TYPE_TEAM_OFFICIAL = "TEAM_OFFICIAL"
SOURCE_TYPE_TEAM_BEAT = "TEAM_BEAT"
SOURCE_TYPE_NATIONAL_REPORTER = "NATIONAL_REPORTER"
SOURCE_TYPE_OTHER_VERIFIED = "OTHER_VERIFIED"


NFL_TEAMS: List[Dict[str, str]] = [
    {"team": "ARI", "name": "Arizona Cardinals"},
    {"team": "ATL", "name": "Atlanta Falcons"},
    {"team": "BAL", "name": "Baltimore Ravens"},
    {"team": "BUF", "name": "Buffalo Bills"},
    {"team": "CAR", "name": "Carolina Panthers"},
    {"team": "CHI", "name": "Chicago Bears"},
    {"team": "CIN", "name": "Cincinnati Bengals"},
    {"team": "CLE", "name": "Cleveland Browns"},
    {"team": "DAL", "name": "Dallas Cowboys"},
    {"team": "DEN", "name": "Denver Broncos"},
    {"team": "DET", "name": "Detroit Lions"},
    {"team": "GB", "name": "Green Bay Packers"},
    {"team": "HOU", "name": "Houston Texans"},
    {"team": "IND", "name": "Indianapolis Colts"},
    {"team": "JAX", "name": "Jacksonville Jaguars"},
    {"team": "KC", "name": "Kansas City Chiefs"},
    {"team": "LAC", "name": "Los Angeles Chargers"},
    {"team": "LAR", "name": "Los Angeles Rams"},
    {"team": "LV", "name": "Las Vegas Raiders"},
    {"team": "MIA", "name": "Miami Dolphins"},
    {"team": "MIN", "name": "Minnesota Vikings"},
    {"team": "NE", "name": "New England Patriots"},
    {"team": "NO", "name": "New Orleans Saints"},
    {"team": "NYG", "name": "New York Giants"},
    {"team": "NYJ", "name": "New York Jets"},
    {"team": "PHI", "name": "Philadelphia Eagles"},
    {"team": "PIT", "name": "Pittsburgh Steelers"},
    {"team": "SEA", "name": "Seattle Seahawks"},
    {"team": "SF", "name": "San Francisco 49ers"},
    {"team": "TB", "name": "Tampa Bay Buccaneers"},
    {"team": "TEN", "name": "Tennessee Titans"},
    {"team": "WAS", "name": "Washington Commanders"},
]


def _mock_source(
    team: str,
    source_name: str,
    handle: str,
    source_type: str,
    credibility_score: int,
    priority: int,
) -> Dict[str, Any]:
    return {
        "team": team,
        "name": source_name,
        "handle": handle,
        "sourceType": source_type,
        "credibilityScore": credibility_score,
        "priority": priority,
        "active": True,
    }


def _build_default_sources() -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []

    for entry in NFL_TEAMS:
        team = entry["team"]
        team_name = entry["name"]
        handle_base = team.lower()

        sources.extend(
            [
                _mock_source(
                    team=team,
                    source_name=f"Mock {team_name} Official Feed",
                    handle=f"mock_{handle_base}_official",
                    source_type=SOURCE_TYPE_TEAM_OFFICIAL,
                    credibility_score=95,
                    priority=1,
                ),
                _mock_source(
                    team=team,
                    source_name=f"Mock {team_name} Beat Reporter",
                    handle=f"mock_{handle_base}_beat",
                    source_type=SOURCE_TYPE_TEAM_BEAT,
                    credibility_score=78,
                    priority=2,
                ),
                _mock_source(
                    team=team,
                    source_name=f"Mock National Reporter on {team_name}",
                    handle=f"mock_national_{handle_base}",
                    source_type=SOURCE_TYPE_NATIONAL_REPORTER,
                    credibility_score=84,
                    priority=3,
                ),
                _mock_source(
                    team=team,
                    source_name=f"Mock Verified Analyst for {team_name}",
                    handle=f"mock_verified_{handle_base}",
                    source_type=SOURCE_TYPE_OTHER_VERIFIED,
                    credibility_score=68,
                    priority=4,
                ),
            ]
        )

    return sources


SOCIAL_SOURCES = _build_default_sources()


def get_social_sources(team: Optional[str] = None, active_only: bool = True) -> List[Dict[str, Any]]:
    normalized_team = str(team or "").strip().upper()
    sources = SOCIAL_SOURCES

    if normalized_team:
        sources = [source for source in sources if source["team"] == normalized_team]

    if active_only:
        sources = [source for source in sources if source.get("active", False)]

    return list(sources)


def get_sources_by_handle() -> Dict[str, Dict[str, Any]]:
    return {
        str(source["handle"]): source
        for source in SOCIAL_SOURCES
    }


def get_social_source_summary() -> Dict[str, Any]:
    active_sources = [source for source in SOCIAL_SOURCES if source.get("active", False)]
    return {
        "teamsCovered": len({source["team"] for source in SOCIAL_SOURCES}),
        "sourcesConfigured": len(SOCIAL_SOURCES),
        "sourcesActive": len(active_sources),
        "sourceTypes": sorted({source["sourceType"] for source in SOCIAL_SOURCES}),
        "provider": "MOCK",
        "isLive": False,
    }