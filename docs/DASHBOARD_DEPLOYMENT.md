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
| **Cloudflare + domain** (recommended) | One canonical HTTPS URL, operator login works safely, origin can stay internal-only behind Nginx | Requires DNS + reverse proxy setup |
| **VPS IP only** | No cost, no extra setup. Access via `http://YOUR_VPS_IP:8000` | No HTTPS; operator login over public HTTP is blocked by design |
| **Purchase domain (no Cloudflare)** | HTTPS via reverse proxy / Let's Encrypt, cleaner URL | More origin-facing ops than Cloudflare-proxied setup |
| **GitHub Pages** | Free static hosting | Not suitable: frontend must call VPS API. HTTPS page → HTTP API = mixed content blocked. Backend still needs VPS. |

**Recommended:** Use `https://zeninvest.zenouz.ai` behind Cloudflare-proxied DNS and an Nginx reverse proxy. Keep raw VPS/IP access only as an emergency or local fallback. See `docs/CLOUDFLARE_DASHBOARD_DOMAIN_PLAN.md`.

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

**Frontend API URL:** The frontend is served from the same origin as the API. Requests use relative paths (`/api/*`). The SSE activity feed uses `/api/events/stream` (same-origin), so it works through either the current VPS/IP path or the planned canonical domain path.

**Authentication:** Public, read-only routes live under `/api/public/*`. Operator routes require backend login and a signed session cookie. Operator login is blocked on plain HTTP except localhost-only development mode.

### VPS Firewall (one-time)

```bash
sudo ufw allow 8000/tcp comment "Dashboard"
sudo ufw reload
```

### Recommended: Cloudflare + nginx Reverse Proxy

Target production posture:
- Cloudflare proxied DNS for `zeninvest.zenouz.ai`
- nginx publishes `80/443`
- dashboard service is internal-only
- nginx proxies to the dashboard service and forwards `X-Forwarded-Proto: https`
- Disable buffering for SSE: `proxy_buffering off` on `/api/events/stream`

Detailed implementation/runbook: `docs/CLOUDFLARE_DASHBOARD_DOMAIN_PLAN.md`

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

Access from your machine:
- preferred: `https://zeninvest.zenouz.ai`
- fallback/emergency: `http://YOUR_VPS_IP:8000` only until the domain rollout is complete

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

Verify:
- `curl http://localhost:8000/health`
- open `https://zeninvest.zenouz.ai` once the domain rollout is complete
- or use `http://YOUR_VPS_IP:8000` only as the temporary pre-domain path

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
- [x] Firewall: `ufw allow 8000/tcp` for the current raw-dashboard path
- [x] Build & run: `docker compose up -d --build`
- [x] Verify: `curl http://localhost:8000/health` and open the dashboard in a browser

**Next hardening step:** `US-7.7 Dashboard HTTPS Domain & Canonical Access` moves the dashboard to `https://zeninvest.zenouz.ai`, adds Cloudflare + nginx, and removes public raw `:8000` exposure.

**Outcome:** Dashboard is running on VPS. Today it can run on the raw Docker/IP path; the planned production target is `https://zeninvest.zenouz.ai` with Cloudflare + nginx and no public `:8000` exposure. Portfolio page includes Cash, Investments, Positions (T212 positions normalised for display), sector allocation, and chronological value history chart.

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
- **CORS:** Dashboard API restricts cross-origin requests via `dashboard.cors_origins` in `config/settings.yaml`. Default: localhost only. For production, add the canonical HTTPS domain and keep localhost origins for local development:
  ```yaml
  dashboard:
    cors_origins:
      - "https://zeninvest.zenouz.ai"
      - "http://localhost:3000"
      - "http://localhost:8000"
  ```
- Dashboard Home has **Dry Run** and **Live Run** buttons; they call `POST /api/runs/trigger` and `POST /api/runs/trigger-live` respectively. Live Run requires confirmation.

## Related Notes

- [Dashboard System](DASHBOARD.md)
- [Cloudflare Dashboard Domain Plan](CLOUDFLARE_DASHBOARD_DOMAIN_PLAN.md)
- [Deployment (VPS)](DEPLOYMENT.md)
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md) — US-1.8
