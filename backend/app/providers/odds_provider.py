from __future__ import annotations

from typing import Any, Dict

from app.providers.base_provider import BaseProvider


class OddsProvider(BaseProvider):
    provider_name = "Odds"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or ""

    def fetch_data(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {
            "source": "odds",
            "status": "configured" if self.api_key else "missing_key",
            "api_key_present": bool(self.api_key),
        }

    def get_metadata(self) -> Dict[str, Any]:
        metadata = super().get_metadata()
        metadata.update({"provider": "Odds", "isLive": bool(self.api_key), "status": "Live" if self.api_key else "Unavailable"})
        return metadata
