from __future__ import annotations

import json
import socket
import ssl
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import certifi
import pytest

from app.services.personnel_authority import load_personnel_authority_lookup
from app.services.personnel_ingestion import (
    APPROVED_NFL_INJURY_SOURCE_URL,
    DEFAULT_NFL_INJURY_SOURCE_URL,
    NFLInjuryFetchResult,
    PersonnelIngestionError,
    PersonnelRetrievalError,
    build_personnel_snapshot,
    fetch_and_store_nfl_injury_source,
    fetch_nfl_injury_source,
    ingest_nfl_personnel_snapshot,
    load_latest_personnel_snapshot,
    normalize_team_id,
    write_personnel_snapshot,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "personnel"


def _fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class _FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _FakeResponse:
    def __init__(self, *, body: bytes, status: int, final_url: str, headers: dict[str, str] | None = None):
        self._body = body
        self.status = status
        self._final_url = final_url
        self.headers = _FakeHeaders(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body

    def geturl(self):
        return self._final_url

    def getcode(self):
        return self.status


def test_fetch_nfl_injury_source_uses_certifi_and_verified_context(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}
    original_create_default_context = ssl.create_default_context

    def create_default_context_spy(*args, **kwargs):
        observed["cafile"] = kwargs.get("cafile")
        context = original_create_default_context(*args, **kwargs)
        observed["context"] = context
        return context

    def fake_urlopen(request, *, timeout=None, context=None):
        observed["request_url"] = request.full_url
        observed["timeout"] = timeout
        observed["context_passed"] = context
        return _FakeResponse(
            body=b"<html>injuries</html>",
            status=200,
            final_url=APPROVED_NFL_INJURY_SOURCE_URL,
            headers={"Last-Modified": "Wed, 25 Sep 2026 17:05:00 GMT"},
        )

    monkeypatch.setattr("app.services.personnel_ingestion.ssl.create_default_context", create_default_context_spy)
    monkeypatch.setattr("app.services.personnel_ingestion.urllib_request.urlopen", fake_urlopen)

    result = fetch_nfl_injury_source()

    assert observed["cafile"] == certifi.where()
    assert isinstance(observed["context"], ssl.SSLContext)
    assert observed["context"].verify_mode == ssl.CERT_REQUIRED
    assert observed["context"].check_hostname is True
    assert observed["context_passed"] is observed["context"]
    assert observed["request_url"] == APPROVED_NFL_INJURY_SOURCE_URL
    assert observed["timeout"] == 30
    assert result.body == b"<html>injuries</html>"
    assert result.source_url == APPROVED_NFL_INJURY_SOURCE_URL
    assert result.final_url == APPROVED_NFL_INJURY_SOURCE_URL
    assert result.http_status == 200
    assert result.source_timestamp == "Wed, 25 Sep 2026 17:05:00 GMT"
    assert result.retrieved_at


def test_fetch_nfl_injury_source_rejects_non_https_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        raise AssertionError("urlopen should not be reached for rejected URLs")

    monkeypatch.setattr("app.services.personnel_ingestion.urllib_request.urlopen", fake_urlopen)

    with pytest.raises(PersonnelRetrievalError, match="PERSONNEL_SOURCE_URL_REJECTED"):
        fetch_nfl_injury_source("http://www.nfl.com/injuries/")

    assert calls["count"] == 0


def test_fetch_nfl_injury_source_tls_failure_raises_and_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        raise urllib.error.URLError(ssl.SSLError("CERTIFICATE_VERIFY_FAILED"))

    monkeypatch.setattr("app.services.personnel_ingestion.urllib_request.urlopen", fake_urlopen)

    with pytest.raises(PersonnelRetrievalError, match="PERSONNEL_SOURCE_TLS_ERROR"):
        fetch_nfl_injury_source()

    assert calls["count"] == 1


def test_fetch_nfl_injury_source_timeout_raises_and_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        raise socket.timeout("timed out")

    monkeypatch.setattr("app.services.personnel_ingestion.urllib_request.urlopen", fake_urlopen)

    with pytest.raises(PersonnelRetrievalError, match="PERSONNEL_SOURCE_TIMEOUT"):
        fetch_nfl_injury_source()

    assert calls["count"] == 1


def test_fetch_nfl_injury_source_non_success_status_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        return _FakeResponse(
            body=b"service unavailable",
            status=503,
            final_url=APPROVED_NFL_INJURY_SOURCE_URL,
        )

    monkeypatch.setattr("app.services.personnel_ingestion.urllib_request.urlopen", fake_urlopen)

    with pytest.raises(PersonnelRetrievalError, match="PERSONNEL_SOURCE_HTTP_STATUS_503"):
        fetch_nfl_injury_source()

    assert calls["count"] == 1


def test_fetch_nfl_injury_source_empty_response_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        return _FakeResponse(
            body=b"",
            status=200,
            final_url=APPROVED_NFL_INJURY_SOURCE_URL,
        )

    monkeypatch.setattr("app.services.personnel_ingestion.urllib_request.urlopen", fake_urlopen)

    with pytest.raises(PersonnelRetrievalError, match="PERSONNEL_SOURCE_EMPTY_RESPONSE"):
        fetch_nfl_injury_source()

    assert calls["count"] == 1


def test_fetch_nfl_injury_source_success_preserves_provenance_and_single_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        return _FakeResponse(
            body=b"<html>nfl injuries</html>",
            status=200,
            final_url=APPROVED_NFL_INJURY_SOURCE_URL,
            headers={
                "Last-Modified": "Wed, 25 Sep 2026 17:05:00 GMT",
                "Date": "Wed, 25 Sep 2026 17:06:00 GMT",
                "Content-Type": "text/html; charset=utf-8",
            },
        )

    monkeypatch.setattr("app.services.personnel_ingestion.urllib_request.urlopen", fake_urlopen)

    result = fetch_nfl_injury_source()

    assert calls["count"] == 1
    assert result.body == b"<html>nfl injuries</html>"
    assert result.source_url == APPROVED_NFL_INJURY_SOURCE_URL
    assert result.final_url == APPROVED_NFL_INJURY_SOURCE_URL
    assert result.http_status == 200
    assert result.source_timestamp == "Wed, 25 Sep 2026 17:05:00 GMT"
    assert result.content_type == "text/html; charset=utf-8"
    assert result.retrieved_at


def test_fetch_and_store_nfl_injury_source_persists_artifacts_before_parse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        return _FakeResponse(
            body=b"<html><body>fixture</body></html>",
            status=200,
            final_url=APPROVED_NFL_INJURY_SOURCE_URL,
            headers={"Date": "Wed, 25 Sep 2026 17:06:00 GMT", "Content-Type": "text/html"},
        )

    monkeypatch.setattr("app.services.personnel_ingestion.urllib_request.urlopen", fake_urlopen)

    staged = fetch_and_store_nfl_injury_source(
        season=2026,
        week=3,
        source_url=APPROVED_NFL_INJURY_SOURCE_URL,
        evidence_root=tmp_path / "fetches",
    )

    assert calls["count"] == 1
    assert staged.fetch_result.http_status == 200
    assert staged.artifact.body_path.exists()
    assert staged.artifact.metadata_path.exists()
    payload = json.loads(staged.artifact.metadata_path.read_text(encoding="utf-8"))
    assert payload["body_bytes"] == len(staged.fetch_result.body)
    assert payload["http_status"] == 200
    assert payload["source_url"] == APPROVED_NFL_INJURY_SOURCE_URL


def test_html_injury_fixture_parses_statuses_and_position_groups() -> None:
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
        source_payload=_fixture_text("nfl_injuries_week3.html"),
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )

    assert snapshot.source_timestamp == "2026-09-25T17:05:00Z"
    assert snapshot.records[0].retrieved_at == "2026-09-25T17:06:00Z"
    assert {record.team for record in snapshot.records} == {"WAS", "SEA", "DET"}
    assert {record.position_group for record in snapshot.records} == {"QB", "WR", "OL", "RB"}
    by_player = {record.player_name: record for record in snapshot.records}
    assert by_player["Jayden Daniels"].normalized_availability == "OUT"
    assert by_player["DK Metcalf"].normalized_availability == "QUESTIONABLE"
    assert by_player["Frank Ragnow"].normalized_availability == "DOUBTFUL"
    assert by_player["Austin Ekeler"].normalized_availability == "QUESTIONABLE"
    assert by_player["Jayden Daniels"].practice_status == "Dnp"
    assert by_player["Jayden Daniels"].injury_description == "Elbow"


def test_html_injury_fixture_ignores_non_player_rows() -> None:
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
        source_payload=_fixture_text("nfl_injuries_week3.html"),
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )
    assert all(record.player_name.upper() != "RESERVE/INJURED" for record in snapshot.records)


