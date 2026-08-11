from __future__ import annotations

from typing import Any, Dict

from app.providers.base_provider import BaseProvider


class MockProvider(BaseProvider):
    provider_name = "Mock"

    def fetch_data(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"source": "mock", "status": "mock"}

    def get_metadata(self) -> Dict[str, Any]:
        metadata = super().get_metadata()
        metadata.update({"provider": "Mock", "isLive": False, "status": "Mock"})
        return metadata
