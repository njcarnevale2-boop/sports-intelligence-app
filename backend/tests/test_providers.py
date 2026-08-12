import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.providers.provider_manager import ProviderManager


def test_provider_manager_falls_back_to_mock_when_key_missing(monkeypatch):
    monkeypatch.delenv("SPORTSRADAR_API_KEY", raising=False)
    monkeypatch.setenv("INJURY_PROVIDER", "mock")

    manager = ProviderManager()
    provider = manager.get_injury_provider()

    assert provider.provider_name == "Mock"
    assert provider.get_metadata()["provider"] == "Mock"


def test_provider_manager_uses_mock_when_override_is_enabled(monkeypatch):
    monkeypatch.setenv("SPORTSRADAR_API_KEY", "demo-key")
    monkeypatch.setenv("INJURY_PROVIDER", "mock")

    manager = ProviderManager()
    provider = manager.get_injury_provider()

    assert provider.provider_name == "Mock"


def test_provider_manager_default_is_espn(monkeypatch):
    monkeypatch.delenv("INJURY_PROVIDER", raising=False)

    manager = ProviderManager()
    provider = manager.get_injury_provider()

    assert provider.provider_name == "ESPN (Public)"
    assert provider.get_metadata()["requiresCredentials"] is False