def test_html_team_heading_transition_does_not_carry_previous_team() -> None:
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
        source_payload=_fixture_text("nfl_injuries_week3.html"),
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )
    by_player = {record.player_name: record for record in snapshot.records}
    assert by_player["Jayden Daniels"].team == "WAS"
    assert by_player["DK Metcalf"].team == "SEA"
    assert by_player["Frank Ragnow"].team == "DET"


def test_json_injury_fixture_team_normalization_and_provenance() -> None:
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
        source_payload=_fixture_text("nfl_injuries_week3.json"),
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )

    assert normalize_team_id("Washington Commanders") == "WAS"
    assert normalize_team_id("L.A. Rams") == "LAR"
    assert snapshot.personnel_snapshot_id.startswith("personnel-")
    assert snapshot.personnel_snapshot_hash
    assert snapshot.records[0].source_url == DEFAULT_NFL_INJURY_SOURCE_URL
    assert snapshot.records[0].source == "nfl.com/injuries"


def test_washington_out_does_not_auto_verify_replacement_starter(monkeypatch: pytest.MonkeyPatch) -> None:
    injuries = json.loads(_fixture_text("nfl_injuries_week3.json"))
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
        source_payload=injuries,
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )

    monkeypatch.setattr(
        "app.services.personnel_authority.load_latest_personnel_snapshot",
        lambda *, season, week, store_root=None: snapshot,
    )

    lookup = load_personnel_authority_lookup(
        season=2026,
        week=3,
        schedule_events=[SimpleNamespace(source_event_id="2026_03_WAS_SEA", canonical_event_key="2026_03_WAS_SEA", away_team="WAS", home_team="SEA")],
    )

    authority = lookup["2026_03_WAS_SEA"]
    assert authority["awayExpectedStartingQB"] is None
    assert authority["awayQBStatus"] == "UNVERIFIED"
    assert authority["qbResolutionStatus"] == "UNAVAILABLE"
    assert authority["personnelReadiness"] == "UNAVAILABLE"
    assert authority["personnelReadinessReason"] == "QB_RESOLUTION_UNVERIFIED"


