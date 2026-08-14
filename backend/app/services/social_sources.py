from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


SOURCE_TYPE_TEAM_OFFICIAL = "TEAM_OFFICIAL"
SOURCE_TYPE_TEAM_BEAT = "TEAM_BEAT"
SOURCE_TYPE_NATIONAL_REPORTER = "NATIONAL_REPORTER"
SOURCE_TYPE_OTHER_VERIFIED = "OTHER_VERIFIED"

SOURCE_TIER_1 = "TIER_1"
SOURCE_TIER_2 = "TIER_2"
SOURCE_TIER_3 = "TIER_3"
SOURCE_TIER_WATCHLIST = "WATCHLIST"


DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
TEAM_SOURCES_FILE = DATA_ROOT / "nfl_social_sources.json"
NATIONAL_SOURCES_FILE = DATA_ROOT / "national_social_sources.json"


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

TEAM_CODES = [entry["team"] for entry in NFL_TEAMS]

SOURCE_TYPE_VALUES = {
    SOURCE_TYPE_TEAM_OFFICIAL,
    SOURCE_TYPE_TEAM_BEAT,
    SOURCE_TYPE_NATIONAL_REPORTER,
    SOURCE_TYPE_OTHER_VERIFIED,
}

SOURCE_TIER_VALUES = {
    SOURCE_TIER_1,
    SOURCE_TIER_2,
    SOURCE_TIER_3,
    SOURCE_TIER_WATCHLIST,
}


