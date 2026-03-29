---
tags: [dashboard, deployment, cloudflare, nginx, docker, security]
status: delivered
last_updated: 2026-03-29
---

# Cloudflare Domain Rollout for `zeninvest.zenouz.ai`

## Summary

`US-7.7 Dashboard HTTPS Domain & Canonical Access` shipped on `2026-03-25`.

The dashboard now uses one canonical production URL:

- `https://zeninvest.zenouz.ai`

The delivered posture is:

- Cloudflare proxied DNS in front of the VPS
- SSL/TLS mode `Full (strict)`
- Dockerized `nginx` as the only public ingress on `80/443`
- internal-only `dashboard` service on the Compose network (`expose: 8000`)
- canonical host/scheme enforcement at nginx
- anonymous access exposes the full tab map, but each public page is intentionally either a sanitized live view or a disabled preview surface
- operator pages and controls still protected by session auth over proxied HTTPS
- no public raw `:8000` exposure in the target state

## Delivered Architecture

```text
Cloudflare proxied DNS
  -> nginx:alpine (80/443)
  -> dashboard:8000 (internal-only on Compose network)
```

Key runtime pieces:

- `docker-compose.yml`
  - `dashboard` uses `expose: ["8000"]`
  - `nginx` publishes `80:80` and `443:443`
- `deploy/nginx/conf.d/default.conf`
  - redirects HTTP to `https://zeninvest.zenouz.ai`
  - redirects unknown hosts on `:80` to the canonical host
  - serves only the canonical host on `:443`
  - forwards `X-Forwarded-Proto: https`
  - disables proxy buffering on `/api/events/stream`

## Cloudflare Settings

Delivered settings:

- proxied `A` record: `zeninvest` -> VPS public IP
- SSL/TLS mode: `Full (strict)`
- `Always Use HTTPS`: enabled
- no Cloudflare Tunnel in this rollout
- no Cloudflare Access/SSO in this rollout
- HSTS intentionally deferred until the path is proven stable

Origin certificate placement:

- `/home/deploy_invest_ai/certs/zeninvest.zenouz.ai/origin.crt`
- `/home/deploy_invest_ai/certs/zeninvest.zenouz.ai/origin.key`

## Verification Checklist

Repository/runtime checks:

- `docker compose config`
- `docker compose exec nginx nginx -t`

Expected HTTP/HTTPS behavior:

- `http://zeninvest.zenouz.ai` -> `301` to `https://zeninvest.zenouz.ai`
- `https://zeninvest.zenouz.ai/health` -> `200`
- anonymous read-only pages load on the canonical host
- operator login succeeds over `https://zeninvest.zenouz.ai`
- direct public `http://YOUR_VPS_IP:8000` no longer works in the target posture
- SSE activity feed still works through the proxied domain

Expected auth behavior:

- `/api/public/*` remains anonymous
- protected `/api/*` routes return signed-out/unauthorized responses without a session
- operator login is blocked over raw HTTP outside localhost-only insecure dev mode

## Rollback Posture

Rollback is operational only and does not change the intended target architecture.

If HTTPS ingress fails and operator access must be restored temporarily:

1. remove or disable the `nginx` service
2. re-publish `dashboard` on `8000:8000`
3. reopen `8000/tcp` only for the duration of the rollback
4. restore the canonical HTTPS path as soon as the ingress issue is fixed

Raw VPS/IP access is rollback-only and is not the recommended production posture.