def test_explicit_starter_evidence_can_verify_qb_resolution() -> None:
    injuries = json.loads(_fixture_text("nfl_injuries_week3.json"))
    starter_evidence = json.loads(_fixture_text("starter_evidence_week3.json"))["starter_evidence"]
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
        source_payload=injuries,
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
        starter_evidence=starter_evidence,
    )

    lookup = load_personnel_authority_lookup(
        season=2026,
        week=3,
        personnel_snapshot=snapshot,
        schedule_events=[SimpleNamespace(source_event_id="2026_03_WAS_SEA", canonical_event_key="2026_03_WAS_SEA", away_team="WAS", home_team="SEA")],
    )

    authority = lookup["2026_03_WAS_SEA"]
    assert authority["awayExpectedStartingQB"] == "Marcus Mariota"
    assert authority["homeExpectedStartingQB"] == "Geno Smith"
    assert authority["awayQBStatus"] == "VERIFIED"
    assert authority["homeQBStatus"] == "VERIFIED"
    assert authority["qbResolutionStatus"] == "CURRENT"
    assert authority["personnelReadiness"] == "CURRENT"
    assert authority["personnelReadinessReason"] == "QB_STATUS_CURRENT"


def test_duplicate_player_conflict_fails_closed() -> None:
    payload = json.loads(_fixture_text("nfl_injuries_week3.json"))
    payload["injuries"].append(
        {
            "team": "WAS",
            "player_name": "Jayden Daniels",
            "position": "QB",
            "injury_description": "Elbow",
            "practice_status": "Full",
            "game_status": "QUESTIONABLE",
        }
    )

    with pytest.raises(PersonnelIngestionError, match="Conflicting personnel status"):
        build_personnel_snapshot(
            season=2026,
            week=3,
            source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
            source_payload=payload,
            source_timestamp="2026-09-25T17:05:00Z",
            retrieved_at="2026-09-25T17:06:00Z",
        )


