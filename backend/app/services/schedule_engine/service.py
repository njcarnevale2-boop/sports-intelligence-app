from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from app.runtime_paths import runtime_paths
from app.services.result_engine import build_canonical_event_identity, normalize_kickoff_utc, normalize_team_id


try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
_EASTERN = ZoneInfo("America/New_York")
_UTC = timezone.utc


class ScheduleEngineError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalScheduleEvent:
    source_event_id: str
    canonical_event_key: str
    season: int
    week: int
    game_type: str
    gameday: str
    kickoff_utc: str
    away_team: str
    home_team: str


@dataclass(frozen=True)
class CanonicalWeeklySchedule:
    schedule_version: str
    schedule_hash: str
    season: int
    week: int
    event_count: int
    source: str
    source_version: str | None
    source_dataset_version: str | None
    source_content_sha256: str | None
    source_manifest_identity: str | None
    generated_at: str
    payload_hash: str
    events: tuple[CanonicalScheduleEvent, ...]


def _utc_now_iso() -> str:
    return datetime.now(_UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScheduleEngineError(f"{field_name} must be a non-empty string")
    text = value.strip()
    if text in {".", ".."}:
        raise ScheduleEngineError(f"{field_name} contains unsupported characters: {text}")
    if not _IDENTIFIER_RE.match(text):
        raise ScheduleEngineError(f"{field_name} contains unsupported characters: {text}")
    return text


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_hex(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        if hasattr(os, "O_DIRECTORY"):
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


@contextmanager
def _file_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_json_file(path: Path, *, field_name: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScheduleEngineError(f"Failed to read {field_name}: {path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScheduleEngineError(f"Corrupt JSON in {field_name}: {path}") from exc
    if not isinstance(payload, dict):
        raise ScheduleEngineError(f"Malformed {field_name}: expected JSON object")
    return payload


def _parse_gameday(value: Any) -> date:
    text = str(value or "").strip()
    if not text:
        raise ScheduleEngineError("SCHEDULE_GAMEDAY_MISSING")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ScheduleEngineError(f"SCHEDULE_GAMEDAY_INVALID: {text}") from exc


def _parse_gametime(value: Any) -> time:
    text = str(value or "").strip()
    if not text:
        raise ScheduleEngineError("SCHEDULE_GAMETIME_MISSING")
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ScheduleEngineError(f"SCHEDULE_GAMETIME_INVALID: {text}")


def _normalize_kickoff_from_eastern(*, gameday_value: Any, gametime_value: Any) -> str:
    gameday = _parse_gameday(gameday_value)
    gametime = _parse_gametime(gametime_value)
    local_dt = datetime.combine(gameday, gametime, tzinfo=_EASTERN)
    kickoff_utc = local_dt.astimezone(_UTC)
    return normalize_kickoff_utc(kickoff_utc.isoformat().replace("+00:00", "Z"))


def _schedule_identity_payload(events: tuple[CanonicalScheduleEvent, ...], *, season: int, week: int) -> dict[str, Any]:
    ordered = sorted(events, key=lambda item: (item.kickoff_utc, item.canonical_event_key))
    return {
        "season": int(season),
        "week": int(week),
        "events": [
            {
                "source_event_id": item.source_event_id,
                "canonical_event_key": item.canonical_event_key,
                "game_type": item.game_type,
                "gameday": item.gameday,
                "kickoff_utc": item.kickoff_utc,
                "away_team": item.away_team,
                "home_team": item.home_team,
            }
            for item in ordered
        ],
    }


def _schedule_hash(events: tuple[CanonicalScheduleEvent, ...], *, season: int, week: int) -> str:
    return _sha256_hex(_canonical_json(_schedule_identity_payload(events, season=season, week=week)))


def _payload_hash(schedule: CanonicalWeeklySchedule) -> str:
    payload = {
        "schedule_version": schedule.schedule_version,
        "schedule_hash": schedule.schedule_hash,
        "season": schedule.season,
        "week": schedule.week,
        "event_count": schedule.event_count,
        "source": schedule.source,
        "source_version": schedule.source_version,
        "source_dataset_version": schedule.source_dataset_version,
        "source_content_sha256": schedule.source_content_sha256,
        "source_manifest_identity": schedule.source_manifest_identity,
        "events": _schedule_identity_payload(schedule.events, season=schedule.season, week=schedule.week)["events"],
    }
    return _sha256_hex(_canonical_json(payload))


def _event_from_payload(payload: dict[str, Any]) -> CanonicalScheduleEvent:
    event = CanonicalScheduleEvent(
        source_event_id=str(payload["source_event_id"]),
        canonical_event_key=str(payload["canonical_event_key"]),
        season=int(payload["season"]),
        week=int(payload["week"]),
        game_type=str(payload.get("game_type") or "REG"),
        gameday=str(payload["gameday"]),
        kickoff_utc=str(payload["kickoff_utc"]),
        away_team=str(payload["away_team"]),
        home_team=str(payload["home_team"]),
    )
    _validate_schedule_event(event)
    return event


def _schedule_from_payload(payload: dict[str, Any]) -> CanonicalWeeklySchedule:
    required = {
        "schedule_version",
        "schedule_hash",
        "season",
        "week",
        "event_count",
        "source",
        "source_dataset_version",
        "generated_at",
        "payload_hash",
        "events",
    }
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise ScheduleEngineError(f"Malformed schedule artifact missing fields: {missing}")
    events_raw = payload.get("events")
    if not isinstance(events_raw, list):
        raise ScheduleEngineError("Malformed schedule artifact: events must be a list")
    schedule = CanonicalWeeklySchedule(
        schedule_version=str(payload["schedule_version"]),
        schedule_hash=str(payload["schedule_hash"]),
        season=int(payload["season"]),
        week=int(payload["week"]),
        event_count=int(payload["event_count"]),
        source=str(payload["source"]),
        source_version=None if payload.get("source_version") in (None, "") else str(payload.get("source_version")),
        source_dataset_version=None if payload.get("source_dataset_version") in (None, "") else str(payload["source_dataset_version"]),
        source_content_sha256=None if payload.get("source_content_sha256") in (None, "") else str(payload.get("source_content_sha256")),
        source_manifest_identity=None if payload.get("source_manifest_identity") in (None, "") else str(payload.get("source_manifest_identity")),
        generated_at=str(payload["generated_at"]),
        payload_hash=str(payload["payload_hash"]),
        events=tuple(_event_from_payload(item) for item in events_raw),
    )
    _validate_schedule(schedule)
    return schedule


def _validate_schedule_event(event: CanonicalScheduleEvent) -> None:
    _validate_identifier(event.source_event_id, "source_event_id")
    _validate_identifier(event.canonical_event_key, "canonical_event_key")
    _validate_identifier(event.game_type, "game_type")
    _parse_gameday(event.gameday)
    normalize_team_id(event.away_team)
    normalize_team_id(event.home_team)
    if event.away_team == event.home_team:
        raise ScheduleEngineError("SCHEDULE_IDENTITY_INVALID")
    normalized = build_canonical_event_identity(
        season=event.season,
        week=event.week,
        kickoff_utc=event.kickoff_utc,
        away_team=event.away_team,
        home_team=event.home_team,
    )
    if normalized.canonical_event_key != event.canonical_event_key:
        raise ScheduleEngineError("SCHEDULE_CANONICAL_EVENT_KEY_MISMATCH")
    kickoff_local_date = datetime.fromisoformat(normalized.kickoff_utc.replace("Z", "+00:00")).astimezone(_EASTERN).date().isoformat()
    if kickoff_local_date != event.gameday:
        raise ScheduleEngineError("SCHEDULE_GAMEDAY_KICKOFF_MISMATCH")


def _validate_schedule(schedule: CanonicalWeeklySchedule) -> None:
    if schedule.season <= 0:
        raise ScheduleEngineError("SEASON_INVALID")
    if schedule.week <= 0:
        raise ScheduleEngineError("WEEK_INVALID")
    if schedule.event_count <= 0:
        raise ScheduleEngineError("SCHEDULE_EVENT_COUNT_INVALID")
    if len(schedule.events) != schedule.event_count:
        raise ScheduleEngineError("SCHEDULE_EVENT_COUNT_MISMATCH")
    source_event_ids = [event.source_event_id for event in schedule.events]
    canonical_keys = [event.canonical_event_key for event in schedule.events]
    matchups = [f"{event.away_team}@{event.home_team}" for event in schedule.events]
    team_counts: dict[str, int] = {}
    for event in schedule.events:
        if event.season != schedule.season or event.week != schedule.week:
            raise ScheduleEngineError("SCHEDULE_SEASON_WEEK_MISMATCH")
        _validate_schedule_event(event)
        team_counts[event.away_team] = team_counts.get(event.away_team, 0) + 1
        team_counts[event.home_team] = team_counts.get(event.home_team, 0) + 1
    if len(source_event_ids) != len(set(source_event_ids)):
        raise ScheduleEngineError("SCHEDULE_DUPLICATE_SOURCE_EVENT_ID")
    if len(canonical_keys) != len(set(canonical_keys)):
        raise ScheduleEngineError("SCHEDULE_DUPLICATE_CANONICAL_EVENT_KEY")
    if len(matchups) != len(set(matchups)):
        raise ScheduleEngineError("SCHEDULE_DUPLICATE_MATCHUP")
    if any(count > 1 for count in team_counts.values()):
        raise ScheduleEngineError("SCHEDULE_DUPLICATE_TEAM")
    expected_hash = _schedule_hash(schedule.events, season=schedule.season, week=schedule.week)
    if schedule.schedule_hash != expected_hash:
        raise ScheduleEngineError("SCHEDULE_HASH_MISMATCH")
    expected_payload_hash = _payload_hash(schedule)
    if schedule.payload_hash != expected_payload_hash:
        raise ScheduleEngineError("SCHEDULE_PAYLOAD_HASH_MISMATCH")


class ScheduleEngineStore:
    def __init__(self, *, root_dir: Path | None = None) -> None:
        self._root_dir = Path(root_dir).resolve() if root_dir is not None else (runtime_paths.root.resolve() / "schedule_engine")
        self._weeks_dir = self._root_dir / "weeks"
        self._locks_dir = self._root_dir / "locks"
        self._lock_file = self._locks_dir / "schedule_engine.lock"

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def _ensure_dirs(self) -> None:
        self._weeks_dir.mkdir(parents=True, exist_ok=True)
        self._locks_dir.mkdir(parents=True, exist_ok=True)

    def _week_path(self, season: int, week: int) -> Path:
        if season <= 0 or week <= 0:
            raise ScheduleEngineError("season/week must be positive integers")
        return self._weeks_dir / f"canonical-weekly-schedule-{season}-{week}.json"

    def _week_lock_path(self, season: int, week: int) -> Path:
        return self._locks_dir / f"canonical-weekly-schedule-{season}-{week}.lock"


def default_schedule_engine_store() -> ScheduleEngineStore:
    return ScheduleEngineStore()


@contextmanager
def _schedule_lock(store: ScheduleEngineStore, *, season: int, week: int):
    with _file_lock(store._week_lock_path(season, week)):
        yield


def _source_rows_from_duckdb(*, duckdb_path: Path, season: int, week: int) -> list[dict[str, Any]]:
    if not duckdb_path.exists():
        raise ScheduleEngineError("SCHEDULE_SOURCE_MISSING")
    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "schedules" not in tables:
            raise ScheduleEngineError("SCHEDULE_SOURCE_TABLE_MISSING")
        columns = {row[1] for row in con.execute("PRAGMA table_info('schedules')").fetchall()}
        has_game_type = "game_type" in columns
        if has_game_type:
            rows = con.execute(
                """
                SELECT game_id, season, week, game_type, gameday, gametime, away_team, home_team
                FROM schedules
                WHERE season = ? AND week = ?
                ORDER BY gameday, gametime, game_id
                """,
                [season, week],
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT game_id, season, week, gameday, gametime, away_team, home_team
                FROM schedules
                WHERE season = ? AND week = ?
                ORDER BY gameday, gametime, game_id
                """,
                [season, week],
            ).fetchall()
    finally:
        con.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        if len(row) == 8:
            game_id, row_season, row_week, game_type, gameday, gametime, away_team, home_team = row
        else:
            game_id, row_season, row_week, gameday, gametime, away_team, home_team = row
            game_type = "REG"
        out.append(
            {
                "game_id": game_id,
                "season": row_season,
                "week": row_week,
                "game_type": game_type,
                "gameday": gameday,
                "gametime": gametime,
                "away_team": away_team,
                "home_team": home_team,
            }
        )
    return out


def _materialize_events(*, rows: list[dict[str, Any]], season: int, week: int) -> tuple[CanonicalScheduleEvent, ...]:
    events: list[CanonicalScheduleEvent] = []
    for row in rows:
        if int(row.get("season")) != season or int(row.get("week")) != week:
            raise ScheduleEngineError("SCHEDULE_SEASON_WEEK_MISMATCH")
        source_event_id = _validate_identifier(str(row.get("game_id") or "").strip(), "game_id")
        game_type = _validate_identifier(str(row.get("game_type") or "REG").strip(), "game_type")
        away_team = normalize_team_id(row.get("away_team"))
        home_team = normalize_team_id(row.get("home_team"))
        if away_team == home_team:
            raise ScheduleEngineError("SCHEDULE_IDENTITY_INVALID")
        gameday = _parse_gameday(row.get("gameday")).isoformat()
        kickoff_utc = _normalize_kickoff_from_eastern(gameday_value=row.get("gameday"), gametime_value=row.get("gametime"))
        identity = build_canonical_event_identity(
            season=season,
            week=week,
            kickoff_utc=kickoff_utc,
            away_team=away_team,
            home_team=home_team,
        )
        events.append(
            CanonicalScheduleEvent(
                source_event_id=source_event_id,
                canonical_event_key=identity.canonical_event_key,
                season=season,
                week=week,
                game_type=game_type,
                gameday=gameday,
                kickoff_utc=identity.kickoff_utc,
                away_team=identity.away_team,
                home_team=identity.home_team,
            )
        )
    return tuple(sorted(events, key=lambda item: (item.kickoff_utc, item.canonical_event_key)))


def load_canonical_weekly_schedule(
    *,
    season: int,
    week: int,
    store: ScheduleEngineStore | None = None,
) -> CanonicalWeeklySchedule | None:
    target_store = store or default_schedule_engine_store()
    path = target_store._week_path(season, week)
    if not path.exists():
        return None
    return _schedule_from_payload(_read_json_file(path, field_name="canonical weekly schedule"))


def materialize_canonical_weekly_schedule(
    *,
    season: int,
    week: int,
    store: ScheduleEngineStore | None = None,
    duckdb_path: Path | None = None,
    source: str = "nflverse_schedules_duckdb",
    source_dataset_version: str | None = None,
) -> dict[str, Any]:
    if season <= 0:
        raise ScheduleEngineError("SEASON_INVALID")
    if week <= 0:
        raise ScheduleEngineError("WEEK_INVALID")
    target_store = store or default_schedule_engine_store()
    target_store._ensure_dirs()
    source_path = Path(duckdb_path).resolve() if duckdb_path is not None else runtime_paths.nfl_model_duckdb.resolve()

    rows = _source_rows_from_duckdb(duckdb_path=source_path, season=season, week=week)
    if not rows:
        raise ScheduleEngineError("SCHEDULE_SOURCE_WEEK_MISSING")

    events = _materialize_events(rows=rows, season=season, week=week)
    schedule_hash = _schedule_hash(events, season=season, week=week)
    schedule = CanonicalWeeklySchedule(
        schedule_version=f"canonical-schedule-v1:{season}:{week}:{schedule_hash[:12]}",
        schedule_hash=schedule_hash,
        season=season,
        week=week,
        event_count=len(events),
        source=source,
        source_version=None,
        source_dataset_version=source_dataset_version,
        source_content_sha256=None,
        source_manifest_identity=None,
        generated_at=_utc_now_iso(),
        payload_hash="",
        events=events,
    )
    schedule = CanonicalWeeklySchedule(
        schedule_version=schedule.schedule_version,
        schedule_hash=schedule.schedule_hash,
        season=schedule.season,
        week=schedule.week,
        event_count=schedule.event_count,
        source=schedule.source,
        source_version=schedule.source_version,
        source_dataset_version=schedule.source_dataset_version,
        source_content_sha256=schedule.source_content_sha256,
        source_manifest_identity=schedule.source_manifest_identity,
        generated_at=schedule.generated_at,
        payload_hash=_payload_hash(schedule),
        events=schedule.events,
    )
    _validate_schedule(schedule)

    with _schedule_lock(target_store, season=season, week=week):
        existing = load_canonical_weekly_schedule(season=season, week=week, store=target_store)
        if existing is not None:
            if existing.schedule_hash == schedule.schedule_hash and existing.payload_hash == schedule.payload_hash:
                return {"status": "ALREADY_MATERIALIZED", "schedule": asdict(existing)}
            raise ScheduleEngineError("SCHEDULE_CONFLICT")

        path = target_store._week_path(season, week)
        _atomic_write_text(path, _canonical_json(asdict(schedule)))
        persisted = load_canonical_weekly_schedule(season=season, week=week, store=target_store)
        if persisted is None:
            raise ScheduleEngineError("SCHEDULE_READBACK_MISSING")
        if persisted.schedule_hash != schedule.schedule_hash or persisted.schedule_version != schedule.schedule_version:
            raise ScheduleEngineError("SCHEDULE_READBACK_VERIFICATION_FAILED")
        return {"status": "MATERIALIZED", "schedule": asdict(persisted)}