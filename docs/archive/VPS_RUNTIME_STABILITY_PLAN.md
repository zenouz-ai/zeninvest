---
tags: [operations, vps, systemd, stability, hardening]
status: archived
last_updated: 2026-03-29
archived: true
---

# VPS Runtime Stability Plan

> **Archived 2026-03-29:** All hardening measures delivered (US-7.6). Runtime locks, bounded workers, and cycle guards are now part of the active codebase. See [DEPLOYMENT.md](DEPLOYMENT.md) for current operational guidance.

## Purpose

This document records the production-stability hardening delivered after the VPS experienced severe CPU saturation, elevated load average, and memory pressure caused by duplicate Python processes and overlapping long-running services. It is the authoritative implementation record for the runtime-safety work itself, regardless of whether the host is operated via Docker Compose or a lean non-Docker `systemd` layout.

**Current operational choice (2026-03-24):** production remains Docker-based on the VPS. The committed `systemd` units are an alternative deployment path, not the active control plane on the current host.

Use this document alongside:

- [Deployment & Monitoring Guide](DEPLOYMENT.md)
- [Solution Architecture](ARCHITECTURE.md)
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md)
- [VPS Systemd Runbook](VPS_SYSTEMD_RUNBOOK.md)

---

## Incident Summary

**Observed symptoms:**

- CPU pinned near 100% for extended periods
- Load average above 30 on a 1 vCPU host
- Memory pressure and general VPS unresponsiveness
- Multiple duplicate Python processes for the same deployment
- Immediate recovery after killing stray processes

**Long-running components in scope:**

1. FastAPI dashboard API (`python -m dashboard.backend.server`)
2. APScheduler service (`python -m src.scheduler.scheduler`)
3. Slack Socket Mode listener (`python -m src.agents.notifications.slack_trade_listener`)

---

## Likely Failure Mode

The incident was not one single bug; it was the interaction of several smaller runtime hazards on a resource-constrained machine.

### 1. Duplicate service starts were not blocked

Before hardening, the scheduler, API, and Slack listener did not take a hard runtime lock. If one service was started twice by deploy scripts, manual shell sessions, container restarts, or overlapping service managers, both instances could stay alive and compete for CPU, memory, SQLite, and network.

### 2. The API still had production-footgun entrypoints

Some dashboard start paths still used `uvicorn` with `reload=True`. Reload mode is correct for local development but intentionally creates extra Python processes (a reloader/supervisor plus worker process). On a tiny VPS this is wasted headroom and makes duplicate-process diagnosis harder.

### 3. Cycle execution could overlap across process boundaries

APScheduler jobs had `max_instances=1`, which protects only within one scheduler process. It does not stop:

- two scheduler processes from running at once
- a manual dashboard-triggered cycle overlapping with a scheduled cycle
- duplicate deploy starts from racing each other

### 4. Dashboard manual triggers used raw background threads

The API used direct `threading.Thread(...)` launches for manual dry-run/live cycles. That was simple, but it gave no bounded queue, no shared in-process guard, and no clear rejection path when a cycle was already running.

### 5. Slack listener created one thread per inbound message

The Slack Socket Mode listener acknowledged events quickly, but then spawned unbounded daemon threads per command/confirmation. On a bursty channel or after duplicate listener starts, that could create unnecessary thread pressure and noisy CPU usage.

### 6. SSE polling was too aggressive for idle VPS operation

The dashboard activity stream queried SQLite every second per connected client and held a long-lived DB session open. That is not catastrophic on its own, but it is unnecessary background churn on a 1 vCPU box.

### 7. Migrations were coupled to runtime startup paths

Some deployment flows chained `alembic upgrade head && <service start>`. That increases restart complexity and can make it harder to reason about whether a service was restarted cleanly or duplicated during deploys.

---

## Reliability Goals

The hardening work targeted the following constraints:

- one instance per service
- one orchestrator cycle at a time
- low idle CPU usage
- safe small-VPS defaults
- explicit restart behaviour
- no tight loops
- migrations handled separately from long-lived processes
- simple operations with either Docker Compose or `systemd`

