---
tags: [dashboard, deployment, vps, docker]
status: delivered
last_updated: 2026-03-29
---

# Dashboard Deployment

> VPS deployment plan for the 12-page monitoring dashboard (US-1.8 + US-7.7 + US-7.8).

## Purpose

Deploy the dashboard backend (FastAPI + SSE) and frontend (built SPA) on the VPS behind a canonical HTTPS ingress, sharing the agent's SQLite database.

## Domain / Access Options

| Option | Pros | Cons |
|--------|------|------|
| **Cloudflare + domain** (recommended) | One canonical HTTPS URL, operator login works safely, origin can stay internal-only behind Nginx | Requires DNS + reverse proxy setup |
| **VPS IP only** | Useful as an emergency rollback posture | Not the target production ingress; public `:8000` exposure should be removed in normal operation |
| **Purchase domain (no Cloudflare)** | HTTPS via reverse proxy / Let's Encrypt, cleaner URL | More origin-facing ops than Cloudflare-proxied setup |
| **GitHub Pages** | Free static hosting | Not suitable: frontend must call VPS API. HTTPS page → HTTP API = mixed content blocked. Backend still needs VPS. |

**Recommended:** Use `https://zeninvest.zenouz.ai` behind Cloudflare-proxied DNS and an Nginx reverse proxy. Keep raw VPS/IP access only as an operational rollback. See `docs/CLOUDFLARE_DASHBOARD_DOMAIN_PLAN.md`.

---

## Docker Architecture

Four services in `docker-compose.yml`, using two app Dockerfiles plus an Nginx ingress:

| Service | Dockerfile | Purpose | Entry point |
|---------|-----------|---------|-------------|
| `investment-agent` | `Dockerfile.agent` | Python-only — runs scheduler | `alembic upgrade head && python -m src.scheduler.scheduler` |
| `slack-listener` | `Dockerfile.agent` | Python-only — keeps Slack Socket Mode connected | `alembic upgrade head && python -m src.agents.notifications.slack_trade_listener` |
| `dashboard` | `Dockerfile` | Multi-stage (Node + Python) — builds frontend, runs FastAPI | `python -m dashboard.backend.server` |
| `nginx` | `nginx:alpine` | Public ingress, TLS termination, canonical host enforcement | `/etc/nginx/conf.d/default.conf` |

The three app services share the same SQLite DB via `./data` volume. The `dashboard` service is internal-only on the Compose network and is reachable publicly only through the `nginx` service on `80/443`.

- `Dockerfile.agent`: Python 3.12-slim, Poetry deps, application code. No Node.js, no frontend build.
- `Dockerfile`: Stage 1 (Node 20-slim) builds the React/Vite frontend with no secrets injected at build time. Stage 2 (Python 3.12-slim) installs Poetry deps, copies app code + built frontend dist.

**Frontend API URL:** The frontend is served from the same origin as the API. Requests use relative paths (`/api/*`). The SSE activity feed uses `/api/events/stream` (same-origin), so it works through the canonical HTTPS domain and any localhost/dev tunnel using the same-origin path.

**Authentication:** Public, read-only routes live under `/api/public/*`, including dedicated sanitized feeds for Overview, Universe, Portfolio, Runs, Opportunity, Costs, and World News plus roadmap docs. Order Management, Chat, and Evolution are visible publicly only as disabled preview surfaces. Operator routes require backend login and a signed session cookie. Operator login is blocked on plain HTTP except localhost-only development mode.

**Hardening visibility:** Order rows can now include `warning_note` for off-hours submissions, and status/system payloads expose HALTED auto-recovery progress plus any active peak-inflation warning note for dashboard alerts.

### Cloudflare and TLS prerequisites

```bash
mkdir -p /home/deploy_invest_ai/certs/zeninvest.zenouz.ai
chmod 700 /home/deploy_invest_ai/certs/zeninvest.zenouz.ai
```

Cloudflare dashboard settings:
- proxied `A` record: `zeninvest` -> VPS public IP
- SSL/TLS mode: `Full (strict)`
- enable `Always Use HTTPS`
- do not enable HSTS, Cloudflare Tunnel, or Cloudflare Access in this story

Origin cert files on VPS:
- `/home/deploy_invest_ai/certs/zeninvest.zenouz.ai/origin.crt`
- `/home/deploy_invest_ai/certs/zeninvest.zenouz.ai/origin.key`

Suggested permissions:

```bash
chmod 600 /home/deploy_invest_ai/certs/zeninvest.zenouz.ai/origin.key
chmod 644 /home/deploy_invest_ai/certs/zeninvest.zenouz.ai/origin.crt
```

---

## Deployment Commands (VPS)

Run from the project directory on the VPS (e.g. `/home/deploy/investment-agent`). Use `main` or your deployment branch (e.g. `feature/dashboard-full-spec`) as appropriate.

