from __future__ import annotations

import json
import socket
import re
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
import urllib.error as urllib_error
import urllib.request as urllib_request

import certifi

from app.runtime_paths import runtime_paths


PERSONNEL_AVAILABILITY_STATES = {
    "AVAILABLE",
    "QUESTIONABLE",
    "DOUBTFUL",
    "OUT",
    "IR",
    "PUP",
    "SUSPENDED",
    "UNKNOWN",
}

PERSONNEL_POSITION_GROUPS = {
    "QB": "QB",
    "RB": "RB",
    "FB": "RB",
    "WR": "WR",
    "TE": "TE",
    "T": "OL",
    "OT": "OL",
    "G": "OL",
    "OG": "OL",
    "C": "OL",
    "OL": "OL",
    "LT": "OL",
    "RT": "OL",
    "EDGE": "EDGE",
    "DE": "EDGE",
    "DL": "DL",
    "DT": "DL",
    "NT": "DL",
    "LB": "LB",
    "ILB": "LB",
    "MLB": "LB",
    "OLB": "LB",
    "CB": "CB",
    "DB": "CB",
    "S": "S",
    "FS": "S",
    "SS": "S",
    "K": "K/P",
    "P": "K/P",
}

TEAM_ALIASES = {
    "LA": "LAR",
    "L.A.": "LAR",
    "L.A. RAMS": "LAR",
    "LA RAMS": "LAR",
    "LOS ANGELES RAMS": "LAR",
    "LOS ANGELES CHARGERS": "LAC",
    "SAN DIEGO CHARGERS": "LAC",
    "WASHINGTON": "WAS",
    "WASHINGTON COMMANDERS": "WAS",
    "WASHINGTON REDSKINS": "WAS",
    "WSH": "WAS",
    "JAX": "JAX",
    "JAC": "JAX",
    "ARIZONA CARDINALS": "ARI",
    "ATLANTA FALCONS": "ATL",
    "BALTIMORE RAVENS": "BAL",
    "BUFFALO BILLS": "BUF",
    "CAROLINA PANTHERS": "CAR",
    "CHICAGO BEARS": "CHI",
    "CINCINNATI BENGALS": "CIN",
    "CLEVELAND BROWNS": "CLE",
    "DALLAS COWBOYS": "DAL",
    "DENVER BRONCOS": "DEN",
    "DETROIT LIONS": "DET",
    "GREEN BAY PACKERS": "GB",
    "HOUSTON TEXANS": "HOU",
    "INDIANAPOLIS COLTS": "IND",
    "KANSAS CITY CHIEFS": "KC",
    "LAS VEGAS RAIDERS": "LV",
    "MIAMI DOLPHINS": "MIA",
    "MINNESOTA VIKINGS": "MIN",
    "NEW ENGLAND PATRIOTS": "NE",
    "NEW ORLEANS SAINTS": "NO",
    "NEW YORK GIANTS": "NYG",
    "NEW YORK JETS": "NYJ",
    "PHILADELPHIA EAGLES": "PHI",
    "PITTSBURGH STEELERS": "PIT",
    "SAN FRANCISCO 49ERS": "SF",
    "SEATTLE SEAHAWKS": "SEA",
    "TAMPA BAY BUCCANEERS": "TB",
    "TENNESSEE TITANS": "TEN",
    "49ERS": "SF",
    "BEARS": "CHI",
    "BENGALS": "CIN",
    "BILLS": "BUF",
    "BRONCOS": "DEN",
    "BROWNS": "CLE",
    "BUCCANEERS": "TB",
    "CARDINALS": "ARI",
    "CHARGERS": "LAC",
    "CHIEFS": "KC",
    "COLTS": "IND",
    "COMMANDERS": "WAS",
    "COWBOYS": "DAL",
    "DOLPHINS": "MIA",
    "EAGLES": "PHI",
    "FALCONS": "ATL",
    "GIANTS": "NYG",
    "JAGUARS": "JAX",
    "JETS": "NYJ",
    "LIONS": "DET",
    "PACKERS": "GB",
    "PANTHERS": "CAR",
    "PATRIOTS": "NE",
    "RAIDERS": "LV",
    "RAMS": "LAR",
    "RAVENS": "BAL",
    "SAINTS": "NO",
    "SEAHAWKS": "SEA",
    "STEELERS": "PIT",
    "TEXANS": "HOU",
    "TITANS": "TEN",
    "VIKINGS": "MIN",
}

