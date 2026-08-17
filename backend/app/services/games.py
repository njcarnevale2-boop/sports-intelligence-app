from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.providers.provider_manager import ProviderManager
from app.services.market_data import market_data_service
from app.services.market_intelligence import build_market_intelligence_lookup, normalize_market
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

TEAM_CODE_ALIASES = {
    "LA": "LAR",
    "JAC": "JAX",
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


def normalize_team_code(team_code: str) -> str:
    code = str(team_code or "").strip().upper()
    return TEAM_CODE_ALIASES.get(code, code)


def derive_game_status(kickoff: datetime, now_utc: datetime) -> str:
    if kickoff + timedelta(hours=4) <= now_utc:
        return "FINAL"
    if kickoff <= now_utc <= kickoff + timedelta(hours=4):
        return "LIVE"
    return "SCHEDULED"


class GamesService:
    def __init__(self) -> None:
        self.provider_manager = ProviderManager()
        self._schedule_context_cache: Dict[Tuple[str, str, str], Tuple[int, int]] = {}
        self._schedule_context_mtime: Optional[float] = None
        self._opportunities_cache: Dict[Tuple[Optional[float], Optional[Tuple[str, ...]]], Dict[str, Dict[str, Any]]] = {}

    def list_games(self, week: Optional[int] = None, game_date: Optional[str] = None) -> Dict[str, Any]:
        market_meta = market_data_service.metadata()

        if not GAME_PROJECTIONS.exists():
            return {
                "count": 0,
                "games": [],
                "availableWeeks": [],
                "availableDates": [],
                "source": "unavailable",
                "dataStatus": self._data_status(schedule_available=False, opportunities_available=False),
                "provider": market_meta["provider"],
                "lastUpdated": market_meta["lastUpdated"],
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
                "provider": market_meta["provider"],
                "lastUpdated": market_meta["lastUpdated"],
            }

        schedule_df = schedule_df.copy()
        schedule_df["api_event_id"] = schedule_df["api_event_id"].astype(str)

        context_lookup = self._load_schedule_context_lookup()
        now_utc = datetime.now(timezone.utc)

        candidate_rows: List[Dict[str, Any]] = []
        for _, source_row in schedule_df.iterrows():
            event_id = str(source_row.get("api_event_id", "")).strip()
            if not event_id:
                continue

            kickoff = parse_commence_time(source_row.get("commence_time"))
            if kickoff is None:
                continue

            away_code = normalize_team_code(source_row.get("away_team", ""))
            home_code = normalize_team_code(source_row.get("home_team", ""))
            game_date_text = kickoff.date().isoformat()

            season, mapped_week = self._season_and_week_for_game(
                kickoff=kickoff,
                game_date=game_date_text,
                away_team=away_code,
                home_team=home_code,
                context_lookup=context_lookup,
            )

            candidate_rows.append(
                {
                    "eventId": event_id,
                    "season": season,
                    "week": mapped_week,
                    "gameDate": game_date_text,
                    "commenceTime": kickoff,
                    "awayCode": away_code,
                    "homeCode": home_code,
                    "sourceRow": source_row,
                }
            )

        # Compute available weeks/dates from the full unfiltered slate so selectors
        # always reflect the complete schedule regardless of the active filter.
        available_weeks = sorted({int(item["week"]) for item in candidate_rows if item.get("week") is not None})
        available_dates = sorted({item["gameDate"] for item in candidate_rows if item.get("gameDate")})

        if week is not None:
            candidate_rows = [item for item in candidate_rows if item.get("week") == week]
        if game_date:
            candidate_rows = [item for item in candidate_rows if item.get("gameDate") == game_date]

        if not candidate_rows:
            return {
                "count": 0,
                "games": [],
                "availableWeeks": available_weeks,
                "availableDates": available_dates,
                "source": str(GAME_PROJECTIONS),
                "dataStatus": self._data_status(schedule_available=True, opportunities_available=RANKED_BET_BOARD.exists()),
                "provider": market_meta["provider"],
                "lastUpdated": market_meta["lastUpdated"],
            }

        opportunities_lookup = self._load_best_opportunities_lookup({item["eventId"] for item in candidate_rows})
        market_lookup = market_data_service.all_event_snapshots()

        rows: List[Dict[str, Any]] = []
        for item in candidate_rows:
            event_id = item["eventId"]
            kickoff = item["commenceTime"]
            away_code = item["awayCode"]
            home_code = item["homeCode"]
            source_row = item["sourceRow"]
            team_away = TEAM_META.get(away_code, {})
            team_home = TEAM_META.get(home_code, {})

            enrichment = opportunities_lookup.get(event_id)
            market_intelligence = enrichment.get("marketIntelligence") if enrichment else None
            sports_score = enrichment.get("sportsIntelligenceScore") if enrichment else None
            market_snapshot = market_lookup.get(event_id, {})

            qualification_status = "QUALIFIED" if enrichment else "NOT_QUALIFIED"
            bet_status = "NO QUALIFIED BET"
            qualification_reasons = ["Current edge and confidence do not meet SIA qualification thresholds."]
            recommendation_label = enrichment.get("recommendationLabel") if enrichment else None

            if enrichment:
                recommendation_upper = str(recommendation_label or "").upper()
                if "STRONG" in recommendation_upper or "ELITE" in recommendation_upper:
                    bet_status = "STRONG BET"
                elif "LEAN" in recommendation_upper:
                    bet_status = "LEAN"
                else:
                    bet_status = "QUALIFIED"
                qualification_reasons = ["Current model edge and confidence meet SIA qualification thresholds."]
            elif market_snapshot.get("booksTracked", 0) == 0:
                qualification_status = "INSUFFICIENT_DATA"
                bet_status = "INSUFFICIENT DATA"
                qualification_reasons = ["Insufficient market data to evaluate a qualified bet."]

            best_away_spread = market_snapshot.get("bestAwaySpread")
            best_home_spread = market_snapshot.get("bestHomeSpread")
            best_over = market_snapshot.get("bestOver")
            best_under = market_snapshot.get("bestUnder")

            best_available_line = {
                "awaySpread": best_away_spread,
                "homeSpread": best_home_spread,
                "over": best_over,
                "under": best_under,
            }

            best_sportsbook = {
                "awaySpread": best_away_spread.get("sportsbook") if best_away_spread else None,
                "homeSpread": best_home_spread.get("sportsbook") if best_home_spread else None,
                "over": best_over.get("sportsbook") if best_over else None,
                "under": best_under.get("sportsbook") if best_under else None,
            }

            rows.append(
                {
                    "eventId": event_id,
                    "season": item["season"],
                    "week": item["week"],
                    "gameDate": item["gameDate"],
                    "commenceTime": kickoff.isoformat(),
                    "awayTeam": team_away.get("name", away_code),
                    "homeTeam": team_home.get("name", home_code),
                    "awayAbbreviation": away_code,
                    "homeAbbreviation": home_code,
                    "awayLogo": team_away.get("logo"),
                    "homeLogo": team_home.get("logo"),
                    "status": derive_game_status(kickoff, now_utc),
                    "spread": market_snapshot.get("consensusSpread", safe_float(source_row.get("market_home_spread"))),
                    "total": market_snapshot.get("consensusTotal", safe_float(source_row.get("market_total"))),
                    "moneyline": market_snapshot.get("consensusMoneyline"),
                    "bestOpportunity": enrichment.get("bestOpportunity") if enrichment else None,
                    "sportsIntelligenceScore": sports_score,
                    "marketIntelligence": market_intelligence,
                    "bestAvailableLine": best_available_line,
                    "bestSportsbook": best_sportsbook,
                    "booksTracked": market_snapshot.get("booksTracked", 0),
                    "marketLastUpdated": market_snapshot.get("lastUpdated"),
                    "marketProvider": market_snapshot.get("provider", market_meta["provider"]),
                    "marketDataStatus": market_snapshot.get("dataStatus", "UNAVAILABLE"),
                    "injuryContext": None,
                    "weatherContext": None,
                    "recommendation": recommendation_label,
                    "qualificationStatus": qualification_status,
                    "qualificationReasons": qualification_reasons,
                    "betStatus": bet_status,
                }
            )

        rows.sort(key=lambda row: row["commenceTime"])

        return {
            "count": len(rows),
            "games": rows,
            "availableWeeks": available_weeks,
            "availableDates": available_dates,
            "source": str(GAME_PROJECTIONS),
            "dataStatus": self._data_status(schedule_available=True, opportunities_available=RANKED_BET_BOARD.exists()),
            "provider": market_meta["provider"],
            "lastUpdated": market_meta["lastUpdated"],
        }

    def _load_schedule_context_lookup(self) -> Dict[Tuple[str, str, str], Tuple[int, int]]:
        if not SCHEDULE_CONTEXT.exists():
            return {}

        try:
            modified_time = SCHEDULE_CONTEXT.stat().st_mtime
        except OSError:
            return {}

        if self._schedule_context_mtime == modified_time and self._schedule_context_cache:
            return self._schedule_context_cache

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
            away_team = normalize_team_code(row.get("away_team", ""))
            home_team = normalize_team_code(row.get("home_team", ""))
            if not game_day or not away_team or not home_team:
                continue

            lookup[(game_day, away_team, home_team)] = (season, week)

        self._schedule_context_cache = lookup
        self._schedule_context_mtime = modified_time
        return lookup

    def _season_and_week_for_game(
        self,
        kickoff: datetime,
        game_date: str,
        away_team: str,
        home_team: str,
        context_lookup: Dict[Tuple[str, str, str], Tuple[int, int]],
    ) -> Tuple[int, int]:
        kickoff_date = kickoff.date()
        candidate_dates = [
            game_date,
            (kickoff_date - timedelta(days=1)).isoformat(),
            (kickoff_date + timedelta(days=1)).isoformat(),
        ]

        for candidate in candidate_dates:
            direct = context_lookup.get((candidate, away_team, home_team))
            if direct is not None:
                return direct

        season = infer_nfl_season(kickoff)
        season_start = datetime(season, 9, 1, tzinfo=timezone.utc)
        inferred_week = max(1, ((kickoff - season_start).days // 7) + 1)
        return season, inferred_week

    def _load_best_opportunities_lookup(self, event_ids: Optional[set[str]] = None) -> Dict[str, Dict[str, Any]]:
        if not RANKED_BET_BOARD.exists():
            return {}

        try:
            modified_time = RANKED_BET_BOARD.stat().st_mtime
        except OSError:
            modified_time = None

        normalized_ids: Optional[Tuple[str, ...]] = None
        if event_ids is not None:
            normalized_ids = tuple(sorted(str(event_id) for event_id in event_ids if str(event_id).strip()))

        cache_key = (modified_time, normalized_ids)
        cached_lookup = self._opportunities_cache.get(cache_key)
        if cached_lookup is not None:
            return cached_lookup

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
        if event_ids is not None:
            event_ids = {str(event_id) for event_id in event_ids}
            board_df = board_df[board_df["api_event_id"].isin(event_ids)]
        if board_df.empty:
            self._opportunities_cache[cache_key] = {}
            return {}

        board_df = board_df.sort_values("rank")
        best_rows_by_event: List[Tuple[str, pd.Series, pd.DataFrame]] = []
        selection_keys: set[Tuple[str, str, str]] = set()
        for event_id, group in board_df.groupby("api_event_id", sort=False):
            best = group.iloc[0]
            market = str(best.get("market", "")).strip().lower()
            side = str(best.get("side", "")).strip().lower()

            best_rows_by_event.append((event_id, best, group))
            selection_keys.add((str(event_id), market, side))

        lookup_event_ids = {event_id for event_id, _, _ in best_rows_by_event}
        market_intelligence_lookup = build_market_intelligence_lookup(
            event_ids=lookup_event_ids,
            selection_keys=selection_keys,
        )

        output: Dict[str, Dict[str, Any]] = {}
        for event_id, best, group in best_rows_by_event:
            market = str(best.get("market", "")).strip().lower()
            side = str(best.get("side", "")).strip().lower()

            market_intelligence = market_intelligence_lookup.get(
                (str(event_id), normalize_market(market), str(side).lower()),
                {},
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
                "recommendationLabel": str(best.get("recommendation", "")).strip() or None,
                "sportsIntelligenceScore": float(score_payload.get("score", 0.0)),
                "marketIntelligence": market_intelligence_payload,
                "moneyline": moneyline,
            }
        self._opportunities_cache[cache_key] = output
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

        market_meta = market_data_service.metadata()

        return {
            "schedule": "CACHED" if schedule_available else "UNAVAILABLE",
            "opportunities": "FILE" if opportunities_available else "UNAVAILABLE",
            "marketIntelligence": market_meta.get("dataStatus", "UNAVAILABLE"),
            "injury": injury_status,
            "weather": weather_status,
        }


service = GamesService()
