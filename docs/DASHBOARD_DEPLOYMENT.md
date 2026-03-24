---
tags: [dashboard, deployment, vps, docker]
status: delivered
last_updated: 2026-03-10
---

# Dashboard Deployment

> VPS deployment plan for the 10-page monitoring dashboard (US-1.8).

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

Three services in `docker-compose.yml`, using two Dockerfiles:

| Service | Dockerfile | Purpose | Entry point |
|---------|-----------|---------|-------------|
| `investment-agent` | `Dockerfile.agent` | Python-only — runs scheduler | `alembic upgrade head && python -m src.scheduler.scheduler` |
| `slack-listener` | `Dockerfile.agent` | Python-only — keeps Slack Socket Mode connected | `alembic upgrade head && python -m src.agents.notifications.slack_trade_listener` |
| `dashboard` | `Dockerfile` | Multi-stage (Node + Python) — builds frontend, runs FastAPI | `uvicorn dashboard.backend.app.main:app` |

All three share the same SQLite DB via `./data` volume. The split avoids building the frontend twice and halves memory usage on low-RAM VPS instances.

- `Dockerfile.agent`: Python 3.12-slim, Poetry deps, application code. No Node.js, no frontend build.
- `Dockerfile`: Stage 1 (Node 20-slim) builds the React/Vite frontend with no secrets injected at build time. Stage 2 (Python 3.12-slim) installs Poetry deps, copies app code + built frontend dist.

**Frontend API URL:** The frontend is served from the same origin as the API. Requests use relative paths (`/api/*`). The SSE activity feed uses `/api/events/stream` (same-origin), so it works at `http://VPS_IP:8000`.

**Authentication:** Public, read-only routes live under `/api/public/*`. Operator routes require backend login and a signed session cookie. Operator login is blocked on plain HTTP except localhost-only development mode.

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

**Local development:** Build the frontend with `cd dashboard/frontend && npm run build`. The dashboard Docker image (`Dockerfile`) runs a multi-stage build (Node → Python) that includes the built SPA. The agent image (`Dockerfile.agent`) is Python-only and is reused by both the scheduler and the Slack listener.

---

**Run History:** Shows `runs` table entries (one per cycle). Scheduler creates a single Run per scheduled cycle and passes its cycle_id to the orchestrator, which updates that Run on completion (no duplicate cycle_ vs scheduled_ entries). Manual/dashboard-triggered runs create their own Run with a `cycle_*` id.

**One-off live cycle (in addition to scheduler):**
```bash
docker exec -it investment-agent poetry run python -m src.orchestrator.main
```

---

## Deployment Complete Checklist

When the operator has run the steps above on a VPS:

- [x] Code: scheduler + always-on Slack listener + dashboard services in docker-compose; multi-stage frontend build; FastAPI serves SPA
- [x] Config: `dashboard.enabled: true`, `dashboard.events_enabled: true` in `config/settings.yaml`
- [x] Firewall: `ufw allow 8000/tcp` (included in deployment commands above)
- [x] Build & run: `docker compose up -d --build`
- [x] Verify: `curl http://localhost:8000/health` and open `http://YOUR_VPS_IP:8000` in a browser

**Outcome:** Dashboard is running on VPS. All 10 pages (Home, Universe, Run History, Portfolio, Opportunity, Order Management, Commands, World News, Costs, Roadmap), activity feed (SSE), and API are available at `http://YOUR_VPS_IP:8000`. Portfolio page includes Cash, Investments, Positions (T212 positions normalised for display), sector allocation, and chronological value history chart.

---

## Security Note

With VPS IP and HTTP:
- Use firewall to restrict access (e.g. only your IP) if desired.
- **Public vs operator split:** Only `/api/public/*` routes are anonymous. All trading controls, holdings, strategy data, runs, events, commands, and research remain operator-only.
- **Operator login:** Set these in `.env`:
  ```
  DASHBOARD_OPERATOR_USERNAME=<operator-username>
  DASHBOARD_OPERATOR_PASSWORD_HASH=<pbkdf2 hash>
  DASHBOARD_SESSION_SECRET=<random-hex-secret>
  DASHBOARD_INSECURE_DEV_MODE=false
  ```
  Generate the password hash with:
  ```bash
  poetry run python - <<'PY'
  from dashboard.backend.app.services.auth import hash_password
  print(hash_password("choose-a-strong-password"))
  PY
  ```
- **Transport requirement:** Operator login and operator API access are blocked over raw HTTP. Until TLS is available, use SSH tunnelling/VPN/local-only binding for operator work.
- **Public routes:** Use only the explicit public endpoints:
  - `/api/public/docs/*`
  - `/api/public/costs/*`
  - `/api/public/performance/*`
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
