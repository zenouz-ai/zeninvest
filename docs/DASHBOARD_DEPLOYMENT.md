---
tags: [dashboard, deployment, vps, docker]
status: delivered
last_updated: 2026-03-10
---

# Dashboard Deployment

> VPS deployment plan for the 7-page monitoring dashboard (US-1.8).

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

**Run History:** Shows `runs` table entries (one per cycle). Runs are created when `dashboard.enabled` and `dashboard.events_enabled` are true; scheduler and orchestrator both create/update Run records.

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

**Outcome:** Dashboard is running on VPS. All 7 pages (Home, Universe, Run History, Portfolio, Opportunity, Order Management, Costs), activity feed (SSE), and API are available at `http://YOUR_VPS_IP:8000`.

---

## Security Note

With VPS IP and HTTP:
- Use firewall to restrict access (e.g. only your IP) if desired.
- Consider basic auth or API key for the dashboard later.
- Dashboard Home has **Dry Run** and **Live Run** buttons; they call `POST /api/runs/trigger` and `POST /api/runs/trigger-live` respectively. Live Run requires confirmation.

## Related Notes

- [Dashboard System](DASHBOARD.md)
- [Deployment (VPS)](DEPLOYMENT.md)
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md) — US-1.8
