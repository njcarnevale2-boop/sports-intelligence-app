from __future__ import annotations

import json

from app.services.social_sources import (
    SOURCE_TIER_1,
    SOURCE_TIER_2,
    SOURCE_TYPE_TEAM_BEAT,
    SOURCE_TYPE_TEAM_OFFICIAL,
    TEAM_CODES,
    add_source,
    assign_source_tier,
    deactivate_source,
    get_social_source_coverage_report,
    get_social_sources,
    load_national_sources,
    load_team_source_registry,
    save_national_sources,
    save_team_source_registry,
    update_credibility,
    verify_source,
)


def test_32_teams_represented() -> None:
    entries = load_team_source_registry()
    assert len(entries) == 32
    assert [entry["team"] for entry in entries] == TEAM_CODES


def test_source_verification_and_tier_assignment() -> None:
    team_entries = load_team_source_registry()
    national_sources = load_national_sources()

    try:
        add_source(
            {
                "name": "Placeholder Team Source",
                "handle": "placeholder_team_source",
                "sourceType": SOURCE_TYPE_TEAM_OFFICIAL,
                "publication": "Placeholder Outlet",
                "profileUrl": "https://example.com/placeholder-team-source",
                "teamCoverage": ["BUF"],
                "credibilityScore": 92,
                "priority": 1,
                "active": True,
                "verified": False,
                "notes": "Placeholder only for registry tooling tests.",
            },
            team="BUF",
        )

        verified = verify_source("placeholder_team_source")
        assert verified["verified"] is True
        assert verified["verifiedAt"] is not None

        updated = update_credibility("placeholder_team_source", 85)
        assert updated["credibilityScore"] == 85
        assert updated["tier"] == SOURCE_TIER_2

        tiered = assign_source_tier("placeholder_team_source", SOURCE_TIER_1)
        assert tiered["tier"] == SOURCE_TIER_1

        deactivated = deactivate_source("placeholder_team_source")
        assert deactivated["active"] is False
    finally:
        save_team_source_registry(team_entries)
        save_national_sources(national_sources)


def test_duplicate_handles_raise() -> None:
    team_entries = load_team_source_registry()
    national_sources = load_national_sources()

    try:
        add_source(
            {
                "name": "Placeholder Duplicate Source",
                "handle": "duplicate_source_handle",
                "sourceType": SOURCE_TYPE_TEAM_BEAT,
                "teamCoverage": ["BUF"],
                "credibilityScore": 82,
                "priority": 1,
                "active": True,
                "verified": True,
            },
            team="BUF",
        )

        try:
            add_source(
                {
                    "name": "Placeholder Duplicate Source Two",
                    "handle": "duplicate_source_handle",
                    "sourceType": SOURCE_TYPE_TEAM_BEAT,
                    "teamCoverage": ["MIA"],
                    "credibilityScore": 81,
                    "priority": 2,
                    "active": True,
                    "verified": True,
                },
                team="MIA",
            )
            assert False, "Expected duplicate handle validation to raise"
        except ValueError as exc:
            assert "Duplicate source handle" in str(exc)
    finally:
        save_team_source_registry(team_entries)
        save_national_sources(national_sources)


def test_coverage_reporting_shape() -> None:
    coverage = get_social_source_coverage_report()
    assert coverage["teamsCovered"] == 32
    assert "coveragePercent" in coverage
    assert len(coverage["teams"]) == 32


def test_inactive_sources_excluded_from_active_queries() -> None:
    sources = get_social_sources(active_only=True, include_national=True)
    assert all(source.get("active", False) for source in sources)