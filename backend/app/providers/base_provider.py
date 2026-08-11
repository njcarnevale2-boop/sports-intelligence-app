from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


class BaseProvider:
    provider_name: str = "Base"

    def fetch_data(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "isLive": False,
            "status": "Unavailable",
        }
