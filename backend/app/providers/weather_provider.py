from __future__ import annotations

from typing import Any, Dict

from app.providers.base_provider import BaseProvider


class WeatherProvider(BaseProvider):
    provider_name = "Weather"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or ""

    def fetch_data(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {
            "source": "weather",
            "status": "configured" if self.api_key else "missing_key",
            "api_key_present": bool(self.api_key),
        }

    def get_metadata(self) -> Dict[str, Any]:
        metadata = super().get_metadata()
        metadata.update({"provider": "Weather", "isLive": bool(self.api_key)})
        return metadata
