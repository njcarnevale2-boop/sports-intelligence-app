from __future__ import annotations

from unittest.mock import patch

import pytest

from app.runtime_jobs import odds_refresh


def test_run_refresh_requires_odds_api_key_and_makes_no_request_without_key(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    with patch.object(odds_refresh.requests, "get") as request_get:
        with pytest.raises(RuntimeError, match="ODDS_API_KEY_MISSING"):
            odds_refresh.run_refresh()
        request_get.assert_not_called()
