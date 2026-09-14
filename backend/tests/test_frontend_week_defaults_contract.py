from __future__ import annotations

from pathlib import Path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_briefing_no_longer_hardcodes_week_one_requests():
    repo_root = Path(__file__).resolve().parents[2]
    briefing = _read(repo_root / "app" / "briefing" / "page.tsx")

    assert "/api/games?week=1" not in briefing
    assert "/api/opportunities?limit=100&week=1" not in briefing


def test_games_and_opportunities_consume_backend_default_week_metadata():
    repo_root = Path(__file__).resolve().parents[2]
    games = _read(repo_root / "app" / "games" / "page.tsx")
    opportunities = _read(repo_root / "app" / "opportunities" / "page.tsx")

    assert "defaultWeek" in games
    assert "canonicalWeek" in games
    assert "defaultWeek" in opportunities
    assert "canonicalWeek" in opportunities
