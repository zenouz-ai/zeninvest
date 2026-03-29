---
title: Data Export Runbook
tags: [operations, export, vps, analysis]
status: active
last_updated: 2026-03-29
related: [DEPLOYMENT.md]
---

# Data Export Runbook

> Repeatable VPS-to-local export procedure for database, logs, journals, and config.

## Purpose

Ensure every investigation includes the full evidence set — database snapshot, logs, journals, config, and integrity manifest — exported safely from the VPS while the scheduler is running.

## 1) Create a timestamped export package on VPS

```bash
cd /home/deploy_invest_ai/investment-agent
TS=$(date -u +%Y%m%d_%H%M%S)
mkdir -p exports/$TS
```

## 2) Create a consistent SQLite snapshot

Use SQLite `.backup` so the snapshot is safe even while the scheduler is running.

```bash
docker compose exec investment-agent sh -lc "sqlite3 /app/data/investment_agent.db \".backup '/app/data/investment_agent_${TS}.db'\""
cp data/investment_agent_${TS}.db exports/$TS/
```

## 3) Export logs, journals, settings, and commit hash

```bash
docker compose logs --since 168h investment-agent > exports/$TS/docker_logs_7d.log
cp -r logs exports/$TS/logs
cp -r journals exports/$TS/journals
cp config/settings.yaml exports/$TS/settings.yaml
git rev-parse HEAD > exports/$TS/git_commit.txt
```

## 4) Add a row-count manifest (integrity check)

```bash
sqlite3 exports/$TS/investment_agent_${TS}.db "
SELECT 'system_state', COUNT(*) FROM system_state
UNION ALL SELECT 'instruments', COUNT(*) FROM instruments
UNION ALL SELECT 'market_data_cache', COUNT(*) FROM market_data_cache
UNION ALL SELECT 'news_sentiment_cache', COUNT(*) FROM news_sentiment_cache
UNION ALL SELECT 'strategy_decisions', COUNT(*) FROM strategy_decisions
UNION ALL SELECT 'moderation_logs', COUNT(*) FROM moderation_logs
UNION ALL SELECT 'risk_decisions', COUNT(*) FROM risk_decisions
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'portfolio_snapshots', COUNT(*) FROM portfolio_snapshots
UNION ALL SELECT 'opportunity_score_snapshots', COUNT(*) FROM opportunity_score_snapshots
UNION ALL SELECT 'opportunity_queue', COUNT(*) FROM opportunity_queue
UNION ALL SELECT 'cost_logs', COUNT(*) FROM cost_logs
UNION ALL SELECT 'api_logs', COUNT(*) FROM api_logs;
" > exports/$TS/row_counts.txt
```

## 5) Package and checksum

```bash
tar -C exports -czf exports/investment_export_${TS}.tgz $TS
sha256sum exports/investment_export_${TS}.tgz > exports/investment_export_${TS}.sha256
```

## 6) Copy to local machine

Run from your local machine:

```bash
scp deploy_invest_ai@<VPS_IP>:/home/deploy_invest_ai/investment-agent/exports/investment_export_${TS}.tgz ./local_analysis/
scp deploy_invest_ai@<VPS_IP>:/home/deploy_invest_ai/investment-agent/exports/investment_export_${TS}.sha256 ./local_analysis/
```

Optional integrity verify on local:

```bash
cd ./local_analysis
sha256sum -c investment_export_${TS}.sha256
```

## 7) Minimum dataset required for every investigation

Every investigation should include at least:

- `investment_agent_<timestamp>.db`
- `docker_logs_7d.log`
- `logs/` (component logs)
- `journals/` (trade rationale markdown)
- `settings.yaml`
- `git_commit.txt`
- `row_counts.txt`

## 8) Investigation checklist (coverage)

When analysing results, ensure all layers are used:

1. Signal generation: `strategy_decisions`
2. Moderation behavior: `moderation_logs`
3. Risk veto/resize outcomes: `risk_decisions`
4. Execution outcomes: `orders`
5. Opportunity ranking memory: `opportunity_score_snapshots`, `opportunity_queue`
6. Portfolio trajectory: `portfolio_snapshots`, `system_state`
7. API reliability: `api_logs`
8. Cost and budget behavior: `cost_logs`
9. Data availability context: `instruments`, `market_data_cache`, `news_sentiment_cache`

## Troubleshooting

- Do not copy a live `.db` file directly while writes are ongoing; use `.backup`.
- Keep timestamps in UTC when comparing scheduler events and DB rows.
- Never export `.env` in shared analysis bundles.

## Related Notes

- [Deployment (VPS)](DEPLOYMENT.md)
- [Dashboard Deployment](DASHBOARD_DEPLOYMENT.md)
- [Governance & Audit Trail](GOVERNANCE.md)

