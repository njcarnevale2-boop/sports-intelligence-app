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

### Required backend environment variables

- CORS_ORIGINS: a comma-separated list of allowed frontend origins, for example `https://sports-intelligence.vercel.app`
- DATABASE_URL: the production PostgreSQL connection string
- JWT_SECRET_KEY: a strong secret value
- POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB: optional fallbacks when `DATABASE_URL` is not set

### Production startup command

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

A repository-level Procfile is also provided for platforms that use it.

## 3. PostgreSQL setup

1. Create a PostgreSQL database for staging.
2. Create a dedicated user with access to that database.
3. Set `DATABASE_URL` to the SQLAlchemy-compatible connection string:

```bash
postgresql+psycopg2://<user>:<password>@<host>:5432/<database>
```

If the deployment platform provides a managed Postgres service, use the platform-provided connection string directly.

## 4. CORS configuration

The backend reads `CORS_ORIGINS` from the environment and allows the listed origins. For Vercel staging, add the deployed frontend domain as one of the values.

Example:

```bash
CORS_ORIGINS=https://sports-intelligence.vercel.app,https://sports-intelligence-git-main.example.vercel.app
```

## 5. Health checks

- Backend health endpoint: `https://<backend-host>/health`
- Backend API readiness: `https://<backend-host>/api/opportunities?limit=1`

## 6. Secrets and environment safety

- Do not commit `.env` files or real secrets to Git.
- Keep deployment secrets in the hosting platform environment settings.
- The repository includes `.env.example` as the safe template.
