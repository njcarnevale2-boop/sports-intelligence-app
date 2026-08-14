from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.services.social_sources import (
    SOURCE_TIER_WATCHLIST,
    get_social_sources,
)


DEFAULT_SIGNAL_KEYWORDS = [
    "injury",
    "practice",
    "limited",
    "questionable",
    "out",
    "left practice",
    "did not return",
    "first-team",
    "reps",
    "inactive",
]

DEFAULT_QUERY_LIMIT = 450
DEFAULT_MAX_SOURCES_PER_BATCH = 20


def _normalize_keywords(keywords: Optional[Sequence[str]]) -> List[str]:
    output: List[str] = []
    for keyword in keywords or DEFAULT_SIGNAL_KEYWORDS:
        text = str(keyword or "").strip()
        if text:
            output.append(text)
    return output


def _source_clause(handle: str) -> str:
    return f"from:{handle.lstrip('@')}"


def _keyword_clause(keywords: Sequence[str]) -> str:
    if not keywords:
        return ""
    formatted = []
    for keyword in keywords:
        if " " in keyword:
            formatted.append(f'"{keyword}"')
        else:
            formatted.append(keyword)
    return "(" + " OR ".join(formatted) + ")"


def get_production_query_sources(team: Optional[str] = None) -> List[Dict[str, Any]]:
    sources = get_social_sources(
        team=team,
        active_only=True,
        verified_only=True,
        include_watchlist=False,
        include_national=True,
    )

    deduped: Dict[str, Dict[str, Any]] = {}
    for source in sources:
        handle = str(source.get("handle") or "").strip().lower()
        if not handle or source.get("tier") == SOURCE_TIER_WATCHLIST:
            continue
        deduped.setdefault(handle, source)

    return sorted(
        deduped.values(),
        key=lambda source: (
            int(source.get("priority", 999) or 999),
            -int(source.get("credibilityScore", 0) or 0),
        ),
    )


def build_query_batches(
    sources: Sequence[Dict[str, Any]],
    keywords: Optional[Sequence[str]] = None,
    max_query_length: int = DEFAULT_QUERY_LIMIT,
    max_sources_per_batch: int = DEFAULT_MAX_SOURCES_PER_BATCH,
) -> List[Dict[str, Any]]:
    trusted_sources = []
    seen_handles = set()
    for source in sources:
        if not source.get("active", False) or not source.get("verified", False):
            continue
        if source.get("tier") == SOURCE_TIER_WATCHLIST:
            continue
        handle = str(source.get("handle") or "").strip().lstrip("@").lower()
        if not handle or handle in seen_handles:
            continue
        seen_handles.add(handle)
        trusted_sources.append({**source, "handle": handle})

    keyword_list = _normalize_keywords(keywords)
    keyword_part = _keyword_clause(keyword_list)

    batches: List[Dict[str, Any]] = []
    current_sources: List[Dict[str, Any]] = []
    current_query = ""

    for source in trusted_sources:
        candidate_sources = current_sources + [source]
        source_part = "(" + " OR ".join(_source_clause(item["handle"]) for item in candidate_sources) + ")"
        candidate_query = f"{source_part} {keyword_part}".strip()

        if current_sources and (len(candidate_sources) > max_sources_per_batch or len(candidate_query) > max_query_length):
            batches.append(
                {
                    "query": current_query,
                    "sources": current_sources,
                    "keywords": keyword_list,
                }
            )
            current_sources = [source]
            current_query = f"({_source_clause(source['handle'])}) {keyword_part}".strip()
        else:
            current_sources = candidate_sources
            current_query = candidate_query

    if current_sources:
        batches.append(
            {
                "query": current_query,
                "sources": current_sources,
                "keywords": keyword_list,
            }
        )

    return batches


def build_team_query_batches(
    team: str,
    keywords: Optional[Sequence[str]] = None,
    max_query_length: int = DEFAULT_QUERY_LIMIT,
    max_sources_per_batch: int = DEFAULT_MAX_SOURCES_PER_BATCH,
) -> List[Dict[str, Any]]:
    return build_query_batches(
        get_production_query_sources(team=team),
        keywords=keywords,
        max_query_length=max_query_length,
        max_sources_per_batch=max_sources_per_batch,
    )


def recommend_polling_interval_minutes(
    kickoff: Optional[datetime],
    now: Optional[datetime] = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    if kickoff is None:
        return 120

    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)

    hours_to_kickoff = (kickoff - current_time).total_seconds() / 3600.0
    if hours_to_kickoff <= 6:
        return 10
    if hours_to_kickoff <= 24:
        return 20
    if hours_to_kickoff <= 72:
        return 60
    return 120


def dedupe_posts(posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_ids = set()
    output: List[Dict[str, Any]] = []
    for post in posts:
        post_id = str(post.get("postId") or "").strip()
        if not post_id or post_id in seen_ids:
            continue
        seen_ids.add(post_id)
        output.append(dict(post))
    return output


def build_usage_record(
    query: str,
    batch_index: int,
    posts_read: int,
    team_scope: Optional[str] = None,
    provider: str = "X",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    usage_units = float(posts_read)
    return {
        "provider": provider,
        "teamScope": team_scope,
        "queryText": query,
        "queryBatchIndex": batch_index,
        "postsRead": posts_read,
        "usageUnits": usage_units,
        "estimatedCost": 0.0,
        "metadata": metadata or {},
    }