```bash
cd /home/deploy/investment-agent
git fetch origin
git pull origin main   # or: git pull origin feature/dashboard-full-spec

# Ensure dashboard enabled in config/settings.yaml
# dashboard.enabled: true, dashboard.events_enabled: true

# Ensure dashboard auth is production-safe
# DASHBOARD_INSECURE_DEV_MODE=false in .env

# Firewall: canonical HTTPS ingress only
sudo ufw allow 80/tcp comment "Dashboard HTTP redirect"
sudo ufw allow 443/tcp comment "Dashboard HTTPS"
sudo ufw delete allow 8000/tcp || true
sudo ufw reload

docker compose up -d --build

docker compose ps
docker compose exec nginx nginx -t
```

Access from your machine:
- preferred: `https://zeninvest.zenouz.ai`
- fallback/emergency: `http://YOUR_VPS_IP:8000` only if you intentionally revert Compose and firewall settings as part of rollback

### Updating / Rebuilding the dashboard

After code changes (frontend or backend), rebuild and restart:

```bash
cd /home/deploy/investment-agent   # or your project path
git pull origin main
docker compose up -d --build
```

To rebuild only the dashboard service (keeps agent + ingress running):

```bash
docker compose up -d --build dashboard
```

Verify:
- `docker compose exec nginx nginx -t`
- open `https://zeninvest.zenouz.ai`
- confirm `/api/public/*` loads anonymously
- confirm operator login succeeds only on HTTPS

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

- [x] Code: scheduler + always-on Slack listener + internal-only dashboard + public nginx services in docker-compose; multi-stage frontend build; FastAPI serves SPA
- [x] Config: `dashboard.enabled: true`, `dashboard.events_enabled: true` in `config/settings.yaml`
- [x] Cloudflare DNS + TLS: proxied `A` record, `Full (strict)`, `Always Use HTTPS`, Cloudflare Origin CA cert installed on VPS
- [x] Firewall: `80/tcp` and `443/tcp` open; public `8000/tcp` removed
- [x] Build & run: `docker compose up -d --build`
- [x] Verify: `docker compose exec nginx nginx -t`, open the dashboard in a browser, and confirm HTTPS login + anonymous public routes

**Outcome:** Dashboard is running on VPS at `https://zeninvest.zenouz.ai` with Cloudflare + nginx and no public raw `:8000` exposure. Signed-out visitors can browse the full product navigation, but every anonymous tab is intentionally either a sanitized live view (Overview, Universe, Portfolio, Runs, Opportunity, Costs, World News, Roadmap) or a disabled preview surface (Order Management, Chat, Evolution). Operator pages and controls remain authenticated.

---

## Verification and Rollback

Verification:
- `http://zeninvest.zenouz.ai` returns `301` to `https://zeninvest.zenouz.ai`
- `https://zeninvest.zenouz.ai/health` returns `200`
- `/api/public/*` remains anonymous
- operator login works on `https://zeninvest.zenouz.ai`
- protected routes return `401/403` when signed out
- SSE-backed activity feed updates through the canonical domain
- raw public `http://YOUR_VPS_IP:8000` no longer works

Rollback:
- stop/remove the `nginx` service from Compose
- restore `dashboard` port publishing on `8000`
- reopen firewall `8000/tcp`
- redeploy with `docker compose up -d --build`
- use the raw path only until HTTPS ingress is fixed

## Security Note

With the canonical HTTPS domain:
- **Public vs operator split:** Anonymous access is limited to intentionally exposed `/api/public/*` read models and disabled preview surfaces. Public live routes cover roadmap docs, performance snapshot, universe, portfolio, runs, opportunity, sanitized Insights guidance, costs, and World News / macro read models. Trading controls, events, chat execution, evolution planning, research, strategy-attribution review, and all mutation endpoints remain operator-only.
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
- **Transport requirement:** Operator login and operator API access are blocked over raw HTTP. Production requires HTTPS via the canonical domain; localhost-only development can still use `DASHBOARD_INSECURE_DEV_MODE=true`.
- **Public routes:** Use only the explicit public endpoints:
  - `/api/public/docs/*`
  - `/api/public/costs/*`
  - `/api/public/performance/*`
  - `/api/public/universe`
  - `/api/public/portfolio`
  - `/api/public/portfolio/history`
  - `/api/public/runs`
  - `/api/public/opportunity`
  - `/api/public/insights/guidance/latest`
  - `/api/public/insights/guidance/history`
  - `/api/public/macro/*`
- **CORS:** Dashboard API restricts cross-origin requests via `dashboard.cors_origins` in `config/settings.yaml`. Default: `https://zeninvest.zenouz.ai` plus localhost dev origins. If you override it, keep the canonical HTTPS domain and localhost origins:
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
