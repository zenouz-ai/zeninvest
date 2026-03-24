---
tags: [operations, vps, systemd, runbook]
status: current
last_updated: 2026-03-24
---

# VPS Systemd Runbook

> Alternative non-Docker operating path. Use this only if you intentionally choose `systemd` instead of Docker Compose for production.

## Target Architecture

Run exactly three long-lived services on the VPS:

- `investment-agent-api.service`
  Runs FastAPI through a single locked `uvicorn` process.
- `investment-agent-scheduler.service`
  Runs APScheduler and owns scheduled portfolio cycles.
- `investment-agent-slack-listener.service`
  Runs Slack Socket Mode and processes commands through a bounded worker pool.

Run database migrations separately with:

- `investment-agent-migrate.service`

## Why This Layout

- Each service has a dedicated systemd unit.
- Each unit starts one process only.
- Each process takes an advisory runtime lock, so duplicate manual starts fail fast instead of silently competing.
- The orchestrator now takes a separate `orchestrator-cycle` lock, so dashboard-triggered runs and scheduled runs cannot overlap.

## Install Units

```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable investment-agent-api.service
sudo systemctl enable investment-agent-scheduler.service
sudo systemctl enable investment-agent-slack-listener.service
```

## Safe Deploy Sequence

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

## Health Checks

```bash
systemctl status investment-agent-api.service
systemctl status investment-agent-scheduler.service
systemctl status investment-agent-slack-listener.service
curl http://127.0.0.1:8000/health
pgrep -af "dashboard.backend|src.scheduler.scheduler|slack_trade_listener"
ls /home/deploy_invest_ai/investment-agent/data/runtime
```

Expected:

- one API process
- one scheduler process
- one Slack listener process
- one `api.lock`, one `scheduler.lock`, one `slack-listener.lock`
- at most one `orchestrator-cycle.lock` while a cycle is actually running

## Logs

```bash
journalctl -u investment-agent-api.service -f
journalctl -u investment-agent-scheduler.service -f
journalctl -u investment-agent-slack-listener.service -f
journalctl -u investment-agent-migrate.service -n 100
```

## Uvicorn Recommendation

Keep `uvicorn` as a single process on this VPS.

- `gunicorn` + `uvicorn` workers adds an extra master process and invites multiple workers.
- On 1 vCPU / 4 GB RAM, the scheduler and Slack listener already consume part of the machine budget.
- Use one API worker unless you later move the scheduler/listener off-box or upgrade the server.
