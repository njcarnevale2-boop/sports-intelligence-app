from __future__ import annotations

from typing import Any, Dict, List, Optional


class InjuryAnalyzer:
    """
    Evaluate mock injury data with realistic NFL weighting.

    The goal is not to predict exact game outcomes, but to provide a
    readable injury intelligence signal that can support later betting
    and roster analysis features.
    """

    def __init__(self, injuries: Optional[List[Dict[str, Any]]] = None):
        # Use provided injuries when supplied; otherwise fall back to a
        # mock roster of realistic NFL injuries.
        self.injuries = injuries or self._mock_injuries()

    def analyze(self) -> Dict[str, Any]:
        """
        Analyze the current injury snapshot and return a compact report.
        """

        scoring_details = []

        for injury in self.injuries:
            severity = self._severity_score(injury)
            impact = self._position_weight(injury) * severity
            scoring_details.append(
                {
                    "player": injury.get("player", "Unknown"),
                    "team": injury.get("team", "Unknown"),
                    "position": injury.get("position", "Unknown"),
                    "status": injury.get("status", "unknown"),
                    "starter": injury.get("starter", False),
                    "impact": injury.get("impact", 0),
                    "severity": severity,
                    "weightedImpact": impact,
                    "category": self._impact_category(injury),
                }
            )

        # Reduce the full injury set into an overall game-impact signal.
        total_weighted = sum(item["weightedImpact"] for item in scoring_details)
        normalized_score = round(clamp(total_weighted / 5.0, 0, 100), 1)

        offensive_impact = round(
            sum(
                item["weightedImpact"]
                for item in scoring_details
                if item["category"] == "offense"
            )
            / 2.0,
            1,
        )
        defensive_impact = round(
            sum(
                item["weightedImpact"]
                for item in scoring_details
                if item["category"] == "defense"
            )
            / 2.0,
            1,
        )
        special_teams_impact = round(
            sum(
                item["weightedImpact"]
                for item in scoring_details
                if item["category"] == "special_teams"
            )
            / 2.0,
            1,
        )

        point_adjustment = round((100 - normalized_score) / 10.0, 1)

        key_players = self._top_key_players(scoring_details)
        summary = self._build_summary(
            normalized_score,
            offensive_impact,
            defensive_impact,
            special_teams_impact,
            point_adjustment,
            key_players,
        )

        return {
            "injuryScore": normalized_score,
            "offensiveImpact": offensive_impact,
            "defensiveImpact": defensive_impact,
            "specialTeamsImpact": special_teams_impact,
            "pointAdjustment": point_adjustment,
            "keyPlayers": key_players,
            "summary": summary,
        }

    def _mock_injuries(self) -> List[Dict[str, Any]]:
        """
        A compact mock dataset with realistic positional value.

        The weighting intentionally makes:
        - QB matter more than RB
        - LT matter a lot
        - CB1 matter a lot
        - backup WR barely move the score
        """

        return [
            {
                "player": "Josh Allen",
                "team": "BUF",
                "position": "QB",
                "status": "questionable",
                "starter": True,
                "impact": 9,
            },
            {
                "player": "Trent Williams",
                "team": "SF",
                "position": "LT",
                "status": "out",
                "starter": True,
                "impact": 8,
            },
            {
                "player": "Darius Slay",
                "team": "PHI",
                "position": "CB1",
                "status": "doubtful",
                "starter": True,
                "impact": 7,
            },
            {
                "player": "Tony Pollard",
                "team": "TEN",
                "position": "RB",
                "status": "questionable",
                "starter": True,
                "impact": 5,
            },
            {
                "player": "Jalen Tolbert",
                "team": "DAL",
                "position": "WR",
                "status": "probable",
                "starter": False,
                "impact": 2,
            },
        ]

    def _position_weight(self, injury: Dict[str, Any]) -> float:
        """
        Use realistic football weighting so the engine reflects positional importance.
        """

        position = str(injury.get("position", "")).upper()

        weights = {
            "QB": 1.00,
            "LT": 0.90,
            "RT": 0.78,
            "C": 0.72,
            "LG": 0.68,
            "RG": 0.68,
            "CB1": 0.80,
            "CB": 0.68,
            "S": 0.62,
            "EDGE": 0.70,
            "DE": 0.66,
            "DT": 0.64,
            "LB": 0.60,
            "RB": 0.56,
            "WR": 0.40,
            "TE": 0.44,
            "K": 0.22,
            "P": 0.18,
        }

        base_weight = weights.get(position, 0.35)

        # Starters matter more than backups, because the loss of a full-time contributor
        # is more disruptive than the loss of a rotational player.
        if injury.get("starter", False):
            base_weight *= 1.15

        return base_weight

    def _severity_score(self, injury: Dict[str, Any]) -> float:
        """
        Convert status and impact into a 0-10 severity score.
        """

        status = str(injury.get("status", "")).lower()
        impact = float(injury.get("impact", 0) or 0)

        status_weights = {
            "out": 1.0,
            "doubtful": 0.85,
            "questionable": 0.65,
            "probable": 0.40,
            "healthy": 0.10,
        }

        severity = status_weights.get(status, 0.3) * (impact / 10.0) * 10.0

        # A high-impact player can move the metric further even if the status is only
        # questionable. That keeps the engine realistic without overreacting to every report.
        if impact >= 8:
            severity += 1.2
        elif impact >= 6:
            severity += 0.7
        elif impact >= 4:
            severity += 0.3

        return clamp(severity, 0.0, 10.0)

    def _impact_category(self, injury: Dict[str, Any]) -> str:
        """
        Group injuries into offense, defense, or special teams based on the position.
        """

        position = str(injury.get("position", "")).upper()

        if position in {"QB", "LT", "RT", "C", "LG", "RG", "RB", "WR", "TE"}:
            return "offense"
        if position in {"CB1", "CB", "S", "EDGE", "DE", "DT", "LB"}:
            return "defense"
        return "special_teams"

    def _top_key_players(self, scoring_details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Return the three most meaningful injuries.
        """

        ranked = sorted(
            scoring_details,
            key=lambda item: item["weightedImpact"],
            reverse=True,
        )

        return [
            {
                "player": item["player"],
                "team": item["team"],
                "position": item["position"],
                "status": item["status"],
                "severity": round(item["severity"], 1),
                "weightedImpact": round(item["weightedImpact"], 1),
            }
            for item in ranked[:3]
        ]

    def _build_summary(
        self,
        injury_score: float,
        offensive_impact: float,
        defensive_impact: float,
        special_teams_impact: float,
        point_adjustment: float,
        key_players: List[Dict[str, Any]],
    ) -> str:
        """
        Create a natural-language summary for the UI.
        """

        player_names = ", ".join(item["player"] for item in key_players)

        if injury_score >= 75:
            return (
                f"Severe injury pressure is present, led by {player_names}. "
                "The matchup profile is meaningfully altered on both sides of the ball."
            )
        if injury_score >= 50:
            return (
                f"Moderate injury pressure is shaping the game, with {player_names} "
                "standing out as the most relevant losses."
            )
        return (
            f"Injury impact is light overall, with {player_names} contributing only minor disruption."
        )


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    """Clamp a numeric value to a bounded range."""

    return max(minimum, min(maximum, value))
