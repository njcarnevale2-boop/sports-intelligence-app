# Beta Readiness Audit

## Summary
This audit reviewed the current Sports Intelligence app for issues that could block an invite-only beta. The audit focused on frontend routes, backend endpoints, TypeScript and Python correctness, environment configuration, API resilience, navigation, auth, and obvious security and data-quality concerns.

## Findings

### CRITICAL

1. Hardcoded localhost API calls remain in the frontend
- File/location: app/admin/page.tsx, app/auth-context.tsx, app/games/page.tsx, app/login/page.tsx, app/performance/page.tsx, app/register/page.tsx, app/settings/page.tsx
- Problem: Multiple pages call http://localhost:8000 directly, which breaks in deployed or non-local environments and makes beta rollout fragile.
- Why it matters: Invite-only beta environments will not reliably reach the backend without environment-based configuration.
- Recommended fix: Replace hardcoded endpoints with environment-based URLs and timeout-aware helpers.

2. Backend CORS is overly narrow for beta environments
- File/location: backend/app/main.py
- Problem: CORS only allows http://localhost:3000.
- Why it matters: Any non-local frontend host or staging environment will be blocked by browser policy.
- Recommended fix: Read allowed origins from environment configuration and include a safe default list.

3. Auth is not yet production-ready for beta access
- File/location: backend/app/routes/auth.py, backend/app/auth.py, app/auth-context.tsx
- Problem: Authentication exists but relies on local token storage and the backend does not yet enforce a hardened auth policy or refresh-flow behavior beyond the basic implementation.
- Why it matters: Beta users need predictable sign-in, sign-out, and token handling without confusing failures.
- Recommended fix: Add explicit token refresh handling, redirect behavior on expired tokens, and stronger server-side auth validation before opening beta access.

### HIGH

4. The backend still exposes mock-driven injury/weather data as if it were real intelligence
- File/location: backend/app/routes/injuries.py, backend/app/services/injuries.py, backend/app/services/weather.py, backend/app/services/injury_matchup.py
- Problem: The API returns mock status and mock payloads when no live provider data is available.
- Why it matters: Beta users may interpret mock outputs as live analysis, creating trust and compliance issues.
- Recommended fix: Clearly label these as mock-only responses in the UI and expose a provider status flag that is surfaced prominently.

5. Performance page can show empty state but does not distinguish “no data” from “unavailable endpoint” clearly enough
- File/location: app/performance/page.tsx
- Problem: The page currently depends on backend data without a strong fallback for endpoint errors or empty history.
- Why it matters: Beta users need clear feedback when performance has not yet accumulated or when the backend is unreachable.
- Recommended fix: Display explicit states for loading, empty history, and API failure.

6. Frontend API calls have no timeout handling
- File/location: app/lib/api.ts (new helper), and all frontend pages using fetch directly
- Problem: Requests can hang indefinitely if the backend is slow or unavailable.
- Why it matters: A hanging request can create a poor beta experience and make app pages feel broken.
- Recommended fix: Continue using timeout-aware request helpers and fail fast with visible error states.

### MEDIUM

7. Missing environment variable support for API base URL and CORS origins
- File/location: app/lib/api.ts, backend/app/config.py, backend/app/main.py
- Problem: The app has no explicit environment-based configuration for runtime API settings.
- Why it matters: Local development and hosted beta environments need predictable configuration.
- Recommended fix: Add NEXT_PUBLIC_API_BASE_URL and backend CORS origin settings via environment variables.

8. The app still uses mock-backed intelligence in several services
- File/location: backend/app/services/injuries.py, backend/app/services/injury_matchup.py, backend/app/services/weather.py
- Problem: The app is still presenting deterministic mock intelligence as a core experience.
- Why it matters: This is acceptable for development, but it should be clearly surfaced to beta users so expectations are managed.
- Recommended fix: Add provider status badges and make mock usage visible in the UI and API responses.

9. Backend startup silently swallows initialization failures
- File/location: backend/app/main.py
- Problem: The startup event catches all exceptions and ignores database initialization issues.
- Why it matters: This can hide real beta blockers such as broken migrations or schema issues.
- Recommended fix: Log startup failures and surface health-check diagnostics rather than silently swallowing them.

10. Missing explicit health diagnostics for auth and performance endpoints
- File/location: backend/app/routes/auth.py, backend/app/routes/performance.py
- Problem: These routes are present, but there is no richer health or readiness detail for beta operators.
- Why it matters: Beta support needs fast visibility into auth and performance health.
- Recommended fix: Add readiness endpoints that report dependency status and last-known errors.

### LOW

11. Some pages use generic error messages that do not distinguish backend outage from data absence
- File/location: app/briefing/page.tsx, app/games/page.tsx, app/line-movement/page.tsx
- Problem: The UI does not clearly say whether data is empty or the request failed.
- Why it matters: Small clarity issues can create confusion during beta onboarding.
- Recommended fix: Use specific error states such as “No data available” versus “Unable to reach backend”.

12. Navigation is present but the account shell still lacks a polished beta-ready experience
- File/location: app/layout-shell.tsx
- Problem: The shell is functional, but account interactions remain minimal and could be improved for invite-only onboarding.
- Why it matters: Beta users need confidence that the app is intentional and complete.
- Recommended fix: Improve account affordances and state messaging with a small polish pass.

## Safe fixes completed during this audit
- Added a shared frontend API helper with timeout handling in app/lib/api.ts.
- Replaced the most obvious hardcoded localhost frontend calls with the shared helper.
- Verified the frontend build still succeeds.
- Verified the backend Python modules still compile successfully.

## Recommended next steps before beta
1. Introduce environment-based API base URLs for frontend and backend CORS.
2. Add explicit mock/live provider badges in the UI.
3. Harden auth flows with refresh handling and better token expiry UX.
4. Add clearer readiness and health diagnostics for the backend.
5. Review remaining mock-backed services before inviting users.