def _default_team_entries() -> List[Dict[str, Any]]:
    return [{"team": team_code, "sources": []} for team_code in TEAM_CODES]


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=False)
        file.write("\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_team_coverage(value: Any, fallback_team: Optional[str] = None) -> List[str]:
    if value is None:
        return [fallback_team] if fallback_team else []

    if isinstance(value, str):
        text = value.strip().upper()
        if not text:
            return [fallback_team] if fallback_team else []
        if text == "ALL":
            return ["ALL"]
        return [text]

    output: List[str] = []
    for item in value if isinstance(value, list) else []:
        text = str(item).strip().upper()
        if text:
            output.append(text)

    if not output and fallback_team:
        return [fallback_team]
    return output


def infer_source_tier(credibility_score: Any) -> str:
    try:
        score = int(float(credibility_score))
    except (TypeError, ValueError):
        return SOURCE_TIER_WATCHLIST

    if score >= 90:
        return SOURCE_TIER_1
    if score >= 80:
        return SOURCE_TIER_2
    if score >= 70:
        return SOURCE_TIER_3
    return SOURCE_TIER_WATCHLIST


def _normalize_source(source: Dict[str, Any], fallback_team: Optional[str], default_type: str) -> Dict[str, Any]:
    team = str(source.get("team") or fallback_team or "").strip().upper()
    handle = str(source.get("handle") or "").strip()
    source_type = str(source.get("sourceType") or default_type).strip().upper()
    if source_type not in SOURCE_TYPE_VALUES:
        source_type = default_type

    credibility_score = int(float(source.get("credibilityScore", 0) or 0))
    tier = str(source.get("tier") or infer_source_tier(credibility_score)).strip().upper()
    if tier not in SOURCE_TIER_VALUES:
        tier = infer_source_tier(credibility_score)

    verified = bool(source.get("verified", False))
    verified_at = source.get("verifiedAt") if verified else None

    normalized = {
        "team": team or None,
        "name": str(source.get("name") or "").strip(),
        "handle": handle,
        "sourceType": source_type,
        "publication": str(source.get("publication") or "").strip() or None,
        "profileUrl": str(source.get("profileUrl") or "").strip() or None,
        "teamCoverage": _normalize_team_coverage(source.get("teamCoverage"), fallback_team=team or fallback_team),
        "credibilityScore": credibility_score,
        "tier": tier,
        "priority": int(source.get("priority", 999) or 999),
        "active": bool(source.get("active", False)),
        "verified": verified,
        "verifiedAt": verified_at,
        "notes": str(source.get("notes") or "").strip() or None,
    }
    return normalized


def load_team_source_registry() -> List[Dict[str, Any]]:
    payload = _read_json(TEAM_SOURCES_FILE, _default_team_entries())
    entries = payload if isinstance(payload, list) else payload.get("teams", []) if isinstance(payload, dict) else []

    by_team: Dict[str, Dict[str, Any]] = {entry["team"]: {"team": entry["team"], "sources": []} for entry in _default_team_entries()}
    for entry in entries:
        team = str(entry.get("team") or "").strip().upper()
        if team not in by_team:
            continue
        sources = entry.get("sources", []) if isinstance(entry.get("sources"), list) else []
        by_team[team]["sources"] = [_normalize_source(source, fallback_team=team, default_type=SOURCE_TYPE_TEAM_BEAT) for source in sources]

    return [by_team[team_code] for team_code in TEAM_CODES]


def load_national_sources() -> List[Dict[str, Any]]:
    payload = _read_json(NATIONAL_SOURCES_FILE, {"sources": []})
    sources = payload.get("sources", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    return [_normalize_source(source, fallback_team=None, default_type=SOURCE_TYPE_NATIONAL_REPORTER) for source in sources]


def save_team_source_registry(entries: Sequence[Dict[str, Any]]) -> None:
    normalized = []
    seen_teams = set()
    for entry in entries:
        team = str(entry.get("team") or "").strip().upper()
        if team not in TEAM_CODES or team in seen_teams:
            continue
        seen_teams.add(team)
        sources = entry.get("sources", []) if isinstance(entry.get("sources"), list) else []
        normalized.append({
            "team": team,
            "sources": [_normalize_source(source, fallback_team=team, default_type=SOURCE_TYPE_TEAM_BEAT) for source in sources],
        })

    for team_code in TEAM_CODES:
        if team_code not in seen_teams:
            normalized.append({"team": team_code, "sources": []})

    normalized.sort(key=lambda entry: TEAM_CODES.index(entry["team"]))
    _write_json(TEAM_SOURCES_FILE, normalized)


def save_national_sources(sources: Sequence[Dict[str, Any]]) -> None:
    normalized = [_normalize_source(source, fallback_team=None, default_type=SOURCE_TYPE_NATIONAL_REPORTER) for source in sources]
    _write_json(NATIONAL_SOURCES_FILE, {"sources": normalized})


def _flatten_team_sources(entries: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []
    for entry in entries:
        team = entry["team"]
        for source in entry.get("sources", []):
            flattened.append({**source, "team": team})
    return flattened


def get_social_sources(
    team: Optional[str] = None,
    active_only: bool = True,
    verified_only: bool = False,
    include_watchlist: bool = True,
    include_national: bool = True,
) -> List[Dict[str, Any]]:
    normalized_team = str(team or "").strip().upper()
    team_entries = load_team_source_registry()
    sources = _flatten_team_sources(team_entries)

    if include_national:
        sources.extend(load_national_sources())

    if normalized_team:
        sources = [
            source
            for source in sources
            if normalized_team in source.get("teamCoverage", []) or source.get("team") == normalized_team or "ALL" in source.get("teamCoverage", [])
        ]

    if active_only:
        sources = [source for source in sources if source.get("active", False)]

    if verified_only:
        sources = [source for source in sources if source.get("verified", False)]

    if not include_watchlist:
        sources = [source for source in sources if source.get("tier") != SOURCE_TIER_WATCHLIST]

    return list(sources)


def get_sources_by_handle(
    active_only: bool = False,
    verified_only: bool = False,
    include_watchlist: bool = True,
    include_national: bool = True,
) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for source in get_social_sources(
        active_only=active_only,
        verified_only=verified_only,
        include_watchlist=include_watchlist,
        include_national=include_national,
    ):
        handle = str(source.get("handle") or "")
        if handle:
            lookup[handle] = source
    return lookup


def _find_source_entries(handle: str) -> List[Tuple[str, int]]:
    normalized_handle = str(handle or "").strip()
    matches: List[Tuple[str, int]] = []
    for entry in load_team_source_registry():
        for index, source in enumerate(entry.get("sources", [])):
            if str(source.get("handle") or "") == normalized_handle:
                matches.append((entry["team"], index))

    for index, source in enumerate(load_national_sources()):
        if str(source.get("handle") or "") == normalized_handle:
            matches.append(("NATIONAL", index))
    return matches


def _ensure_unique_handle(handle: str, excluding: Optional[str] = None) -> None:
    normalized_handle = str(handle or "").strip()
    if not normalized_handle:
        raise ValueError("Source handle is required.")

    for existing in get_social_sources(active_only=False, include_national=True):
        existing_handle = str(existing.get("handle") or "").strip()
        if existing_handle and existing_handle == normalized_handle and existing_handle != excluding:
            raise ValueError(f"Duplicate source handle detected: {normalized_handle}")


def add_source(source: Dict[str, Any], team: Optional[str] = None, national: bool = False) -> Dict[str, Any]:
    normalized_team = str(team or source.get("team") or "").strip().upper()
    normalized = _normalize_source(
        {**source, "team": None if national else normalized_team},
        fallback_team=None if national else normalized_team,
        default_type=SOURCE_TYPE_NATIONAL_REPORTER if national else SOURCE_TYPE_TEAM_BEAT,
    )
    _ensure_unique_handle(normalized["handle"])

    if national:
        sources = load_national_sources()
        sources.append(normalized)
        save_national_sources(sources)
        return normalized

    if normalized_team not in TEAM_CODES:
        raise ValueError(f"Unknown NFL team: {normalized_team}")

    entries = load_team_source_registry()
    for entry in entries:
        if entry["team"] == normalized_team:
            entry.setdefault("sources", []).append(normalized)
            break
    save_team_source_registry(entries)
    return normalized


def deactivate_source(handle: str) -> Dict[str, Any]:
    return _update_source(handle, {"active": False})


def update_credibility(handle: str, credibility_score: int) -> Dict[str, Any]:
    score = int(credibility_score)
    return _update_source(handle, {"credibilityScore": score, "tier": infer_source_tier(score)})


def verify_source(handle: str, verified_at: Optional[str] = None) -> Dict[str, Any]:
    return _update_source(handle, {"verified": True, "verifiedAt": verified_at or _now_iso()})


def assign_team(handle: str, team: str) -> Dict[str, Any]:
    normalized_team = str(team or "").strip().upper()
    if normalized_team not in TEAM_CODES:
        raise ValueError(f"Unknown NFL team: {normalized_team}")
    return _move_source(handle, normalized_team)


def assign_source_tier(handle: str, tier: str) -> Dict[str, Any]:
    normalized_tier = str(tier or "").strip().upper()
    if normalized_tier not in SOURCE_TIER_VALUES:
        raise ValueError(f"Unknown source tier: {normalized_tier}")
    return _update_source(handle, {"tier": normalized_tier})


def _update_source(handle: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    normalized_handle = str(handle or "").strip()
    if not normalized_handle:
        raise ValueError("Source handle is required.")

    entries = load_team_source_registry()
    national_sources = load_national_sources()

    for entry in entries:
        for index, source in enumerate(entry.get("sources", [])):
            if str(source.get("handle") or "") == normalized_handle:
                updated = _normalize_source({**source, **updates}, fallback_team=entry["team"], default_type=source.get("sourceType", SOURCE_TYPE_TEAM_BEAT))
                entry["sources"][index] = updated
                save_team_source_registry(entries)
                return updated

    for index, source in enumerate(national_sources):
        if str(source.get("handle") or "") == normalized_handle:
            updated = _normalize_source({**source, **updates}, fallback_team=None, default_type=source.get("sourceType", SOURCE_TYPE_NATIONAL_REPORTER))
            national_sources[index] = updated
            save_national_sources(national_sources)
            return updated

    raise ValueError(f"Unknown source handle: {normalized_handle}")


def _move_source(handle: str, team: str) -> Dict[str, Any]:
    normalized_handle = str(handle or "").strip()
    entries = load_team_source_registry()
    national_sources = load_national_sources()
    moved_source: Optional[Dict[str, Any]] = None

    for entry in entries:
        retained = []
        for source in entry.get("sources", []):
            if str(source.get("handle") or "") == normalized_handle:
                moved_source = source
            else:
                retained.append(source)
        entry["sources"] = retained

    retained_national = []
    for source in national_sources:
        if str(source.get("handle") or "") == normalized_handle:
            moved_source = source
        else:
            retained_national.append(source)

    if moved_source is None:
        raise ValueError(f"Unknown source handle: {normalized_handle}")

    save_national_sources(retained_national)
    updated = _normalize_source({**moved_source, "team": team, "teamCoverage": [team]}, fallback_team=team, default_type=moved_source.get("sourceType", SOURCE_TYPE_TEAM_BEAT))
    for entry in entries:
        if entry["team"] == team:
            entry.setdefault("sources", []).append(updated)
            break
    save_team_source_registry(entries)
    return updated


def get_social_source_coverage_report() -> Dict[str, Any]:
    team_entries = load_team_source_registry()
    team_rows: List[Dict[str, Any]] = []
    complete = 0
    partial = 0
    missing = 0

    for entry in team_entries:
        sources = entry.get("sources", [])
        active_sources = [source for source in sources if source.get("active", False)]
        verified_sources = [source for source in active_sources if source.get("verified", False)]
        tier_1 = [source for source in verified_sources if source.get("tier") == SOURCE_TIER_1]
        tier_2 = [source for source in verified_sources if source.get("tier") == SOURCE_TIER_2]
        tier_3 = [source for source in verified_sources if source.get("tier") == SOURCE_TIER_3]
        official_count = len([source for source in active_sources if source.get("sourceType") == SOURCE_TYPE_TEAM_OFFICIAL])

        if len(verified_sources) >= 3 and official_count >= 1:
            coverage_status = "COMPLETE"
            complete += 1
        elif active_sources:
            coverage_status = "PARTIAL"
            partial += 1
        else:
            coverage_status = "MISSING"
            missing += 1

        team_rows.append(
            {
                "team": entry["team"],
                "sourcesActive": len(active_sources),
                "verifiedSources": len(verified_sources),
                "tier1": len(tier_1),
                "tier2": len(tier_2),
                "tier3": len(tier_3),
                "coverageStatus": coverage_status,
            }
        )

    total_sources = len(_flatten_team_sources(team_entries)) + len(load_national_sources())
    verified_total = len([source for source in get_social_sources(active_only=False, verified_only=True, include_national=True) if source.get("verified", False)])
    covered_count = complete + partial
    coverage_percent = round((covered_count / len(TEAM_CODES)) * 100.0, 1) if TEAM_CODES else 0.0

    return {
        "teamsCovered": len(team_entries),
        "teamsComplete": complete,
        "teamsPartial": partial,
        "teamsMissing": missing,
        "totalSources": total_sources,
        "verifiedSources": verified_total,
        "coveragePercent": coverage_percent,
        "teams": team_rows,
    }


def get_social_source_summary() -> Dict[str, Any]:
    coverage = get_social_source_coverage_report()
    all_sources = get_social_sources(active_only=False, include_national=True)
    active_sources = [source for source in all_sources if source.get("active", False)]
    verified_sources = [source for source in active_sources if source.get("verified", False)]
    return {
        "teamsCovered": coverage["teamsCovered"],
        "sourcesConfigured": len(all_sources),
        "sourcesActive": len(active_sources),
        "verifiedSources": len(verified_sources),
        "sourceTypes": sorted({source["sourceType"] for source in all_sources if source.get("sourceType")}),
        "provider": "REGISTRY",
        "isLive": False,
        "coveragePercent": coverage["coveragePercent"],
    }