CANONICAL_TEAM_IDS = {
    "ARI",
    "ATL",
    "BAL",
    "BUF",
    "CAR",
    "CHI",
    "CIN",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GB",
    "HOU",
    "IND",
    "JAX",
    "KC",
    "LAC",
    "LAR",
    "LV",
    "MIA",
    "MIN",
    "NE",
    "NO",
    "NYG",
    "NYJ",
    "PHI",
    "PIT",
    "SEA",
    "SF",
    "TB",
    "TEN",
    "WAS",
}

SOURCE_PARSER_VERSION = "personnel_ingestion_v1"
DEFAULT_PERSONNEL_SNAPSHOT_DIR = runtime_paths.root / "data" / "personnel_snapshots"
DEFAULT_PERSONNEL_FETCH_EVIDENCE_DIR = runtime_paths.root / "data" / "personnel_fetches"
DEFAULT_NFL_INJURY_SOURCE_URL = "https://www.nfl.com/injuries/"
APPROVED_NFL_INJURY_SOURCE_URL = DEFAULT_NFL_INJURY_SOURCE_URL
DEFAULT_NFL_INJURY_TIMEOUT_SECONDS = 30
DEFAULT_NFL_INJURY_USER_AGENT = (
    "SIA/1.0 (+https://www.nfl.com/injuries; personnel ingestion)"
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_https_nfl_injury_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https":
        return False
    hostname = (parsed.hostname or "").lower()
    if hostname not in {"nfl.com", "www.nfl.com"}:
        return False
    path = parsed.path.rstrip("/")
    return path == "/injuries"


def _canonicalize_nfl_injury_url(value: str | None) -> str:
    candidate = _normalized_text(value) or DEFAULT_NFL_INJURY_SOURCE_URL
    if not _is_https_nfl_injury_url(candidate):
        raise PersonnelRetrievalError(f"PERSONNEL_SOURCE_URL_REJECTED: {candidate!r}")
    return DEFAULT_NFL_INJURY_SOURCE_URL


class PersonnelRetrievalError(ValueError):
    pass


@dataclass(frozen=True)
class NFLInjuryFetchResult:
    body: bytes
    source_url: str
    final_url: str
    http_status: int
    content_type: str | None
    source_timestamp: str | None
    retrieved_at: str


@dataclass(frozen=True)
class NFLInjuryFetchArtifact:
    metadata_path: Path
    body_path: Path
    body_bytes: int
    content_type: str | None


@dataclass(frozen=True)
class NFLInjuryFetchStage:
    fetch_result: NFLInjuryFetchResult
    artifact: NFLInjuryFetchArtifact


def fetch_nfl_injury_source(
    source_url: str = DEFAULT_NFL_INJURY_SOURCE_URL,
    *,
    timeout_seconds: int = DEFAULT_NFL_INJURY_TIMEOUT_SECONDS,
    user_agent: str = DEFAULT_NFL_INJURY_USER_AGENT,
) -> NFLInjuryFetchResult:
    approved_source_url = _canonicalize_nfl_injury_url(source_url)
    request = urllib_request.Request(
        approved_source_url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    retrieved_at = _utc_now_iso()

    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds, context=ssl_context) as response:
            http_status = int(getattr(response, "status", None) or response.getcode() or 0)
            body = response.read()
            final_url = str(response.geturl() or approved_source_url)
            headers = getattr(response, "headers", None)
            source_timestamp = None
            content_type = None
            if headers is not None:
                source_timestamp = headers.get("Last-Modified") or headers.get("Date")
                content_type = headers.get("Content-Type")
    except urllib_error.HTTPError as exc:
        raise PersonnelRetrievalError(f"PERSONNEL_SOURCE_HTTP_ERROR: {exc.code}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise PersonnelRetrievalError("PERSONNEL_SOURCE_TIMEOUT") from exc
    except urllib_error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise PersonnelRetrievalError("PERSONNEL_SOURCE_TIMEOUT") from exc
        if isinstance(reason, ssl.SSLError):
            raise PersonnelRetrievalError(f"PERSONNEL_SOURCE_TLS_ERROR: {reason}") from exc
        raise PersonnelRetrievalError(f"PERSONNEL_SOURCE_NETWORK_ERROR: {exc.reason!r}") from exc
    except ssl.SSLError as exc:
        raise PersonnelRetrievalError(f"PERSONNEL_SOURCE_TLS_ERROR: {exc}") from exc

    if http_status < 200 or http_status >= 300:
        raise PersonnelRetrievalError(f"PERSONNEL_SOURCE_HTTP_STATUS_{http_status}")
    if not body:
        raise PersonnelRetrievalError("PERSONNEL_SOURCE_EMPTY_RESPONSE")
    if not _is_https_nfl_injury_url(final_url):
        raise PersonnelRetrievalError(f"PERSONNEL_SOURCE_FINAL_URL_REJECTED: {final_url!r}")

    return NFLInjuryFetchResult(
        body=body,
        source_url=approved_source_url,
        final_url=final_url,
        http_status=http_status,
        content_type=content_type,
        source_timestamp=source_timestamp,
        retrieved_at=retrieved_at,
    )


def _persist_nfl_injury_fetch_artifact(
    *,
    season: int,
    week: int,
    fetch_result: NFLInjuryFetchResult,
    evidence_root: Path | None = None,
) -> NFLInjuryFetchArtifact:
    root = Path(evidence_root or DEFAULT_PERSONNEL_FETCH_EVIDENCE_DIR)
    target_dir = root / f"season={int(season)}" / f"week={int(week)}"
    target_dir.mkdir(parents=True, exist_ok=True)

    response_hash = sha256(fetch_result.body).hexdigest()[:12]
    stamp = fetch_result.retrieved_at.replace(":", "").replace("-", "")
    base_name = f"fetch-{stamp}-{response_hash}"
    body_path = target_dir / f"{base_name}.body.html"
    metadata_path = target_dir / f"{base_name}.json"

    body_path.write_bytes(fetch_result.body)
    metadata_payload = {
        "source_url": fetch_result.source_url,
        "final_url": fetch_result.final_url,
        "http_status": int(fetch_result.http_status),
        "content_type": fetch_result.content_type,
        "source_timestamp": fetch_result.source_timestamp,
        "retrieved_at": fetch_result.retrieved_at,
        "body_bytes": len(fetch_result.body),
        "body_path": str(body_path),
        "sha256": sha256(fetch_result.body).hexdigest(),
    }
    metadata_path.write_text(json.dumps(metadata_payload, indent=2, sort_keys=True), encoding="utf-8")
    return NFLInjuryFetchArtifact(
        metadata_path=metadata_path,
        body_path=body_path,
        body_bytes=len(fetch_result.body),
        content_type=fetch_result.content_type,
    )


def fetch_and_store_nfl_injury_source(
    *,
    season: int,
    week: int,
    source_url: str = DEFAULT_NFL_INJURY_SOURCE_URL,
    timeout_seconds: int = DEFAULT_NFL_INJURY_TIMEOUT_SECONDS,
    evidence_root: Path | None = None,
) -> NFLInjuryFetchStage:
    fetch_result = fetch_nfl_injury_source(source_url=source_url, timeout_seconds=timeout_seconds)
    artifact = _persist_nfl_injury_fetch_artifact(
        season=season,
        week=week,
        fetch_result=fetch_result,
        evidence_root=evidence_root,
    )
    return NFLInjuryFetchStage(fetch_result=fetch_result, artifact=artifact)


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_team_id(value: Any) -> str:
    text = _normalized_text(value).upper()
    if not text:
        return ""
    normalized = TEAM_ALIASES.get(text, text)
    if normalized in CANONICAL_TEAM_IDS:
        return normalized
    return ""


def normalize_position_group(position: Any) -> str:
    text = _normalized_text(position).upper()
    return PERSONNEL_POSITION_GROUPS.get(text, text or "UNKNOWN")


def normalize_availability(*, game_status: Any, injury_description: Any = None, practice_status: Any = None) -> str:
    status = _normalized_text(game_status).upper()
    if not status:
        return "UNKNOWN"

    if status in {"QUESTIONABLE", "Q"}:
        return "QUESTIONABLE"
    if status in {"DOUBTFUL", "D"}:
        return "DOUBTFUL"
    if status in {"OUT", "O"}:
        return "OUT"
    if status in {"IR", "INJURED RESERVE"}:
        return "IR"
    if status in {"PUP", "PUP-NFI", "PUP-NFI/RESERVE", "PUP-NFI/ACTIVE"}:
        return "PUP"
    if status in {"SUSPENDED", "SUS"}:
        return "SUSPENDED"
    if status in {"AVAILABLE", "ACTIVE", "PROBABLE"}:
        return "AVAILABLE"
    if status in {"UNKNOWN", "N/A", "NA"}:
        return "UNKNOWN"

    # Do not infer beyond explicit source evidence.
    return "UNKNOWN"


@dataclass(frozen=True)
class PersonnelRecord:
    season: int
    week: int
    team: str
    player_name: str
    position: str
    injury_description: str
    practice_status: str
    game_status: str
    source: str
    source_url: str
    source_timestamp: str | None
    retrieved_at: str
    normalized_availability: str
    position_group: str
    raw_team: str = ""

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "week": self.week,
            "team": self.team,
            "player_name": self.player_name,
            "position": self.position,
            "injury_description": self.injury_description,
            "practice_status": self.practice_status,
            "game_status": self.game_status,
            "source": self.source,
            "source_url": self.source_url,
            "source_timestamp": self.source_timestamp,
            "retrieved_at": self.retrieved_at,
            "normalized_availability": self.normalized_availability,
            "position_group": self.position_group,
            "raw_team": self.raw_team,
        }


@dataclass(frozen=True)
class PersonnelStarterEvidence:
    team: str
    player: str
    role: str
    effective_game: str
    source: str
    source_url: str
    published_at: str | None
    retrieved_at: str
    verification_status: str = "VERIFIED"

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "player": self.player,
            "role": self.role,
            "effective_game": self.effective_game,
            "source": self.source,
            "source_url": self.source_url,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
            "verification_status": self.verification_status,
        }