---

## Current Production Posture

The codebase now supports two operational patterns:

### Active production posture

- **Docker Compose**
- `docker compose up -d --build`
- long-lived services remain containerised
- host-level app `systemd` units stay disabled

### Alternative posture

- **Non-Docker `systemd`**
- one service per long-lived component
- useful when explicitly migrating away from Docker

The runtime-safety code changes (locks, bounded workers, single-cycle guard, safer API entrypoint) still matter in both modes. What differs is which process manager owns startup and restart behaviour.

---

## Target Architecture

The new VPS runtime model is intentionally lean:

### Long-lived services

1. `investment-agent-api.service`
   Runs the FastAPI backend in a single locked process.
2. `investment-agent-scheduler.service`
   Owns APScheduler and all scheduled cycle execution.
3. `investment-agent-slack-listener.service`
   Owns Slack Socket Mode and command ingestion.

### One-shot service

4. `investment-agent-migrate.service`
   Runs Alembic migrations separately before services are restarted.

### Runtime invariants

- exactly one API process
- exactly one scheduler process
- exactly one Slack listener process
- at most one orchestrator cycle in flight across the whole machine

---

## Delivered Changes

## 1. Cross-process runtime locks

Added small Linux file-lock helpers in `src/runtime/locking.py`.

**What they protect:**

- `api.lock` for the dashboard API
- `scheduler.lock` for APScheduler
- `slack-listener.lock` for Slack Socket Mode
- `orchestrator-cycle.lock` for actual cycle execution

**Behaviour:**

- second instance fails fast
- lock metadata records owner PID and acquisition context
- duplicate service starts exit with a dedicated code so `systemd` can avoid restart loops

## 2. Production-safe API entrypoint

Added `dashboard/backend/server.py` as the canonical VPS API entrypoint.

**Key changes:**

- single process only
- `reload=False`
- `workers=1`
- guarded by `api.lock`

Legacy wrappers (`dashboard/backend/__main__.py`, `run_server.py`, `run_server_simple.py`, `run.sh`) now route to the safe entrypoint instead of keeping separate production behaviours.

## 3. Single-cycle execution guard

Updated `src/orchestrator/main.py` so every full cycle acquires `orchestrator-cycle.lock`.

**Effect:**

- scheduled and manual cycles cannot overlap
- duplicate scheduler processes cannot run concurrent cycles even if both somehow start
- the dashboard can reject a trigger cleanly instead of silently starting competing work

## 4. Bounded dashboard trigger dispatch

Added `dashboard/backend/app/services/run_dispatcher.py`.

**Effect:**

- manual dry-run/live triggers use one bounded background executor
- triggers return HTTP `409` when another cycle is already active
- raw ad-hoc thread spawning was removed from dashboard routes

## 5. Bounded Slack worker pool

Updated `src/agents/notifications/slack_listener.py` to use a `ThreadPoolExecutor` instead of creating one daemon thread per message.

**Default small-VPS posture:**

- `notifications.slack_trade_commands.worker_count: 1`

This keeps idle overhead tiny and prevents bursts from exploding thread count.

## 6. Lower idle dashboard load

Updated the SSE stream in `dashboard/backend/app/routers/events.py`.

**Changes:**

- poll interval moved from 1s to 5s
- disconnect detection added
- per-iteration DB sessions instead of one long-lived session
- configurable via `dashboard.sse_poll_interval_seconds`

## 7. Safer logging under VPS permissions drift

Updated `src/utils/logger.py` to fail open if a log file cannot be opened for writing. This avoids a single root-owned log file taking down app imports or tests.

## 8. Migrations separated from service startup

Added:

- `scripts/run_migrations.sh`
- `investment-agent-migrate.service`

The script uses a file lock so migrations themselves cannot overlap.

---

## systemd Layout

The committed units live in `deploy/systemd/`:

- `investment-agent-api.service`
- `investment-agent-scheduler.service`
- `investment-agent-slack-listener.service`
- `investment-agent-migrate.service`

