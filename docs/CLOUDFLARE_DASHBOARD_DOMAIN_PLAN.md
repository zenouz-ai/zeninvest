---
tags: [dashboard, deployment, cloudflare, nginx, docker, security]
status: planned
last_updated: 2026-03-24
---

# Cloudflare Domain Rollout for `zeninvest.zenouz.ai`

## Summary

Migrate the dashboard from raw VPS/IP access to one canonical public URL: `https://zeninvest.zenouz.ai`.

Tomorrow’s implementation should keep the current hybrid access model:
- public overview remains anonymous
- operator dashboard pages and trading controls remain login-protected
- operator login works only over HTTPS on the domain
- direct public access to port `8000` is removed

The implementation should follow the current Docker Compose production posture and add a Dockerized Nginx reverse proxy in front of the existing `dashboard` service. Cloudflare should front the site with a proxied DNS record and SSL/TLS `Full (strict)` using a Cloudflare Origin CA certificate installed on Nginx.

## Implementation Changes

### 1. Save the migration plan in docs first

Create and maintain this tracked doc: `docs/CLOUDFLARE_DASHBOARD_DOMAIN_PLAN.md`

This doc should remain the implementation/runbook for the story and include:
- target URL: `https://zeninvest.zenouz.ai`
- current state: dashboard exposed on raw VPS IP/port `8000`
- target architecture: Cloudflare proxied DNS -> Nginx (TLS) -> internal dashboard service
- exact Cloudflare dashboard steps
- exact VPS/Docker/Nginx steps
- verification checklist
- rollback steps back to raw Docker port exposure if needed

### 2. Add a new roadmap story

Add a new roadmap story with this exact shape:

- ID: `US-7.7`
- Name: `Dashboard HTTPS Domain & Canonical Access`
- Topic: `Hardening`
- Status: `pipeline`
- Effort: `M`
- Priority: `P0`
- Horizon: `Next`
- Timebox: `2`
- Description: `Expose the dashboard at https://zeninvest.zenouz.ai via Cloudflare-proxied DNS and Nginx TLS termination; keep public overview anonymous, keep operator routes session-protected, remove public port 8000 exposure, enforce canonical host access, and update deployment/runbook documentation.`
- Architecture components: `['Dashboard', 'Docker', 'FastAPI', 'Nginx', 'Cloudflare']`

Update both:
- `docs/SOPHISTICATION_ROADMAP.md`
- `dashboard/frontend/src/data/roadmap.ts`

### 3. Cloudflare and DNS design

Use lowercase as the canonical hostname: `zeninvest.zenouz.ai`.

Cloudflare steps to document and implement:
- Create proxied `A` record:
  - name: `zeninvest`
  - content: VPS public IP
  - proxy status: proxied/orange cloud
- SSL/TLS mode: `Full (strict)`
- Enable `Always Use HTTPS`
- Do not use raw IP as a public operator entrypoint anymore
- Do not use Cloudflare Tunnel in this story
- Do not add Cloudflare Access/SSO in this story
- Do not enable HSTS in the first rollout; defer until the domain flow is confirmed healthy

Origin certificate choice:
- Use a Cloudflare Origin CA certificate
- Certificate hostname: `zeninvest.zenouz.ai` only
- Install on Nginx, not inside the FastAPI app
- Store cert/key outside git, under a fixed VPS path such as `/home/deploy_invest_ai/certs/zeninvest.zenouz.ai/`

### 4. Docker and reverse proxy changes

Keep the dashboard app in Docker Compose, but stop exposing it publicly.

Required Docker changes:
- Add an `nginx` service to `docker-compose.yml`
- Publish only:
  - `80:80`
  - `443:443`
- Remove public `8000:8000` publishing from the `dashboard` service
- Replace it with internal-only reachability:
  - either `expose: ["8000"]`
  - or no published port if the compose network is sufficient
- Nginx proxies to the compose service name `dashboard:8000`

