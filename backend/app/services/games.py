from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional


TEAM_META = {
    "Buffalo Bills": {"abbr": "BUF", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png"},
    "Baltimore Ravens": {"abbr": "BAL", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/bal.png"},
    "Miami Dolphins": {"abbr": "MIA", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png"},
    "New England Patriots": {"abbr": "NE", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ne.png"},
    "New York Jets": {"abbr": "NYJ", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/nyj.png"},
    "Pittsburgh Steelers": {"abbr": "PIT", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/pit.png"},
    "Cincinnati Bengals": {"abbr": "CIN", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/cin.png"},
    "Cleveland Browns": {"abbr": "CLE", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/cle.png"},
    "Kansas City Chiefs": {"abbr": "KC", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/kc.png"},
    "Denver Broncos": {"abbr": "DEN", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/den.png"},
    "Las Vegas Raiders": {"abbr": "LV", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lv.png"},
    "Los Angeles Chargers": {"abbr": "LAC", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lac.png"},
    "Houston Texans": {"abbr": "HOU", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png"},
    "Indianapolis Colts": {"abbr": "IND", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png"},
    "Jacksonville Jaguars": {"abbr": "JAX", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/jax.png"},
    "Tennessee Titans": {"abbr": "TEN", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ten.png"},
    "Philadelphia Eagles": {"abbr": "PHI", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/phi.png"},
    "Dallas Cowboys": {"abbr": "DAL", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/dal.png"},
    "Washington Commanders": {"abbr": "WAS", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png"},
    "New York Giants": {"abbr": "NYG", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/nyg.png"},
    "Detroit Lions": {"abbr": "DET", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/det.png"},
    "Green Bay Packers": {"abbr": "GB", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/gb.png"},
    "Minnesota Vikings": {"abbr": "MIN", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/min.png"},
    "Chicago Bears": {"abbr": "CHI", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/chi.png"},
    "San Francisco 49ers": {"abbr": "SF", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/sf.png"},
    "Arizona Cardinals": {"abbr": "ARI", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ari.png"},
    "Los Angeles Rams": {"abbr": "LAR", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lar.png"},
    "Seattle Seahawks": {"abbr": "SEA", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/sea.png"},
    "New Orleans Saints": {"abbr": "NO", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/no.png"},
    "Tampa Bay Buccaneers": {"abbr": "TB", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/tb.png"},
    "Atlanta Falcons": {"abbr": "ATL", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/atl.png"},
    "Carolina Panthers": {"abbr": "CAR", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/car.png"},
    "Kansas City Chiefs": {"abbr": "KC", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/kc.png"},
}

WEEK_MATCHUPS = {
    1: [
        ("Buffalo Bills", "Baltimore Ravens"),
        ("Miami Dolphins", "New England Patriots"),
        ("New York Jets", "Pittsburgh Steelers"),
        ("Cincinnati Bengals", "Cleveland Browns"),
        ("Kansas City Chiefs", "Denver Broncos"),
        ("Las Vegas Raiders", "Los Angeles Chargers"),
        ("Houston Texans", "Indianapolis Colts"),
        ("Jacksonville Jaguars", "Tennessee Titans"),
        ("Philadelphia Eagles", "Dallas Cowboys"),
        ("Washington Commanders", "New York Giants"),
        ("Detroit Lions", "Green Bay Packers"),
        ("Minnesota Vikings", "Chicago Bears"),
        ("San Francisco 49ers", "Arizona Cardinals"),
        ("Los Angeles Rams", "Seattle Seahawks"),
        ("New Orleans Saints", "Tampa Bay Buccaneers"),
        ("Atlanta Falcons", "Carolina Panthers"),
    ],
    2: [
        ("Baltimore Ravens", "Miami Dolphins"),
        ("New England Patriots", "Buffalo Bills"),
        ("Pittsburgh Steelers", "Cincinnati Bengals"),
        ("Cleveland Browns", "Kansas City Chiefs"),
        ("Denver Broncos", "Las Vegas Raiders"),
        ("Los Angeles Chargers", "Houston Texans"),
        ("Indianapolis Colts", "Jacksonville Jaguars"),
        ("Tennessee Titans", "Philadelphia Eagles"),
        ("Dallas Cowboys", "Washington Commanders"),
        ("New York Giants", "Detroit Lions"),
        ("Green Bay Packers", "Minnesota Vikings"),
        ("Chicago Bears", "San Francisco 49ers"),
        ("Arizona Cardinals", "Los Angeles Rams"),
        ("Seattle Seahawks", "New Orleans Saints"),
        ("Tampa Bay Buccaneers", "Atlanta Falcons"),
        ("Carolina Panthers", "Buffalo Bills"),
    ],
    3: [
        ("Buffalo Bills", "Miami Dolphins"),
        ("Baltimore Ravens", "New England Patriots"),
        ("Pittsburgh Steelers", "Denver Broncos"),
        ("Cincinnati Bengals", "Kansas City Chiefs"),
        ("Cleveland Browns", "Las Vegas Raiders"),
        ("Houston Texans", "Tennessee Titans"),
        ("Indianapolis Colts", "Philadelphia Eagles"),
        ("Jacksonville Jaguars", "Dallas Cowboys"),
        ("Washington Commanders", "Green Bay Packers"),
        ("New York Giants", "Chicago Bears"),
        ("Detroit Lions", "San Francisco 49ers"),
        ("Minnesota Vikings", "Arizona Cardinals"),
        ("Los Angeles Rams", "Tampa Bay Buccaneers"),
        ("Seattle Seahawks", "Atlanta Falcons"),
        ("New Orleans Saints", "Carolina Panthers"),
        ("Tampa Bay Buccaneers", "Buffalo Bills"),
    ],
}

DAY_ORDER = ["Thu", "Fri", "Sat", "Sun", "Mon"]


class GamesService:
    def list_games(self, week: Optional[int] = None, date: Optional[str] = None) -> List[Dict[str, Any]]:
        requested_week = week or 1
        requested_day = (date or "").strip().title()
        games: List[Dict[str, Any]] = []

        for index, matchup in enumerate(WEEK_MATCHUPS.get(requested_week, [])):
            away_team, home_team = matchup
            day = DAY_ORDER[index % len(DAY_ORDER)]
            if requested_day and requested_day != day:
                continue

            kickoff_date = date(2026, 9, 10) + timedelta(days=(requested_week - 1) * 7 + (index // 2))
            kickoff = f"{day} • {kickoff_date.strftime('%b %d')} • 8:{(index % 6) + 10} PM ET"
            projected_away = 20 + ((index + requested_week) % 9) + 2
            projected_home = 21 + ((index + requested_week * 2) % 8) + 1
            spread = -2.5 + ((index + requested_week) % 5) * 0.5
            total = 42.5 + ((index + requested_week) % 4)
            score = 73 + requested_week * 3 + (index % 6)
            grade = "Elite Opportunity" if score >= 84 else "Lean" if score >= 76 else "Pass"
            best_bet = "Elite Opportunity" if score >= 84 else "No current betting edge." if score < 74 else "Lean"
            confidence = 76 + (index % 8) + requested_week
            weather = self._weather_summary(index, requested_week)
            injury = self._injury_summary(away_team, home_team)
            line_movement = self._line_movement_summary(index, requested_week)

            games.append(
                {
                    "eventId": f"2026-W{requested_week}-{index + 1:02d}",
                    "season": 2026,
                    "week": requested_week,
                    "date": kickoff_date.strftime("%Y-%m-%d"),
                    "kickoff": kickoff,
                    "awayTeam": away_team,
                    "homeTeam": home_team,
                    "awayLogo": TEAM_META[away_team]["logo"],
                    "homeLogo": TEAM_META[home_team]["logo"],
                    "marketSpread": round(spread, 1),
                    "marketTotal": round(total, 1),
                    "projectedAwayScore": projected_away,
                    "projectedHomeScore": projected_home,
                    "sportsIntelligenceScore": score,
                    "marketGrade": grade,
                    "bestBet": best_bet,
                    "confidence": min(confidence, 98),
                    "weatherSummary": weather,
                    "injurySummary": injury,
                    "lineMovementSummary": line_movement,
                }
            )

        return sorted(games, key=lambda game: (game["date"], game["kickoff"]))

    def _weather_summary(self, index: int, week: int) -> str:
        weather_modes = [
            "Mild conditions should keep passing efficiency intact.",
            "Wind may suppress deep passing volume in the second half.",
            "A wet field will elevate turnover risk and shorten drives.",
            "Indoor conditions keep the environment neutral and clean.",
        ]
        return weather_modes[(index + week) % len(weather_modes)]

    def _injury_summary(self, away_team: str, home_team: str) -> str:
        return f"{away_team} and {home_team} carry balanced health profiles, though the skill-position depth is worth monitoring."

    def _line_movement_summary(self, index: int, week: int) -> str:
        movement_modes = [
            "The market has held firm at the opening number after early sharp support.",
            "The spread has moved one point in the home team's favor as public money arrived.",
            "A late buyback on the favorite suggests a more efficient market read is forming.",
            "The total has climbed as weather expectations and sharp action align.",
        ]
        return movement_modes[(index + week) % len(movement_modes)]


service = GamesService()