**Shared design choices:**

- `Restart=on-failure`
- small restart backoff
- `RestartPreventExitStatus=75` for duplicate-instance exits
- explicit working directory and environment file
- writable access only to runtime data/log/journal paths
- journald-native logging

---

## Recommended Deploy Flow

```bash
cd /home/deploy_invest_ai/investment-agent
git pull
/home/deploy_invest_ai/.local/bin/poetry install

sudo systemctl stop investment-agent-slack-listener.service
sudo systemctl stop investment-agent-scheduler.service
sudo systemctl stop investment-agent-api.service

sudo systemctl start investment-agent-migrate.service

sudo systemctl start investment-agent-api.service
sudo systemctl start investment-agent-scheduler.service
sudo systemctl start investment-agent-slack-listener.service
```

This keeps migrations explicit and avoids mixing one-shot schema work with long-lived service startup.

---

## Observability & Verification

### Logs

```bash
journalctl -u investment-agent-api.service -f
journalctl -u investment-agent-scheduler.service -f
journalctl -u investment-agent-slack-listener.service -f
journalctl -u investment-agent-migrate.service -n 100
```

### Health

```bash
curl http://127.0.0.1:8000/health
systemctl status investment-agent-api.service
systemctl status investment-agent-scheduler.service
systemctl status investment-agent-slack-listener.service
```

### Confirm only one instance is running

```bash
pgrep -af "dashboard.backend|src.scheduler.scheduler|slack_trade_listener"
ls /home/deploy_invest_ai/investment-agent/data/runtime
```

Expected state:

- one API process
- one scheduler process
- one Slack listener process
- service lock files present
- `orchestrator-cycle.lock` appears only while a cycle is active

### Manual trigger expectations

When a cycle is already running:

- `POST /api/runs/trigger`
- `POST /api/runs/trigger-live`
- `POST /api/system/trigger-cycle`

should return `409 Another cycle is already running`.

---

## Uvicorn vs Gunicorn

For this VPS, keep plain `uvicorn` with one worker.

**Recommendation:** do **not** replace it with `gunicorn + uvicorn workers` on this machine.

Why:

- extra master/worker process overhead is not helpful on 1 vCPU
- the scheduler and Slack listener already share the same host
- the API workload is light and mostly operational, not high-throughput web traffic
- single-process simplicity makes duplicate-start diagnosis much easier

If the machine is upgraded substantially or the API is separated from the scheduler/listener, re-evaluating a multi-worker model would be reasonable.

---

## Verification Completed In-Repo

The hardening work was verified with:

- Python bytecode compilation of `src`, `dashboard/backend`, and `tests`
- focused runtime-lock, scheduler, Slack, dashboard-auth, and trigger-dispatch tests
- full backend test suite (`poetry run pytest -q`)
- frontend unit tests (`npm test`)
- frontend production build (`npm run build`)

See the delivery story in [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md) under `US-7.6`.

---

## Related Files

### Runtime and entrypoints

- `src/runtime/locking.py`
- `src/orchestrator/main.py`
- `src/scheduler/scheduler.py`
- `src/agents/notifications/slack_listener.py`
- `src/agents/notifications/slack_trade_listener.py`
- `dashboard/backend/server.py`
- `dashboard/backend/app/services/run_dispatcher.py`
- `dashboard/backend/app/routers/events.py`
- `dashboard/backend/app/routers/runs.py`
- `dashboard/backend/app/routers/system.py`

### Deployment artefacts

- `deploy/systemd/investment-agent-api.service`
- `deploy/systemd/investment-agent-scheduler.service`
- `deploy/systemd/investment-agent-slack-listener.service`
- `deploy/systemd/investment-agent-migrate.service`
- `scripts/run_migrations.sh`

### Supporting docs

- [VPS Systemd Runbook](VPS_SYSTEMD_RUNBOOK.md)
- [Deployment & Monitoring Guide](DEPLOYMENT.md)
- [Solution Architecture](ARCHITECTURE.md)