def test_unknown_team_fails_closed() -> None:
    payload = json.loads(_fixture_text("nfl_injuries_week3.json"))
    payload["injuries"][0]["team"] = "Gotham City"

    with pytest.raises(PersonnelIngestionError, match="Unknown team"):
        build_personnel_snapshot(
            season=2026,
            week=3,
            source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
            source_payload=payload,
            source_timestamp="2026-09-25T17:05:00Z",
            retrieved_at="2026-09-25T17:06:00Z",
        )


def test_snapshot_hash_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    payload = json.loads(_fixture_text("nfl_injuries_week3.json"))
    first = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
        source_payload=payload,
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )
    second = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
        source_payload=payload,
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )

    assert first.personnel_snapshot_id == second.personnel_snapshot_id
    assert first.personnel_snapshot_hash == second.personnel_snapshot_hash

    first_path = write_personnel_snapshot(first, store_root=tmp_path / "personnel")
    second_path = write_personnel_snapshot(second, store_root=tmp_path / "personnel")
    assert first_path == second_path
    assert first_path.exists()
    assert load_latest_personnel_snapshot(season=2026, week=3, store_root=tmp_path / "personnel").personnel_snapshot_hash == first.personnel_snapshot_hash


def test_malformed_source_fails_closed() -> None:
    with pytest.raises(PersonnelIngestionError, match="PERSONNEL_SOURCE_PARSE_FAILED"):
        build_personnel_snapshot(
            season=2026,
            week=3,
            source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
            source_payload='{"injuries": [}',
            source_timestamp="2026-09-25T17:05:00Z",
            retrieved_at="2026-09-25T17:06:00Z",
        )


def test_ingest_nfl_personnel_snapshot_uses_secure_fetch_helper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = _fixture_text("nfl_injuries_week3.json")
    fetch_result = NFLInjuryFetchResult(
        body=payload.encode("utf-8"),
        source_url=APPROVED_NFL_INJURY_SOURCE_URL,
        final_url=APPROVED_NFL_INJURY_SOURCE_URL,
        http_status=200,
        content_type="text/html",
        source_timestamp="Wed, 25 Sep 2026 17:05:00 GMT",
        retrieved_at="2026-09-25T17:06:00Z",
    )

    monkeypatch.setattr("app.services.personnel_ingestion.fetch_nfl_injury_source", lambda **kwargs: fetch_result)

    snapshot, returned_fetch_result, snapshot_path, fetch_artifact = ingest_nfl_personnel_snapshot(
        season=2026,
        week=3,
        store_root=tmp_path / "personnel",
        fetch_evidence_root=tmp_path / "fetches",
    )

    assert returned_fetch_result == fetch_result
    assert fetch_artifact.body_path.exists()
    assert fetch_artifact.metadata_path.exists()
    assert snapshot.source_url == APPROVED_NFL_INJURY_SOURCE_URL
    assert snapshot.source_timestamp == "Wed, 25 Sep 2026 17:05:00 GMT"
    assert snapshot_path.exists()
    assert snapshot.personnel_snapshot_id.startswith("personnel-")
    assert any(record.team == "WAS" for record in snapshot.records)


def test_offline_end_to_end_fixture_pipeline_has_no_unmapped_players(tmp_path: Path) -> None:
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
        source_payload=_fixture_text("nfl_injuries_week3.html"),
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )
    path = write_personnel_snapshot(snapshot, store_root=tmp_path / "personnel")
    replay = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url=DEFAULT_NFL_INJURY_SOURCE_URL,
        source_payload=_fixture_text("nfl_injuries_week3.html"),
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )

    assert path.exists()
    assert all(record.team for record in snapshot.records)
    assert all(record.raw_team for record in snapshot.records)
    assert replay.personnel_snapshot_hash == snapshot.personnel_snapshot_hash