Nginx behavior:
- HTTP `:80`:
  - for `zeninvest.zenouz.ai`, redirect to `https://zeninvest.zenouz.ai$request_uri`
  - for raw IP/unknown hosts on port 80, redirect to `https://zeninvest.zenouz.ai$request_uri`
- HTTPS `:443`:
  - serve only `zeninvest.zenouz.ai`
  - use the Cloudflare Origin CA cert/key
  - proxy all requests to `dashboard:8000`
  - pass:
    - `Host`
    - `X-Real-IP`
    - `X-Forwarded-For`
    - `X-Forwarded-Proto https`
- SSE support:
  - disable proxy buffering on `/api/events/stream`
  - set a long proxy read timeout
- Unknown-host handling on `443`:
  - use a default server that returns a non-proxy response (for example `404` or `444`)
  - do not proxy unknown hosts to the dashboard app

### 5. App/runtime adjustments

Adjust the dashboard app/config so it works cleanly behind an HTTPS reverse proxy.

Required app/config changes:
- Keep session-based operator auth
- Preserve the current hybrid anonymous/public split under `/api/public/*`
- Ensure operator auth treats proxied HTTPS correctly via `X-Forwarded-Proto`
- Do not rely on port-based “canonical” enforcement once Nginx is in front
- Move canonical access enforcement to host/scheme handling at Nginx
- Update `dashboard.cors_origins` defaults/config to include:
  - `https://zeninvest.zenouz.ai`
  - existing localhost dev origins for local development only

Firewall/network posture after rollout:
- close public `8000/tcp`
- open `80/tcp` and `443/tcp`
- keep local/internal access for the compose network only

## Documentation Updates

Update the docs to make the domain path the recommended production posture:

- `docs/DASHBOARD_DEPLOYMENT.md`
  - replace “VPS IP only recommended” guidance
  - make Cloudflare + domain + HTTPS the recommended path
  - keep raw VPS IP only as emergency/local fallback
- `docs/DEPLOYMENT.md`
  - update dashboard deployment section to point to the domain-based flow
- `README.md`
  - update dashboard deployment/access wording from raw IP to canonical domain
- `docs/ARCHITECTURE.md`
  - update dashboard hosting/auth notes to reflect Cloudflare + Nginx + internal-only origin
- `docs/SOPHISTICATION_ROADMAP.md`
  - add `US-7.7`
- `dashboard/frontend/src/data/roadmap.ts`
  - add the same story for the Roadmap page

## Test Plan

### Repo/runtime verification
- `docker compose config` passes
- `nginx -t` passes inside the proxy container or build context
- dashboard container remains healthy
- scheduler and slack listener remain unaffected

### HTTP/HTTPS behavior
- `http://zeninvest.zenouz.ai` -> `301` to `https://zeninvest.zenouz.ai`
- `https://zeninvest.zenouz.ai/login` -> `200`
- public overview loads anonymously on the domain
- operator login succeeds over `https://zeninvest.zenouz.ai`
- operator login over raw public HTTP still fails
- direct public `http://VPS_IP:8000` no longer works
- SSE activity feed still updates through the proxied domain

### Auth and app behavior
- `/api/public/*` remains accessible anonymously on the domain
- protected operator routes still return signed-out/unauthorized responses when not logged in
- after login, dashboard pages load correctly over the domain
- cookies are marked secure in the HTTPS path

### Rollback validation
Document and verify a rollback path:
- remove/disable Nginx service
- restore `dashboard` port publishing on `8000`
- revert docs/roadmap changes only if the rollout is abandoned, not for temporary operational rollback

## Assumptions and Defaults

- Canonical hostname is `zeninvest.zenouz.ai` in lowercase
- Access model remains hybrid, not operator-only
- Ingress model is Cloudflare proxied DNS + Nginx, not Cloudflare Tunnel
- TLS at origin uses Cloudflare Origin CA, not Let’s Encrypt
- Nginx is added as a Docker Compose service, not as a host-native service
- Public raw port `8000` exposure is removed in the target state
- Cloudflare Access/SSO, WAF tuning, and Cloudflare-IP-only origin firewalling are out of scope for this first rollout and can be follow-up hardening work
