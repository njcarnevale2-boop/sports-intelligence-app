# Live Data Migration Plan

## Executive summary

The frontend contract is already relatively stable. The backend services expose structured intelligence payloads, and the provider layer is already designed to swap from mock behavior to live providers without changing route shapes or the UI contract.

The remaining gaps are concentrated in injury, weather, schedule, and market-context data. These are the highest-value areas to replace before beta because they directly affect trust, explainability, and the perceived quality of the product.

## Architecture fit

The current provider architecture is compatible with a live-data migration:

- [backend/app/providers/provider_manager.py](../backend/app/providers/provider_manager.py) centralizes provider selection.
- [backend/app/services/injuries.py](../backend/app/services/injuries.py) and [backend/app/services/weather.py](../backend/app/services/weather.py) already consume provider metadata and return normalized intelligence payloads.
- [backend/app/services/injury_matchup.py](../backend/app/services/injury_matchup.py) and [backend/app/services/data_refresh.py](../backend/app/services/data_refresh.py) consume those services, so the frontend can stay unchanged as long as the response shapes remain intact.
- The routes under [backend/app/routes](../backend/app/routes) already consume service-layer output, which keeps the swap mostly isolated to the backend.

## Migration audit

| Surface | Current implementation | Current provider state | Recommended live provider | Priority | Estimated work | Notes / blockers |
| --- | --- | --- | --- | --- | --- | --- |
| Injury intelligence | [backend/app/services/injuries.py](../backend/app/services/injuries.py) | Mock provider is used by default because the provider manager falls back to mock whenever the injury toggle is enabled or the SportsRadar key is missing | SportsRadar injury / roster / availability feed | P0 | 2-3 days | Missing `SPORTSRADAR_API_KEY`. The service already accepts a normalized injury payload, so the swap should be mostly adapter work. |
| Injury matchup context | [backend/app/services/injury_matchup.py](../backend/app/services/injury_matchup.py) | Reuses the injury analyzer, so it inherits the current mock-backed status | Same live injury feed as above | P0 | 1 day | No frontend contract change required if the output schema remains the same. |
| Weather intelligence | [backend/app/services/weather.py](../backend/app/services/weather.py) | Mock provider is used by default because the provider manager falls back to mock when the weather toggle is enabled or the weather key is missing | OpenWeather or WeatherAPI | P0 | 1-2 days | Missing `WEATHER_API_KEY`. The service already exposes normalized fields such as weather score, impacts, summary, and recommendation. |
| Game slate / schedule | [backend/app/services/games.py](../backend/app/services/games.py) | Hard-coded matchup list and generated game metadata rather than a live provider | SportsRadar schedule or a normalized NFL schedule feed | P1 | 3-4 days | This is not a mock provider yet; it is deterministic fixture data. The UI contract can remain intact with a provider adapter. |
| Schedule context | [backend/app/routes/context.py](../backend/app/routes/context.py) | Reads local CSV artifacts from a user-specific Downloads folder | A live schedule-context feed or an ingested dataset with the same columns | P1 | 2-3 days | This is currently a file dependency rather than a provider, so it is less clean than the injury/weather path but still migratable. |
| Market intelligence | [backend/app/services/market_intelligence.py](../backend/app/services/market_intelligence.py) | Reads a line-movement CSV from a local model outputs directory | Odds API / sportsbook market feed / normalized ingestion pipeline | P1 | 3-5 days | Missing `ODDS_API_KEY` and local model outputs make this currently brittle. |
| Player-level context | No dedicated live provider service yet; player details are embedded in injury payloads | Injury data currently uses a compact mock roster | SportsRadar roster / player availability feed | P1 | 2-3 days | Important for richer trust markers and more believable explainability. |
| Opportunity data | [backend/app/routes/opportunities.py](../backend/app/routes/opportunities.py) | Reads ranked bet-board CSV artifacts from a local model outputs directory | A live opportunity feed or a normalized ingestion pipeline | P1 | 2-3 days | The frontend can remain unchanged if the opportunity schema stays consistent. |

## Current mock and fallback behavior

### Injury data

- [backend/app/services/injuries.py](../backend/app/services/injuries.py) uses a built-in mock injury roster unless an external injury payload is provided.
- [backend/app/providers/provider_manager.py](../backend/app/providers/provider_manager.py) returns [backend/app/providers/mock_provider.py](../backend/app/providers/mock_provider.py) when `USE_MOCK_INJURIES=true` or when no injury provider key is available.
- [backend/app/routes/injuries.py](../backend/app/routes/injuries.py) explicitly falls back to the mock analyzer when no provider-backed injury file exists.

### Weather data

- [backend/app/services/weather.py](../backend/app/services/weather.py) uses a built-in mock weather snapshot by default.
- [backend/app/providers/provider_manager.py](../backend/app/providers/provider_manager.py) returns the mock provider when `USE_MOCK_WEATHER=true` or when no weather API key is available.

### Schedule data

- [backend/app/services/games.py](../backend/app/services/games.py) uses a fixed matchup schedule and generated intelligence helpers.
- This does not yet have a provider abstraction, so the migration path is slightly broader than the injury/weather path.

## Recommended implementation sequence

1. Add live provider adapters for injuries and weather that normalize into the existing service response shapes.
2. Flip the provider manager to prefer the live provider when credentials are present and disable mock fallback via environment flags.
3. Introduce a small ingestion layer for schedule and player context so the database or JSON files can be refreshed without touching the frontend.
4. Keep the service response schemas stable so the UI and routes remain unchanged.
5. Add health and observability markers so the admin status view can clearly show whether a surface is live, mocked, or unavailable.

## Environment and credential gaps

The following configuration is currently missing or not wired for live usage:

- `SPORTSRADAR_API_KEY`: required for injury and roster-backed live data.
- `WEATHER_API_KEY`: required for weather-provider swap-out.
- `ODDS_API_KEY`: required for market-intelligence migration.
- `USE_MOCK_INJURIES=false` and `USE_MOCK_WEATHER=false`: should be set once live providers are available.

## Expected outcome

Once the live providers are wired in, the product should be able to:

- show real or refreshed injury context instead of mock injury summaries,
- show real weather context instead of synthetic weather assumptions,
- keep the frontend experience intact while improving backend trustworthiness,
- expose clearer provider status in admin and diagnostics surfaces.
