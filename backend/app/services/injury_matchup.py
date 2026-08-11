from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.injuries import InjuryAnalyzer


class InjuryMatchupContext:
    """
    Build matchup-level injury context from team-level injury analyses.

    The implementation stays mock-driven for now and uses the existing injury
    engine as the source of truth for team injury burden.
    """

    def __init__(self, analyzer: Optional[InjuryAnalyzer] = None):
        self.analyzer = analyzer or InjuryAnalyzer()

    def build_context(self, away_team: str, home_team: str) -> Dict[str, Any]:
        """
        Return matchup-level injury context for two teams.
        """

        analysis = self.analyzer.analyze()
        team_reports = analysis.get("teams", {})

        away_report = team_reports.get(str(away_team).upper(), None)
        home_report = team_reports.get(str(home_team).upper(), None)

        if away_report is None and home_report is None:
            return self._neutral_context(away_team, home_team)

        away_injury_score = away_report["injuryScore"] if away_report else 0.0
        home_injury_score = home_report["injuryScore"] if home_report else 0.0
        away_point_adjustment = away_report["pointAdjustment"] if away_report else 0.0
        home_point_adjustment = home_report["pointAdjustment"] if home_report else 0.0

        net_home_advantage = round(away_point_adjustment - home_point_adjustment, 2)
        net_away_advantage = round(home_point_adjustment - away_point_adjustment, 2)

        absolute_diff = abs(away_point_adjustment - home_point_adjustment)

        if absolute_diff < 0.25:
            healthier_team = "neutral"
        elif away_point_adjustment < home_point_adjustment:
            healthier_team = "home team"
        else:
            healthier_team = "away team"

        severity = self._severity_label(abs(net_home_advantage))
        key_injuries = self._combine_key_injuries(away_report, home_report)
        summary = self._build_summary(
            away_team,
            home_team,
            net_home_advantage,
            key_injuries,
        )

        return {
            "awayTeam": away_team,
            "homeTeam": home_team,
            "awayInjuryScore": round(away_injury_score, 1),
            "homeInjuryScore": round(home_injury_score, 1),
            "awayPointAdjustment": round(away_point_adjustment, 1),
            "homePointAdjustment": round(home_point_adjustment, 1),
            "netHomeInjuryAdvantage": net_home_advantage,
            "netAwayInjuryAdvantage": net_away_advantage,
            "healthierTeam": healthier_team,
            "severity": severity,
            "keyInjuries": key_injuries,
            "summary": summary,
        }

    def _neutral_context(self, away_team: str, home_team: str) -> Dict[str, Any]:
        return {
            "awayTeam": away_team,
            "homeTeam": home_team,
            "awayInjuryScore": 0.0,
            "homeInjuryScore": 0.0,
            "awayPointAdjustment": 0.0,
            "homePointAdjustment": 0.0,
            "netHomeInjuryAdvantage": 0.0,
            "netAwayInjuryAdvantage": 0.0,
            "healthierTeam": "neutral",
            "severity": "Neutral",
            "keyInjuries": [],
            "summary": "No clear injury edge is present for either team in the current mock dataset.",
        }

    def _combine_key_injuries(
        self,
        away_report: Optional[Dict[str, Any]],
        home_report: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        injuries: List[Dict[str, Any]] = []

        if away_report:
            for item in away_report.get("keyPlayers", []):
                injuries.append({
                    "team": "away",
                    "player": item["player"],
                    "position": item["position"],
                    "status": item["status"],
                    "starter": item["starter"],
                    "severity": item["severity"],
                    "weightedImpact": item["weightedImpact"],
                    "estimatedPointImpact": item["estimatedPointImpact"],
                })

        if home_report:
            for item in home_report.get("keyPlayers", []):
                injuries.append({
                    "team": "home",
                    "player": item["player"],
                    "position": item["position"],
                    "status": item["status"],
                    "starter": item["starter"],
                    "severity": item["severity"],
                    "weightedImpact": item["weightedImpact"],
                    "estimatedPointImpact": item["estimatedPointImpact"],
                })

        return sorted(
            injuries,
            key=lambda item: (
                item["weightedImpact"],
                item["estimatedPointImpact"],
            ),
            reverse=True,
        )[:5]

    def _severity_label(self, net_difference: float) -> str:
        if net_difference < 0.25:
            return "Neutral"
        if net_difference < 0.75:
            return "Small"
        if net_difference < 1.5:
            return "Moderate"
        if net_difference < 3.0:
            return "Significant"
        return "Major"

    def _build_summary(
        self,
        away_team: str,
        home_team: str,
        net_home_advantage: float,
        key_injuries: List[Dict[str, Any]],
    ) -> str:
        if not key_injuries:
            return "No clear injury edge is present for either team in the current mock dataset."

        primary = key_injuries[0]
        primary_player = primary["player"]
        primary_team = "home" if primary["team"] == "home" else "away"
        primary_team_name = home_team if primary_team == "home" else away_team

        if net_home_advantage > 0:
            return (
                f"{home_team} enters with a meaningful injury advantage, driven primarily by "
                f"{primary_player}'s status. The current injury context is worth approximately "
                f"{abs(net_home_advantage):.1f} points toward {home_team}."
            )
        if net_home_advantage < 0:
            return (
                f"{away_team} enters with a meaningful injury advantage, driven primarily by "
                f"{primary_player}'s status. The current injury context is worth approximately "
                f"{abs(net_home_advantage):.1f} points toward {away_team}."
            )
        return (
            f"The injury context is roughly neutral, with {primary_player} standing out as the biggest concern."
        )
