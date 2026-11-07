import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.experimental_power import router
from app.services.experimental_power import ExperimentalPowerUnavailable, load_experimental_power


BUNDLE = Path("/Users/nickcarnevale/Development/sia-week9-recovery-20261105/canonical_week9_power_only_v1_validated")


def configure(monkeypatch, root):
    monkeypatch.setenv("SIA_EXPERIMENTAL_POWER_ENABLED", "true")
    monkeypatch.setenv("SIA_POWER_CANDIDATE_ROOT", str(root))
    monkeypatch.setenv("SIA_POWER_CANDIDATE_MANIFEST_SHA256", hashlib.sha256((root / "bundle.json").read_bytes()).hexdigest())


def test_experimental_power_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SIA_EXPERIMENTAL_POWER_ENABLED", raising=False)
    with pytest.raises(ExperimentalPowerUnavailable, match="DISABLED"):
        load_experimental_power(season=2026, week=9)


def test_real_bundle_is_power_only_and_not_active(monkeypatch):
    if not BUNDLE.exists():
        pytest.skip("Local prepared bundle unavailable")
    configure(monkeypatch, BUNDLE)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/api/experimental/power-projections?season=2026&week=9")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["count"] == 15
    assert payload["projectionReadiness"] == "NOT_ACTIVE"
    assert payload["productionEligible"] is False
    assert payload["officialEligible"] is False
    assert payload["personnelApproval"] == "NOT_EVALUATED"
    for row in payload["games"]:
        assert row["homeFairSpread"] == -row["homeExpectedMargin"]
        assert not {"probability", "modelProbability", "currentEV", "pick", "selection", "recommendedUnits"} & row.keys()


def test_tampered_bundle_is_rejected(monkeypatch, tmp_path):
    if not BUNDLE.exists():
        pytest.skip("Local prepared bundle unavailable")
    root = tmp_path / "bundle"
    shutil.copytree(BUNDLE, root)
    configure(monkeypatch, root)
    manifest = json.loads((root / "bundle.json").read_bytes())
    artifact = root / manifest["candidatePath"]
    artifact.write_bytes(artifact.read_bytes() + b" ")
    with pytest.raises(ExperimentalPowerUnavailable, match="HASH_MISMATCH"):
        load_experimental_power(season=2026, week=9)


def test_active_pointer_is_rejected(monkeypatch, tmp_path):
    if not BUNDLE.exists():
        pytest.skip("Local prepared bundle unavailable")
    root = tmp_path / "bundle"
    shutil.copytree(BUNDLE, root)
    configure(monkeypatch, root)
    pointer = root / "power_engine/projections/active/active-2026-9.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text("{}")
    with pytest.raises(ExperimentalPowerUnavailable, match="ACTIVE_POINTERS"):
        load_experimental_power(season=2026, week=9)