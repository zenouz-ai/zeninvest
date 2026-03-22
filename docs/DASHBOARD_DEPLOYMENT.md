---
tags: [dashboard, deployment, vps, docker]
status: delivered
last_updated: 2026-03-10
---

# Dashboard Deployment

> VPS deployment plan for the 8-page monitoring dashboard (US-1.8).

## Purpose

Deploy the dashboard backend (FastAPI + SSE) and frontend (built SPA) as a Docker service on the VPS, sharing the agent's SQLite database.

## Domain / Access Options

| Option | Pros | Cons |
|--------|------|------|
| **VPS IP only** (recommended) | No cost, no setup. Access via `http://YOUR_VPS_IP:8000` | No HTTPS (Let's Encrypt needs a domain). HTTP is acceptable for a personal dashboard. |
| **Purchase domain** | HTTPS via Let's Encrypt, cleaner URL | ~£10–15/year |
| **GitHub Pages** | Free static hosting | Not suitable: frontend must call VPS API. HTTPS page → HTTP API = mixed content blocked. Backend still needs VPS. |

**Recommended:** Use VPS IP for initial deployment. Add a domain later if HTTPS is desired.

---

## Docker Architecture

Two services in `docker-compose.yml`, each with its own Dockerfile:

| Service | Dockerfile | Purpose | Entry point |
|---------|-----------|---------|-------------|
| `investment-agent` | `Dockerfile.agent` | Python-only — runs scheduler | `alembic upgrade head && python -m src.scheduler.scheduler` |
| `dashboard` | `Dockerfile` | Multi-stage (Node + Python) — builds frontend, runs FastAPI | `uvicorn dashboard.backend.app.main:app` |

Both share the same SQLite DB via `./data` volume. The split avoids building the frontend twice and halves memory usage on low-RAM VPS instances.

- `Dockerfile.agent`: Python 3.12-slim, Poetry deps, application code. No Node.js, no frontend build.
- `Dockerfile`: Stage 1 (Node 20-slim) builds the React/Vite frontend with `DASHBOARD_API_KEY` baked in as `VITE_API_KEY`. Stage 2 (Python 3.12-slim) installs Poetry deps, copies app code + built frontend dist.

**Frontend API URL:** The frontend is served from the same origin as the API. Requests use relative paths (`/api/*`). The SSE activity feed uses `/api/events/stream` (same-origin), so it works at `http://VPS_IP:8000`.

**Authentication:** When `DASHBOARD_API_KEY` is set, all `/api/*` endpoints require `X-API-Key` header. Write endpoints (`/api/system/*`, `/api/runs/trigger*`) are always protected — they cannot be made public even via `public_routes` config.

### VPS Firewall (one-time)

```bash
sudo ufw allow 8000/tcp comment "Dashboard"
sudo ufw reload
```

### Optional: nginx Reverse Proxy

For port 80 or future HTTPS:
- nginx listens on 80, proxies to `http://127.0.0.1:8000`
- Disable buffering for SSE: `proxy_buffering off` on `/api/events/stream`

---

## Deployment Commands (VPS)

Run from the project directory on the VPS (e.g. `/home/deploy/investment-agent`). Use `main` or your deployment branch (e.g. `feature/dashboard-full-spec`) as appropriate.

```bash
cd /home/deploy/investment-agent
git fetch origin
git pull origin main   # or: git pull origin feature/dashboard-full-spec

# Ensure dashboard enabled in config/settings.yaml
# dashboard.enabled: true, dashboard.events_enabled: true

# Allow dashboard port (one-time per VPS)
sudo ufw allow 8000/tcp comment "Dashboard"
sudo ufw reload

docker compose up -d --build

docker compose ps
curl http://localhost:8000/health
curl http://localhost:8000/api/events/?limit=3
```

Access from your machine: `http://YOUR_VPS_IP:8000`

### Updating / Rebuilding the dashboard

After code changes (frontend or backend), rebuild and restart:

```bash
cd /home/deploy/investment-agent   # or your project path
git pull origin main
docker compose up -d --build
```

To rebuild only the dashboard service (keeps agent running):

```bash
docker compose up -d --build dashboard
```

Verify: `curl http://localhost:8000/health` and open `http://YOUR_VPS_IP:8000` in a browser.

**Local development:** Build the frontend with `cd dashboard/frontend && npm run build`. The dashboard Docker image (`Dockerfile`) runs a multi-stage build (Node → Python) that includes the built SPA. The agent image (`Dockerfile.agent`) is Python-only and does not build the frontend.

---

**Run History:** Shows `runs` table entries (one per cycle). Scheduler creates a single Run per scheduled cycle and passes its cycle_id to the orchestrator, which updates that Run on completion (no duplicate cycle_ vs scheduled_ entries). Manual/dashboard-triggered runs create their own Run with a `cycle_*` id.

**One-off live cycle (in addition to scheduler):**
```bash
docker exec -it investment-agent poetry run python -m src.orchestrator.main
```

---

## Deployment Complete Checklist

When the operator has run the steps above on a VPS:

- [x] Code: dashboard service in docker-compose; multi-stage frontend build; FastAPI serves SPA
- [x] Config: `dashboard.enabled: true`, `dashboard.events_enabled: true` in `config/settings.yaml`
- [x] Firewall: `ufw allow 8000/tcp` (included in deployment commands above)
- [x] Build & run: `docker compose up -d --build`
- [x] Verify: `curl http://localhost:8000/health` and open `http://YOUR_VPS_IP:8000` in a browser

**Outcome:** Dashboard is running on VPS. All 8 pages (Home, Universe, Run History, Portfolio, Opportunity, Order Management, Costs, Roadmap), activity feed (SSE), and API are available at `http://YOUR_VPS_IP:8000`. Portfolio page includes Cash, Investments, Positions (T212 positions normalised for display), sector allocation, and chronological value history chart.

---

## Security Note

With VPS IP and HTTP:
- Use firewall to restrict access (e.g. only your IP) if desired.
- **API Key Authentication (US-7.1, delivered):** Set `DASHBOARD_API_KEY` in your `.env` before exposing the dashboard. When set, all `/api/*` endpoints require a matching `X-API-Key` header. Generate a key with:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
  Add to `.env`:
  ```
  DASHBOARD_API_KEY=<your-generated-key>
  ```
  The frontend automatically picks up `VITE_API_KEY` at build time (passed as Docker build arg). Operators can also set the key in the browser via **API key** in the nav (stored in `localStorage`); after save the SPA reloads. If the key is wrong or missing, a red **auth banner** explains the 403 and links to that flow. When `DASHBOARD_API_KEY` is not set, the dashboard runs in unauthenticated mode with a startup warning — acceptable for localhost-only dev.
- **Public demo routes:** To expose read-only pages (e.g. Roadmap, Costs, Run History) without sharing the API key, add `public_routes` to `config/settings.yaml`:
  ```yaml
  dashboard:
    public_routes:
      - "/api/docs/"           # Roadmap & architecture — safe
      - "/api/costs/"          # API spend totals — safe
      - "/api/runs/"           # Cycle history (timestamps + status) — safe
      - "/api/performance/metrics"  # Aggregate Sharpe/win-rate — safe
  ```
  GET requests to listed prefixes bypass auth. Write endpoints (`POST /api/runs/trigger-live`, `POST /api/system/*`) remain protected regardless. Never list `/api/portfolio/` (position data) or `/api/opportunity/` (pending buys) — these leak alpha.
- **CORS:** Dashboard API restricts cross-origin requests via `dashboard.cors_origins` in `config/settings.yaml`. Default: localhost only. For VPS, add your IP:
  ```yaml
  dashboard:
    cors_origins:
      - "http://YOUR_VPS_IP:8000"
      - "http://localhost:3000"
  ```
- Dashboard Home has **Dry Run** and **Live Run** buttons; they call `POST /api/runs/trigger` and `POST /api/runs/trigger-live` respectively. Live Run requires confirmation.

## Related Notes

- [Dashboard System](DASHBOARD.md)
- [Deployment (VPS)](DEPLOYMENT.md)
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md) — US-1.8