@dataclass(frozen=True)
class PersonnelSnapshot:
    personnel_snapshot_id: str
    personnel_snapshot_hash: str
    season: int
    week: int
    created_at: str
    source_version: str
    source_timestamp: str | None
    source_url: str
    records: tuple[PersonnelRecord, ...]
    starter_evidence: tuple[PersonnelStarterEvidence, ...] = field(default_factory=tuple)

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "week": self.week,
            "source_version": self.source_version,
            "source_timestamp": self.source_timestamp,
            "source_url": self.source_url,
            "records": [record.to_canonical_dict() for record in self.records],
            "starter_evidence": [item.to_canonical_dict() for item in self.starter_evidence],
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "personnel_snapshot_id": self.personnel_snapshot_id,
            "personnel_snapshot_hash": self.personnel_snapshot_hash,
            "season": self.season,
            "week": self.week,
            "created_at": self.created_at,
            "source_version": self.source_version,
            "source_timestamp": self.source_timestamp,
            "source_url": self.source_url,
            "records": [record.to_canonical_dict() for record in self.records],
            "starter_evidence": [item.to_canonical_dict() for item in self.starter_evidence],
        }


class PersonnelIngestionError(ValueError):
    pass


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[dict[str, Any]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_cells: list[str] = []
        self._current_cell_text: list[str] = []
        self._current_headers: list[str] = []
        self._capture_header = False
        self._in_heading = False
        self._heading_text: list[str] = []
        self._in_section_subtitle = False
        self._section_subtitle_text: list[str] = []
        self._latest_team_heading = ""
        self._heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6", "caption"}

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self._in_table = True
            self._current_headers = []
            self.tables.append({"headers": [], "rows": [], "team_heading": self._latest_team_heading})
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_cells = []
        elif self._in_row and tag in {"th", "td"}:
            self._in_cell = True
            self._current_cell_text = []
            self._capture_header = tag == "th" and not self._current_headers
        elif tag in self._heading_tags:
            self._in_heading = True
            self._heading_text = []
        elif tag == "div":
            classes = str(attrs_dict.get("class") or "")
            if "d3-o-section-sub-title" in classes:
                self._in_section_subtitle = True
                self._section_subtitle_text = []

    def handle_endtag(self, tag: str):
        if tag in {"th", "td"} and self._in_cell:
            text = " ".join(part.strip() for part in self._current_cell_text if part.strip()).strip()
            self._current_cells.append(text)
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            current = self.tables[-1]
            if self._current_cells:
                if self._capture_header and not current["headers"]:
                    current["headers"] = list(self._current_cells)
                    self._current_headers = list(self._current_cells)
                else:
                    current["rows"].append(list(self._current_cells))
            self._in_row = False
            self._current_cells = []
        elif tag == "table":
            self._in_table = False
        elif tag in self._heading_tags and self._in_heading:
            heading = " ".join(part.strip() for part in self._heading_text if part.strip()).strip()
            if heading and normalize_team_id(heading):
                self._latest_team_heading = heading
            self._in_heading = False
            self._heading_text = []
        elif tag == "div" and self._in_section_subtitle:
            heading = " ".join(part.strip() for part in self._section_subtitle_text if part.strip()).strip()
            if heading and normalize_team_id(heading):
                self._latest_team_heading = heading
            self._in_section_subtitle = False
            self._section_subtitle_text = []

    def handle_data(self, data: str):
        if self._in_cell:
            self._current_cell_text.append(data)
        if self._in_heading:
            self._heading_text.append(data)
        if self._in_section_subtitle:
            self._section_subtitle_text.append(data)


def _parse_source_payload(source_payload: bytes | str | dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(source_payload, dict):
        return _extract_json_records(source_payload), None

    if isinstance(source_payload, bytes):
        text = source_payload.decode("utf-8", errors="replace")
    else:
        text = str(source_payload)

    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _extract_json_records(json.loads(text)), None
    return _extract_html_records(text), None


def _extract_json_records(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    for key in ("injuries", "players", "items", "data", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_html_records(text: str) -> list[dict[str, Any]]:
    parser = _TableParser()
    parser.feed(text)
    rows: list[dict[str, Any]] = []

    def _normalize_header(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

    def _team_keys() -> tuple[str, ...]:
        return ("team", "club", "team_name", "teamname", "abbreviation", "abbr")

    def _heading_team_candidate(row_map: dict[str, Any]) -> str:
        team_from_field = _get_value(row_map, *_team_keys())
        candidate = _normalized_text(team_from_field)
        if candidate and normalize_team_id(candidate):
            return candidate

        values = [
            _normalized_text(value)
            for value in row_map.values()
            if _normalized_text(value)
        ]
        if len(values) == 1 and normalize_team_id(values[0]):
            return values[0]
        return ""

    def _player_name(row_map: dict[str, Any]) -> str:
        return _normalized_text(_get_value(row_map, "player_name", "player", "name", "displayname", "athlete_name"))

    def _looks_like_player_row(row_map: dict[str, Any]) -> bool:
        player_name = _player_name(row_map)
        if not player_name:
            return False
        upper_name = player_name.upper()
        if upper_name in {"PLAYER", "NAME", "RESERVE/INJURED", "INJURED RESERVE", "RESERVE"}:
            return False
        position = _normalized_text(_get_value(row_map, "position", "pos", "position_abbreviation", "positionabbreviation"))
        injury = _normalized_text(_get_value(row_map, "injury_description", "injuries", "injury", "injurydetail", "description", "detail", "notes"))
        practice = _normalized_text(_get_value(row_map, "practice_status", "practicestatus", "practice", "participation_status"))
        game_status = _normalized_text(_get_value(row_map, "game_status", "status", "injury_status", "gamestatus", "availability"))
        if not any([position, injury, practice, game_status]):
            return False
        return True

    team_context = ""

    for table in parser.tables:
        table_heading = _normalized_text(table.get("team_heading"))
        if table_heading and normalize_team_id(table_heading):
            team_context = table_heading
        headers = [_normalize_header(str(header)) for header in table.get("headers", [])]
        for row in table.get("rows", []):
            if not row:
                continue
            if headers and len(headers) == len(row):
                mapped = {headers[idx]: row[idx] for idx in range(len(headers))}
            else:
                mapped = {str(idx): value for idx, value in enumerate(row)}

            heading_team = _heading_team_candidate(mapped)
            if heading_team and not _looks_like_player_row(mapped):
                team_context = heading_team
                continue

            if not _looks_like_player_row(mapped):
                continue

            current_team = _normalized_text(_get_value(mapped, *_team_keys()))
            if not current_team and team_context:
                mapped["team"] = team_context
            rows.append(mapped)
    return rows


def _get_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record.get(key) not in (None, ""):
            return record.get(key)
    return None


def _canonical_record_seed(record: PersonnelRecord) -> dict[str, Any]:
    return {
        "season": record.season,
        "week": record.week,
        "team": record.team,
        "player_name": record.player_name,
        "position": record.position,
        "injury_description": record.injury_description,
        "practice_status": record.practice_status,
        "game_status": record.game_status,
        "source": record.source,
        "source_url": record.source_url,
        "source_timestamp": record.source_timestamp,
        "normalized_availability": record.normalized_availability,
        "position_group": record.position_group,
        "raw_team": record.raw_team,
    }


def _hash_payload(payload: dict[str, Any]) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _normalize_record(
    record: dict[str, Any],
    *,
    season: int,
    week: int,
    source: str,
    source_url: str,
    source_timestamp: str | None,
    retrieved_at: str,
) -> PersonnelRecord:
    team_raw = _get_value(record, "team", "club", "team_name", "teamName", "abbreviation", "abbr")
    team = normalize_team_id(team_raw)
    if not team:
        raise PersonnelIngestionError(f"Unknown team in personnel record: {team_raw!r}")

    player_name = _normalized_text(_get_value(record, "player_name", "player", "name", "displayName", "athlete_name"))
    if not player_name:
        raise PersonnelIngestionError("Personnel record missing player name")

    position = _normalized_text(_get_value(record, "position", "pos", "position_abbreviation", "positionAbbreviation")).upper() or "UNKNOWN"
    injury_description = _normalized_text(_get_value(record, "injury_description", "injuries", "injury", "injuryDetail", "description", "detail", "notes"))
    practice_status = _normalized_text(_get_value(record, "practice_status", "practiceStatus", "practice", "participation_status")).title() or "Unknown"
    game_status = _normalized_text(_get_value(record, "game_status", "status", "injury_status", "gameStatus", "availability")).title() or "Unknown"
    normalized_availability = normalize_availability(game_status=game_status, injury_description=injury_description, practice_status=practice_status)

    return PersonnelRecord(
        season=int(season),
        week=int(week),
        team=team,
        player_name=player_name,
        position=position,
        injury_description=injury_description,
        practice_status=practice_status,
        game_status=game_status,
        source=source,
        source_url=source_url,
        source_timestamp=source_timestamp,
        retrieved_at=retrieved_at,
        normalized_availability=normalized_availability,
        position_group=normalize_position_group(position),
        raw_team=_normalized_text(team_raw),
    )


def _canonicalize_records(records: Iterable[PersonnelRecord]) -> tuple[PersonnelRecord, ...]:
    ordered = sorted(records, key=lambda rec: (rec.team, rec.player_name, rec.position, rec.game_status, rec.practice_status, rec.injury_description))
    conflict_keyed: dict[tuple[str, str], PersonnelRecord] = {}
    for record in ordered:
        key = (record.team, record.player_name)
        existing = conflict_keyed.get(key)
        if existing is None:
            conflict_keyed[key] = record
            continue
        if existing.to_canonical_dict() != record.to_canonical_dict():
            raise PersonnelIngestionError(
                f"Conflicting personnel status for player {record.player_name!r} on team {record.team!r}"
            )
    return tuple(conflict_keyed[key] for key in sorted(conflict_keyed))


def _canonicalize_starter_evidence(records: Iterable[PersonnelStarterEvidence]) -> tuple[PersonnelStarterEvidence, ...]:
    ordered = sorted(records, key=lambda item: (item.team, item.player, item.effective_game, item.source))
    conflict_keyed: dict[tuple[str, str, str], PersonnelStarterEvidence] = {}
    for item in ordered:
        key = (item.team, item.player, item.effective_game)
        existing = conflict_keyed.get(key)
        if existing is None:
            conflict_keyed[key] = item
            continue
        if existing.to_canonical_dict() != item.to_canonical_dict():
            raise PersonnelIngestionError(
                f"Conflicting starter evidence for player {item.player!r} on team {item.team!r}"
            )
    return tuple(conflict_keyed[key] for key in sorted(conflict_keyed))


def build_personnel_snapshot(
    *,
    season: int,
    week: int,
    source_url: str,
    source_payload: bytes | str | dict[str, Any],
    source_timestamp: str | None = None,
    retrieved_at: str | None = None,
    source: str = "nfl.com/injuries",
    source_version: str | None = None,
    starter_evidence: Iterable[dict[str, Any] | PersonnelStarterEvidence] | None = None,
) -> PersonnelSnapshot:
    resolved_retrieved_at = (retrieved_at or _utc_now_iso()).replace("+00:00", "Z")
    try:
        raw_records, _ = _parse_source_payload(source_payload)
        records = [
            _normalize_record(
                record,
                season=season,
                week=week,
                source=source,
                source_url=source_url,
                source_timestamp=source_timestamp,
                retrieved_at=resolved_retrieved_at,
            )
            for record in raw_records
        ]
        canonical_records = _canonicalize_records(records)
    except PersonnelIngestionError:
        raise
    except Exception as exc:
        raise PersonnelIngestionError(f"PERSONNEL_SOURCE_PARSE_FAILED: {exc}") from exc

    evidence_items: list[PersonnelStarterEvidence] = []
    for item in starter_evidence or []:
        if isinstance(item, PersonnelStarterEvidence):
            evidence_items.append(item)
            continue
        team = normalize_team_id(_get_value(item, "team", "club", "team_name", "teamName"))
        player = _normalized_text(_get_value(item, "player", "player_name", "name", "displayName"))
        role = _normalized_text(_get_value(item, "role", "position", "starter_role")).upper() or "STARTING_QB"
        effective_game = _normalized_text(_get_value(item, "effective_game", "effectiveGame", "game_id", "event_id"))
        source_item = _normalized_text(_get_value(item, "source", "provider")) or source
        source_url_item = _normalized_text(_get_value(item, "source_url", "sourceUrl")) or source_url
        published_at = _normalized_text(_get_value(item, "published_at", "publishedAt")) or None
        verification_status = _normalized_text(_get_value(item, "verification_status", "status")) or "VERIFIED"
        evidence_items.append(
            PersonnelStarterEvidence(
                team=team,
                player=player,
                role=role,
                effective_game=effective_game,
                source=source_item,
                source_url=source_url_item,
                published_at=published_at,
                retrieved_at=resolved_retrieved_at,
                verification_status=verification_status.upper(),
            )
        )

    canonical_evidence = _canonicalize_starter_evidence(evidence_items)
    source_version_value = source_version or f"{source}:{SOURCE_PARSER_VERSION}"

    canonical_payload = {
        "season": int(season),
        "week": int(week),
        "source_version": source_version_value,
        "source_timestamp": source_timestamp,
        "source_url": source_url,
        "records": [_canonical_record_seed(record) for record in canonical_records],
        "starter_evidence": [item.to_canonical_dict() for item in canonical_evidence],
    }
    personnel_snapshot_hash = _hash_payload(canonical_payload)
    personnel_snapshot_id = f"personnel-{personnel_snapshot_hash[:16]}"

    return PersonnelSnapshot(
        personnel_snapshot_id=personnel_snapshot_id,
        personnel_snapshot_hash=personnel_snapshot_hash,
        season=int(season),
        week=int(week),
        created_at=resolved_retrieved_at,
        source_version=source_version_value,
        source_timestamp=source_timestamp,
        source_url=source_url,
        records=canonical_records,
        starter_evidence=canonical_evidence,
    )


def ingest_nfl_personnel_snapshot(
    *,
    season: int,
    week: int,
    source_url: str = DEFAULT_NFL_INJURY_SOURCE_URL,
    source_version: str | None = None,
    starter_evidence: Iterable[dict[str, Any] | PersonnelStarterEvidence] | None = None,
    store_root: Path | None = None,
    timeout_seconds: int = DEFAULT_NFL_INJURY_TIMEOUT_SECONDS,
    fetch_evidence_root: Path | None = None,
) -> tuple[PersonnelSnapshot, NFLInjuryFetchResult, Path, NFLInjuryFetchArtifact]:
    fetch_stage = fetch_and_store_nfl_injury_source(
        season=season,
        week=week,
        source_url=source_url,
        timeout_seconds=timeout_seconds,
        evidence_root=fetch_evidence_root,
    )
    fetch_result = fetch_stage.fetch_result
    snapshot = build_personnel_snapshot(
        season=season,
        week=week,
        source_url=fetch_result.source_url,
        source_payload=fetch_result.body,
        source_timestamp=fetch_result.source_timestamp,
        retrieved_at=fetch_result.retrieved_at,
        source_version=source_version,
        starter_evidence=starter_evidence,
    )
    snapshot_path = write_personnel_snapshot(snapshot, store_root=store_root)
    return snapshot, fetch_result, snapshot_path, fetch_stage.artifact


def _snapshot_path(snapshot: PersonnelSnapshot, *, store_root: Path | None = None) -> Path:
    root = store_root or DEFAULT_PERSONNEL_SNAPSHOT_DIR
    return Path(root) / f"season={snapshot.season}" / f"week={snapshot.week}" / f"{snapshot.personnel_snapshot_id}.json"


def write_personnel_snapshot(snapshot: PersonnelSnapshot, *, store_root: Path | None = None) -> Path:
    path = _snapshot_path(snapshot, store_root=store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = load_personnel_snapshot(snapshot.personnel_snapshot_id, store_root=store_root)
        if existing is not None and existing.personnel_snapshot_hash != snapshot.personnel_snapshot_hash:
            raise PersonnelIngestionError("PERSONNEL_SNAPSHOT_HASH_CONFLICT")
        return path
    path.write_text(json.dumps(snapshot.to_payload(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_personnel_snapshot(snapshot_id: str, *, store_root: Path | None = None) -> PersonnelSnapshot | None:
    root = store_root or DEFAULT_PERSONNEL_SNAPSHOT_DIR
    root_path = Path(root)
    if not snapshot_id or not root_path.exists():
        return None
    matches = list(root_path.glob(f"season=*/week=*/{snapshot_id}.json"))
    if not matches:
        return None
    payload = json.loads(matches[0].read_text(encoding="utf-8"))
    return _snapshot_from_payload(payload)


def load_latest_personnel_snapshot(*, season: int, week: int, store_root: Path | None = None) -> PersonnelSnapshot | None:
    root = Path(store_root or DEFAULT_PERSONNEL_SNAPSHOT_DIR) / f"season={int(season)}" / f"week={int(week)}"
    if not root.exists():
        return None
    candidates = sorted(root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    return _snapshot_from_payload(json.loads(candidates[0].read_text(encoding="utf-8")))


def _snapshot_from_payload(payload: dict[str, Any]) -> PersonnelSnapshot:
    records = tuple(
        PersonnelRecord(
            season=int(item["season"]),
            week=int(item["week"]),
            team=str(item["team"]),
            player_name=str(item["player_name"]),
            position=str(item["position"]),
            injury_description=str(item.get("injury_description") or ""),
            practice_status=str(item.get("practice_status") or "Unknown"),
            game_status=str(item.get("game_status") or "Unknown"),
            source=str(item.get("source") or "nfl.com/injuries"),
            source_url=str(item.get("source_url") or ""),
            source_timestamp=item.get("source_timestamp"),
            retrieved_at=str(item.get("retrieved_at") or ""),
            normalized_availability=str(item.get("normalized_availability") or "UNKNOWN"),
            position_group=str(item.get("position_group") or normalize_position_group(item.get("position"))),
            raw_team=str(item.get("raw_team") or ""),
        )
        for item in payload.get("records", [])
    )
    evidence = tuple(
        PersonnelStarterEvidence(
            team=str(item["team"]),
            player=str(item["player"]),
            role=str(item.get("role") or "STARTING_QB"),
            effective_game=str(item.get("effective_game") or ""),
            source=str(item.get("source") or "nfl.com/injuries"),
            source_url=str(item.get("source_url") or ""),
            published_at=item.get("published_at"),
            retrieved_at=str(item.get("retrieved_at") or ""),
            verification_status=str(item.get("verification_status") or "VERIFIED"),
        )
        for item in payload.get("starter_evidence", [])
    )
    return PersonnelSnapshot(
        personnel_snapshot_id=str(payload["personnel_snapshot_id"]),
        personnel_snapshot_hash=str(payload["personnel_snapshot_hash"]),
        season=int(payload["season"]),
        week=int(payload["week"]),
        created_at=str(payload["created_at"]),
        source_version=str(payload["source_version"]),
        source_timestamp=payload.get("source_timestamp"),
        source_url=str(payload["source_url"]),
        records=records,
        starter_evidence=evidence,
    )


def build_starting_qb_evidence(
    *,
    team: str,
    player: str,
    effective_game: str,
    source: str,
    source_url: str,
    published_at: str | None,
    retrieved_at: str | None = None,
) -> PersonnelStarterEvidence:
    return PersonnelStarterEvidence(
        team=normalize_team_id(team),
        player=_normalized_text(player),
        role="STARTING_QB",
        effective_game=_normalized_text(effective_game),
        source=_normalized_text(source),
        source_url=_normalized_text(source_url),
        published_at=_normalized_text(published_at) or None,
        retrieved_at=(retrieved_at or _utc_now_iso()).replace("+00:00", "Z"),
        verification_status="VERIFIED",
    )
