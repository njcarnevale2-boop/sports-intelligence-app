from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.providers.provider_manager import ProviderManager
from app.services.market_intelligence import get_market_intelligence
from app.services.sports_intelligence_score import calculate_sports_intelligence_score


MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"
GAME_PROJECTIONS = MODEL_ROOT / "outputs" / "current_game_projections.csv"
SCHEDULE_CONTEXT = MODEL_ROOT / "outputs" / "schedule_context_latest.csv"
RANKED_BET_BOARD = MODEL_ROOT / "outputs" / "ranked_bet_board.csv"


TEAM_META: Dict[str, Dict[str, str]] = {
    "ARI": {"name": "Arizona Cardinals", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ari.png"},
    "ATL": {"name": "Atlanta Falcons", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/atl.png"},
    "BAL": {"name": "Baltimore Ravens", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/bal.png"},
    "BUF": {"name": "Buffalo Bills", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png"},
    "CAR": {"name": "Carolina Panthers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/car.png"},
    "CHI": {"name": "Chicago Bears", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/chi.png"},
    "CIN": {"name": "Cincinnati Bengals", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/cin.png"},
    "CLE": {"name": "Cleveland Browns", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/cle.png"},
    "DAL": {"name": "Dallas Cowboys", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/dal.png"},
    "DEN": {"name": "Denver Broncos", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/den.png"},
    "DET": {"name": "Detroit Lions", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/det.png"},
    "GB": {"name": "Green Bay Packers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/gb.png"},
    "HOU": {"name": "Houston Texans", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png"},
    "IND": {"name": "Indianapolis Colts", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png"},
    "JAX": {"name": "Jacksonville Jaguars", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/jax.png"},
    "KC": {"name": "Kansas City Chiefs", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/kc.png"},
    "LAC": {"name": "Los Angeles Chargers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lac.png"},
    "LAR": {"name": "Los Angeles Rams", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lar.png"},
    "LV": {"name": "Las Vegas Raiders", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lv.png"},
    "MIA": {"name": "Miami Dolphins", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png"},
    "MIN": {"name": "Minnesota Vikings", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/min.png"},
    "NE": {"name": "New England Patriots", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ne.png"},
    "NO": {"name": "New Orleans Saints", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/no.png"},
    "NYG": {"name": "New York Giants", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/nyg.png"},
    "NYJ": {"name": "New York Jets", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/nyj.png"},
    "PHI": {"name": "Philadelphia Eagles", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/phi.png"},
    "PIT": {"name": "Pittsburgh Steelers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/pit.png"},
    "SEA": {"name": "Seattle Seahawks", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/sea.png"},
    "SF": {"name": "San Francisco 49ers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/sf.png"},
    "TB": {"name": "Tampa Bay Buccaneers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/tb.png"},
    "TEN": {"name": "Tennessee Titans", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ten.png"},
    "WAS": {"name": "Washington Commanders", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png"},
}


def safe_float(value: Any) -> Optional[float]:
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> Optional[int]:
    if pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def infer_nfl_season(kickoff: datetime) -> int:
    return kickoff.year if kickoff.month >= 8 else kickoff.year - 1


def parse_commence_time(value: Any) -> Optional[datetime]:
    if value is None or pd.isna(value):
        return None

    text = str(value).strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = pd.to_datetime(text, utc=True, errors="coerce").to_pydatetime()

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def derive_game_status(kickoff: datetime, now_utc: datetime) -> str:
    if kickoff + timedelta(hours=4) <= now_utc:
        return "FINAL"
    if kickoff <= now_utc <= kickoff + timedelta(hours=4):
        return "LIVE"
    return "SCHEDULED"


class GamesService:
    def __init__(self) -> None:
        self.provider_manager = ProviderManager()

    def list_games(self, week: Optional[int] = None, game_date: Optional[str] = None) -> Dict[str, Any]:
        if not GAME_PROJECTIONS.exists():
            return {
                "count": 0,
                "games": [],
                "availableWeeks": [],
                "availableDates": [],
                "source": "unavailable",
                "dataStatus": self._data_status(schedule_available=False, opportunities_available=False),
            }

        schedule_df = pd.read_csv(GAME_PROJECTIONS)
        if schedule_df.empty:
            return {
                "count": 0,
                "games": [],
                "availableWeeks": [],
                "availableDates": [],
                "source": str(GAME_PROJECTIONS),
                "dataStatus": self._data_status(schedule_available=True, opportunities_available=RANKED_BET_BOARD.exists()),
            }

        schedule_df = schedule_df.copy()
        schedule_df["api_event_id"] = schedule_df["api_event_id"].astype(str)

        context_lookup = self._load_schedule_context_lookup()
        opportunities_lookup = self._load_best_opportunities_lookup()

        rows: List[Dict[str, Any]] = []
        now_utc = datetime.now(timezone.utc)

        for _, source_row in schedule_df.iterrows():
            event_id = str(source_row.get("api_event_id", "")).strip()
            if not event_id:
                continue

            kickoff = parse_commence_time(source_row.get("commence_time"))
            if kickoff is None:
                continue

            away_code = str(source_row.get("away_team", "")).strip().upper()
            home_code = str(source_row.get("home_team", "")).strip().upper()
            game_date_text = kickoff.date().isoformat()

            season, mapped_week = self._season_and_week_for_game(
                kickoff=kickoff,
                game_date=game_date_text,
                away_team=away_code,
                home_team=home_code,
                context_lookup=context_lookup,
            )

            team_away = TEAM_META.get(away_code, {})
            team_home = TEAM_META.get(home_code, {})

            enrichment = opportunities_lookup.get(event_id)
            market_intelligence = enrichment.get("marketIntelligence") if enrichment else None
            sports_score = enrichment.get("sportsIntelligenceScore") if enrichment else None

            rows.append(
                {
                    "eventId": event_id,
                    "season": season,
                    "week": mapped_week,
                    "gameDate": game_date_text,
                    "commenceTime": kickoff.isoformat(),
                    "awayTeam": team_away.get("name", away_code),
                    "homeTeam": team_home.get("name", home_code),
                    "awayAbbreviation": away_code,
                    "homeAbbreviation": home_code,
                    "awayLogo": team_away.get("logo"),
                    "homeLogo": team_home.get("logo"),
                    "status": derive_game_status(kickoff, now_utc),
                    "spread": safe_float(source_row.get("market_home_spread")),
                    "total": safe_float(source_row.get("market_total")),
                    "moneyline": enrichment.get("moneyline") if enrichment else None,
                    "bestOpportunity": enrichment.get("bestOpportunity") if enrichment else None,
                    "sportsIntelligenceScore": sports_score,
                    "marketIntelligence": market_intelligence,
                    "injuryContext": None,
                    "weatherContext": None,
                }
            )

        rows.sort(key=lambda row: row["commenceTime"])

        if not rows:
            return {
                "count": 0,
                "games": [],
                "availableWeeks": [],
                "availableDates": [],
                "source": str(GAME_PROJECTIONS),
                "dataStatus": self._data_status(schedule_available=True, opportunities_available=RANKED_BET_BOARD.exists()),
            }

        filtered = rows
        if week is not None:
            filtered = [item for item in filtered if item.get("week") == week]

        if game_date:
            filtered = [item for item in filtered if item.get("gameDate") == game_date]

        available_weeks = sorted({int(item["week"]) for item in rows if item.get("week") is not None})
        available_dates = sorted({item["gameDate"] for item in rows if item.get("gameDate")})

        return {
            "count": len(filtered),
            "games": filtered,
            "availableWeeks": available_weeks,
            "availableDates": available_dates,
            "source": str(GAME_PROJECTIONS),
            "dataStatus": self._data_status(schedule_available=True, opportunities_available=RANKED_BET_BOARD.exists()),
        }

    def _load_schedule_context_lookup(self) -> Dict[Tuple[str, str, str], Tuple[int, int]]:
        if not SCHEDULE_CONTEXT.exists():
            return {}

        try:
            context_df = pd.read_csv(SCHEDULE_CONTEXT)
        except (OSError, pd.errors.EmptyDataError):
            return {}

        required_cols = {"season", "week", "gameday", "away_team", "home_team"}
        if context_df.empty or not required_cols.issubset(set(context_df.columns)):
            return {}

        lookup: Dict[Tuple[str, str, str], Tuple[int, int]] = {}
        for _, row in context_df.iterrows():
            season = safe_int(row.get("season"))
            week = safe_int(row.get("week"))
            if season is None or week is None:
                continue

            game_day = str(row.get("gameday", "")).strip()
            away_team = str(row.get("away_team", "")).strip()
            home_team = str(row.get("home_team", "")).strip()
            if not game_day or not away_team or not home_team:
                continue

            lookup[(game_day, away_team, home_team)] = (season, week)

        return lookup

    def _season_and_week_for_game(
        self,
        kickoff: datetime,
        game_date: str,
        away_team: str,
        home_team: str,
        context_lookup: Dict[Tuple[str, str, str], Tuple[int, int]],
    ) -> Tuple[int, int]:
        direct = context_lookup.get((game_date, away_team, home_team))
        if direct is not None:
            return direct

        season = infer_nfl_season(kickoff)
        season_start = datetime(season, 9, 1, tzinfo=timezone.utc)
        inferred_week = max(1, ((kickoff - season_start).days // 7) + 1)
        return season, inferred_week

    def _load_best_opportunities_lookup(self) -> Dict[str, Dict[str, Any]]:
        if not RANKED_BET_BOARD.exists():
            return {}

        try:
            board_df = pd.read_csv(RANKED_BET_BOARD)
        except (OSError, pd.errors.EmptyDataError):
            return {}

        required_cols = {
            "api_event_id",
            "rank",
            "market",
            "side",
            "point",
            "price",
            "edge_pp",
            "ev_per_dollar",
            "confidence_score",
            "data_completeness",
        }
        if board_df.empty or not required_cols.issubset(set(board_df.columns)):
            return {}

        board_df = board_df.copy()
        board_df["api_event_id"] = board_df["api_event_id"].astype(str)
        board_df = board_df.sort_values("rank")

        output: Dict[str, Dict[str, Any]] = {}
        for event_id, group in board_df.groupby("api_event_id", sort=False):
            best = group.iloc[0]
            market = str(best.get("market", "")).strip().lower()
            side = str(best.get("side", "")).strip().lower()

            market_intelligence = get_market_intelligence(
                event_id=event_id,
                market=market,
                side=side,
            )
            if market_intelligence.get("booksTracked", 0) == 0:
                market_intelligence_payload: Optional[Dict[str, Any]] = None
            else:
                market_intelligence_payload = market_intelligence

            score_payload = calculate_sports_intelligence_score(
                opportunity={
                    "edge": float(best.get("edge_pp", 0.0)) * 100.0,
                    "evPerDollar": float(best.get("ev_per_dollar", 0.0)),
                    "confidence": float(best.get("confidence_score", 0.0)),
                    "dataCompleteness": float(best.get("data_completeness", 0.0)) * 100.0,
                },
                market_intelligence=market_intelligence,
            )

            moneyline = self._extract_moneyline(group)

            output[event_id] = {
                "bestOpportunity": self._format_best_opportunity(best),
                "sportsIntelligenceScore": float(score_payload.get("score", 0.0)),
                "marketIntelligence": market_intelligence_payload,
                "moneyline": moneyline,
            }

        return output

    def _extract_moneyline(self, event_rows: pd.DataFrame) -> Optional[Dict[str, float]]:
        moneyline_rows = event_rows[event_rows["market"].astype(str).str.lower().isin(["moneyline", "h2h"])]
        if moneyline_rows.empty:
            return None

        output: Dict[str, float] = {}
        for _, row in moneyline_rows.iterrows():
            side = str(row.get("side", "")).strip().lower()
            price = safe_float(row.get("price"))
            if price is None:
                continue
            if side in {"home", "away"}:
                output[side] = price

        return output or None

    def _format_best_opportunity(self, row: pd.Series) -> str:
        recommendation = str(row.get("recommendation", "")).strip()
        market = str(row.get("market", "")).strip().lower()
        side = str(row.get("side", "")).strip().lower()
        point = safe_float(row.get("point"))

        if market == "spread":
            if point is None:
                return recommendation or "Unavailable"
            point_text = f"{point:+g}"
            return f"{recommendation}: {side.title()} {point_text}" if recommendation else f"{side.title()} {point_text}"

        if market == "total":
            if point is None:
                return recommendation or "Unavailable"
            return f"{recommendation}: {side.title()} {point:g}" if recommendation else f"{side.title()} {point:g}"

        return recommendation or "Unavailable"

    def _data_status(self, schedule_available: bool, opportunities_available: bool) -> Dict[str, str]:
        provider_metadata = self.provider_manager.metadata()

        injury_provider = provider_metadata.get("injury", {})
        weather_provider = provider_metadata.get("weather", {})

        injury_status = "LIVE" if injury_provider.get("isLive") else "MOCK" if injury_provider.get("provider") == "Mock" else "UNAVAILABLE"
        weather_status = "LIVE" if weather_provider.get("isLive") else "MOCK" if weather_provider.get("provider") == "Mock" else "UNAVAILABLE"

        return {
            "schedule": "CACHED" if schedule_available else "UNAVAILABLE",
            "opportunities": "CACHED" if opportunities_available else "UNAVAILABLE",
            "marketIntelligence": "CACHED" if opportunities_available else "UNAVAILABLE",
            "injury": injury_status,
            "weather": weather_status,
        }


service = GamesService()
