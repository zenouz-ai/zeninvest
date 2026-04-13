# Dashboard

ZenInvest ships with a React frontend and FastAPI backend for monitoring runs,
portfolio state, research activity, and system health.

## Dashboard Areas

- overview and run health
- portfolio and positions
- universe and opportunity views
- insights and macro context
- order management
- costs and run history
- conversational command surfaces

## Access Model

The dashboard distinguishes between:

- **public-safe read models** for sanitized demonstrations
- **operator-authenticated routes** for live controls and sensitive detail

This public mirror documents the product shape and local development model, but
does not include private deployment or operator runbooks.

## Local Development

Run the backend from the repo root:

```bash
poetry run python -m dashboard.backend.server
```

Run the frontend from `dashboard/frontend`:

```bash
npm ci
npm test
npm run build
```
