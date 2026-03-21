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

Current setup: one container (`investment-agent`) runs the scheduler. The dashboard needs:
- Same SQLite DB (shared `./data` volume)
- Dashboard backend (FastAPI) on port 8000
- Built frontend (static files) served by FastAPI

**Approach:** Add a second service `dashboard` in docker-compose. Same image, different command. Shares `./data` volume.

---

## Implementation Steps

### 1. Update Dockerfile

- Add `COPY dashboard/ dashboard/` so the dashboard package is in the image.
- Add multi-stage frontend build:
  - Stage 1: Node image → `cd dashboard/frontend && npm ci && npm run build`
  - Stage 2: Python image → copy `dashboard/frontend/dist` from stage 1

### 2. Update FastAPI to Serve Frontend

In `dashboard/backend/app/main.py`:
- Add `StaticFiles` for the built frontend.
- Mount `/` to serve `dashboard/frontend/dist` with `html=True` (SPA fallback).
- Keep `/api/*` and `/health` routes; they take precedence.

### 3. Update docker-compose.yml

Add `dashboard` service:

```yaml
dashboard:
  build: .
  container_name: investment-dashboard
  restart: always
  env_file: [.env]
  volumes:
    - ./data:/app/data
    - ./journals:/app/journals
    - ./logs:/app/logs
  ports:
    - "8000:8000"
  command: ["uvicorn", "dashboard.backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
  depends_on:
    - investment-agent
```

### 4. Frontend API URL

The frontend is served from the same origin as the API. `VITE_API_URL` can stay unset — requests use relative paths. The SSE activity feed uses a relative URL (`/api/events/stream`) when `VITE_API_URL` is unset, so it works when accessing the dashboard at `http://VPS_IP:8000` (same-origin).

### 5. VPS Firewall (operator step)

Documented in [Deployment Commands (VPS)](#deployment-commands-vps). One-time per VPS:

```bash
sudo ufw allow 8000/tcp comment "Dashboard"
sudo ufw reload
```

### 6. Optional: nginx Reverse Proxy

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

**Local development:** Build the frontend with `cd dashboard/frontend && npm run build`. The Docker image runs a multi-stage build (Node → Python) that includes the built SPA.

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
  The frontend automatically picks up `VITE_API_KEY` at build time (passed as Docker build arg). When `DASHBOARD_API_KEY` is not set, the dashboard runs in unauthenticated mode with a startup warning — acceptable for localhost-only dev.
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
