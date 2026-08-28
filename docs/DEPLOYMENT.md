# Deployment Guide

This document covers the staging deployment setup for the Sports Intelligence application without introducing new product features.

## 1. Frontend deployment (Vercel)

1. Connect the repository to Vercel.
2. Select the Next.js app root as the project root.
3. Set the production environment variables below.
4. Deploy the app.

### Required frontend environment variables

- NEXT_PUBLIC_API_BASE_URL: the public URL of the FastAPI backend, for example `https://sports-intelligence-api.example.com`

### Production startup command

Vercel uses the existing Next.js build pipeline automatically:

```bash
npm run build
npm run start
```

## 2. Backend deployment (FastAPI)

Deploy the backend service separately from the frontend. The backend should run from the `backend/` directory.

Week 1 deployment contract:

- One always-on backend instance.
- Backend replicas = 1.
- Persistent disk required.
- No Redis required.
- No managed Postgres required.
- No separate worker required.
- No Kubernetes required.

### Required backend environment variables

- NFL_ANALYTICS_OS_ROOT: persistent root path for the NFL Analytics OS runtime tree, for example `/data/NFL_Analytics_OS_v1_9`
- CORS_ORIGINS: a comma-separated list of allowed frontend origins, for example `https://sports-intelligence.vercel.app`
- DATABASE_URL: the production SQLite or SQLAlchemy connection string. For Week 1 a persistent SQLite path is supported, for example `sqlite:////data/sports_intelligence.db`
- JWT_SECRET_KEY: a strong secret value
- ADMIN_API_KEY: admin-only API access token
- PREGAME_AUTOMATION_ENABLED: set to `true` on the always-on backend host when Week 1 automation should run
- POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB: optional fallbacks when `DATABASE_URL` is not set

### Production startup command

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

A repository-level Procfile is also provided for platforms that use it.

The backend host must support:

- outbound HTTPS
- restart-on-failure
- persistent disk mounted at the configured runtime root
- background threads for the in-process scheduler
- health checks against `/health`

## 3. Persistent runtime paths

The following paths must survive backend restart and backend replacement:

- `${NFL_ANALYTICS_OS_ROOT}/database/nfl_model.duckdb`
- `${NFL_ANALYTICS_OS_ROOT}/outputs/current_game_projections.csv`
- `${NFL_ANALYTICS_OS_ROOT}/outputs/line_movement_board.csv`
- `${NFL_ANALYTICS_OS_ROOT}/outputs/schedule_context_latest.csv`
- `${NFL_ANALYTICS_OS_ROOT}/outputs/ranked_bet_board.csv`
- `${NFL_ANALYTICS_OS_ROOT}/logs/refresh_state.json`
- the SQLite database referenced by `DATABASE_URL`

For Week 1, mount these on one persistent backend volume and keep the backend at one replica.

## 4. PostgreSQL setup

PostgreSQL remains optional. Week 1 does not require a migration away from SQLite.

1. Create a PostgreSQL database for staging.
2. Create a dedicated user with access to that database.
3. Set `DATABASE_URL` to the SQLAlchemy-compatible connection string:

```bash
postgresql+psycopg2://<user>:<password>@<host>:5432/<database>
```

If the deployment platform provides a managed Postgres service, use the platform-provided connection string directly.

## 5. CORS configuration

The backend reads `CORS_ORIGINS` from the environment and allows the listed origins. For Vercel staging, add the deployed frontend domain as one of the values.

Example:

```bash
CORS_ORIGINS=https://sports-intelligence.vercel.app,https://sports-intelligence-git-main.example.vercel.app
```

## 6. Health checks

- Backend health endpoint: `https://<backend-host>/health`
- Backend API readiness: `https://<backend-host>/api/opportunities?limit=1`
- Scheduler/admin readiness: `https://<backend-host>/api/admin/status`

## 7. Secrets and environment safety

- Do not commit `.env` files or real secrets to Git.
- Keep deployment secrets in the hosting platform environment settings.
- The repository includes `.env.example` as the safe template.
- `ODDS_API_KEY` must remain backend-only and must never be exposed through a `NEXT_PUBLIC_` environment variable.
