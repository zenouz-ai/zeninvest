---
tags: [deployment, vps, docker, monitoring, operations]
status: current
last_updated: 2026-03-11
---

# Deployment & Monitoring Guide

> VPS deployment, Docker setup, monitoring, backups, and data retrieval for the investment agent.

## Purpose

This guide covers end-to-end deployment of the investment agent on a VPS: server setup, Docker and non-Docker paths, monitoring, log management, backups, updates, troubleshooting, data retrieval for local analysis, backtesting on VPS, and dashboard deployment.

> Path and username note: examples use `/home/deploy` and user `deploy`. If your VPS user differs (for example `deploy_invest_ai`), replace those values consistently in all commands and service files.

---

## Table of Contents

1. [VPS Requirements](#1-vps-requirements)
2. [Initial Server Setup](#2-initial-server-setup)
3. [Docker Deployment (Recommended)](#3-docker-deployment-recommended)
4. [Non-Docker Deployment](#4-non-docker-deployment)
5. [Monitoring](#5-monitoring)
6. [Log Management](#6-log-management)
7. [Backup Strategy](#7-backup-strategy)
8. [Updating](#8-updating)
9. [Troubleshooting](#9-troubleshooting)
10. [Retrieving Activity Data](#10-retrieving-activity-data)
11. [Backtesting on VPS](#11-backtesting-on-vps)
12. [Transferring Project to VPS](#12-transferring-project-to-vps)
13. [Dashboard VPS Deployment](#13-dashboard-vps-deployment)

---

## 1. VPS Requirements

### Minimum Specs

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 1 GB | 2 GB |
| Storage | 10 GB SSD | 20 GB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| Network | Unrestricted outbound HTTPS | Unrestricted outbound HTTPS |

### Why These Specs

- **RAM**: The docker-compose file enforces a 2 GB memory limit. Each analysis cycle loads pandas DataFrames, runs three LLM calls (Anthropic, OpenAI, Google), and processes market data. 2 GB provides comfortable headroom.
- **CPU**: Analysis cycles are I/O-bound (API calls), so 1 vCPU works. 2 vCPU helps when yfinance downloads overlap with LLM calls.
- **Storage**: The SQLite database grows slowly (market data cache is pruned). Logs and journals accumulate over months. 20 GB gives a year of runway with logrotate in place.
- **Network**: The agent makes outbound HTTPS calls only. For the dashboard, inbound port 8000 (or 80 via nginx) is needed. See [§13 Dashboard VPS Deployment](#13-dashboard-vps-deployment).

### Recommended Providers

Any provider offering Ubuntu 22.04/24.04 with SSD storage works: Hetzner, DigitalOcean, Vultr, Linode, OVH. Choose a data center geographically close to London for lowest latency to the Trading 212 API.

---

## 2. Initial Server Setup

### 2.1 Create a Non-Root User

```bash
# As root on a fresh server
adduser deploy
usermod -aG sudo deploy

# Copy SSH keys
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

### 2.2 SSH Hardening

Edit `/etc/ssh/sshd_config`:

```
# Disable root login
PermitRootLogin no

# Disable password authentication (use key-based only)
PasswordAuthentication no
ChallengeResponseAuthentication no

# Limit to deploy user
AllowUsers deploy

# Change default port (optional but recommended)
Port 2222
```

Restart SSH:

```bash
sudo systemctl restart sshd
```

> **Important**: Test SSH access with the new settings in a separate terminal before closing your current session.

### 2.3 Firewall (UFW)

```bash
# Allow SSH (adjust port if changed)
sudo ufw allow 2222/tcp comment "SSH"

# Enable firewall -- no inbound HTTP/HTTPS needed
sudo ufw enable
sudo ufw status verbose
```

Expected output:

```
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)

To                         Action      From
--                         ------      ----
2222/tcp                   ALLOW IN    Anywhere        # SSH
```

### 2.4 Install fail2ban

```bash
sudo apt update && sudo apt install -y fail2ban

sudo tee /etc/fail2ban/jail.local > /dev/null <<'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = 2222
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 7200
EOF

sudo systemctl enable fail2ban
sudo systemctl restart fail2ban
```

### 2.5 Automatic Security Updates

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 2.6 Set Timezone to UTC

The scheduler runs all jobs in UTC. Keep the server clock aligned:

```bash
sudo timedatectl set-timezone UTC
```

---

## 3. Docker Deployment (Recommended)

### 3.1 Install Docker

```bash
# Install Docker Engine (official method)
sudo apt update
sudo apt install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Allow deploy user to run Docker without sudo
sudo usermod -aG docker deploy
newgrp docker
```

### 3.2 Clone the Repository

```bash
cd /home/deploy
git clone <repo-url> investment-agent
cd investment-agent
```

### 3.3 Configure Environment

```bash
cp config/.env.example .env
```

Edit `.env` with your API keys:

```env
T212_API_KEY=your_trading212_api_key
T212_API_SECRET=your_trading212_api_secret
ANTHROPIC_API_KEY=sk-ant-your-key
OPENAI_API_KEY=sk-your-key
GOOGLE_AI_API_KEY=AIyour-key
FINNHUB_API_KEY=your_finnhub_key
ALPHA_VANTAGE_API_KEY=your_av_key
```

Optional (recommended) for chat alerts:

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
ALERT_EMAIL_FROM=agent@yourdomain.com
ALERT_EMAIL_TO=ops@yourdomain.com
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USER=your_smtp_user
SMTP_PASS=your_smtp_password
SMTP_USE_TLS=true
```

For production email delivery, use a transactional SMTP provider (for example SendGrid/Postmark/Resend SMTP) with `SMTP_PORT=587` and `SMTP_USE_TLS=true`.

Optional for batch universe enrichment (Brave/Tavily + Gemini):

```env
BRAVE_SEARCH_API_KEY=your_brave_search_key
BRAVE_ANSWER_API_KEY=your_brave_answer_key
TAVILY_API_KEY=your_tavily_key
```

Each has a 2,000 calls/month limit (config: `search_api_limits`). Omit if not using enrichment.

**Costs (as of 2026-03):** Brave Search $5/1k requests (free $5 credits/month); Brave Answers $4/1k queries + token costs (free $5 credits/month); Tavily pay-as-you-go $0.008/credit (2,000 calls ≈ $16) or Project plan $30/month for 4,000 credits.

**Planned (US-1.6 — Slack natural language trade commands):** When implemented, inbound Slack will require `SLACK_APP_TOKEN` (xapp-…) and `SLACK_BOT_TOKEN` (xoxb-…), and an optional long-running `slack_trade_listener` process or container. See `docs/CHAT_AND_COMMANDS.md`.

Secure the file:

```bash
chmod 600 .env
```

### 3.4 Review Settings

Review `config/settings.yaml` and adjust if needed. Key parameters:

```yaml
trading:
  mode: practice                          # practice or live
  cycle_frequency: intraday                # intraday (3 cycles) or standard (2 cycles)
  cycle_times_utc: ["08:00", "12:00", "16:00"]  # when intraday; ["07:00", "19:00"] when standard
cost_limits:
  anthropic_daily_gbp: 1.00
  openai_daily_gbp: 0.75
  google_daily_gbp: 0.50
  total_monthly_gbp: 50.00
notifications:
  enabled: true
  channels: ["slack", "email"]
  routes:
    trade_instruction_approved: ["slack"]
    trade_execution_result: ["slack", "email"]
    cycle_run_summary: ["slack"]
    state_transition: ["slack", "email"]
    critical_cycle_failure: ["slack", "email"]
  timeout_seconds: 5
  max_retries: 2
  dedup_window_seconds: 300
  include_dry_run_alerts: false
  command_gateway:
    enabled: false
```

### 3.5 Build and Start

```bash
docker compose up -d --build
```

This will:
1. Build the Docker image (Python 3.12-slim, Poetry dependencies, application code).
2. Run Alembic database migrations on startup.
3. Start the APScheduler-based scheduler as the main process.
4. Mount `./data`, `./journals`, and `./logs` as volumes for persistence.
5. Apply a 2 GB memory limit.
6. Restart automatically on failure (`restart: always`).

### 3.6 Verify

```bash
# Check container is running
docker compose ps

# Check health status
docker inspect --format='{{.State.Health.Status}}' investment-agent

# View startup logs
docker compose logs --tail=50 investment-agent

# Confirm scheduled jobs are registered
docker compose logs investment-agent 2>&1 | grep "Scheduled jobs" -A 5
```

You should see output like:

```
Investment Agent Scheduler starting...
Scheduled jobs:
  - analysis_cycle_0800: cron[...]   # (and 1200, 1600 when intraday; or 0700, 1900 when standard)
  - daily_snapshot: cron[...]
  - weekly_report: cron[...]
  - instrument_refresh: cron[...]
```

### 3.7 Manual Cycle Validation (Recommended)

Before relying on scheduler-only execution, trigger one manual dry cycle and one manual live cycle. You can use either the dashboard buttons or CLI:

**Option A: Dashboard** (when dashboard is running)
- Open `http://VPS_IP:8000` → click **Dry Run** or **Live Run** (Live Run requires confirmation)
- Calls `POST /api/runs/trigger` or `POST /api/runs/trigger-live`; cycle runs in the dashboard container

**Option B: CLI**
```bash
# Dry cycle (no real trades)
docker compose run --rm investment-agent python -m src.orchestrator.main --dry-run

# Live cycle (Practice account)
docker compose run --rm investment-agent python -m src.orchestrator.main
```

Then scan logs for auth/order errors:

```bash
docker compose logs investment-agent 2>&1 | grep -Ei "401|403|404|invalid_api_key|unauthorized|forbidden|error"
```

### 3.8 Notification Verification

After the dry-run and live/practice validation cycles, verify notification delivery and audit logs:

```bash
# Confirm recent notification attempts
docker compose exec investment-agent sqlite3 /app/data/investment_agent.db \
"SELECT timestamp,event_type,channel,status,attempt_number,error_message
 FROM notification_logs
 ORDER BY id DESC LIMIT 30;"

# Optional: focus on failures only
docker compose exec investment-agent sqlite3 /app/data/investment_agent.db \
"SELECT timestamp,event_type,channel,status,error_message
 FROM notification_logs
 WHERE status='failed'
 ORDER BY id DESC LIMIT 20;"
```

Expected outcomes:
- Slack rows should be present with `status='sent'`.
- Email rows should be present with `status='sent'`.
- Duplicates inside dedup windows can appear as `status='deduped'` by design.
- If a provider is intentionally not configured, rows may appear as `status='skipped'`.

---

## 4. Non-Docker Deployment

Use this approach if you prefer running directly on the host (useful for debugging or resource-constrained VPS).

### 4.1 Install Python 3.11+ via pyenv

```bash
# Install build dependencies
sudo apt update
sudo apt install -y make build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
  libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
  libffi-dev liblzma-dev git

# Install pyenv
curl https://pyenv.run | bash

# Add to shell profile (~/.bashrc)
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init -)"' >> ~/.bashrc
source ~/.bashrc

# Install Python 3.12 (matching Dockerfile) and set as default
pyenv install 3.12
pyenv global 3.12
```

### 4.2 Install Poetry and Dependencies

```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Add to PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Clone and install
cd /home/deploy
git clone <repo-url> investment-agent
cd investment-agent

poetry install --without dev
```

### 4.3 Configure Environment

```bash
cp config/.env.example .env
chmod 600 .env
# Edit .env with your API keys (same as Docker section 3.3)
```

### 4.4 Initialize Database

```bash
cd /home/deploy/investment-agent
poetry run alembic upgrade head
```

### 4.5 Test a Dry Run

```bash
poetry run python -m src.orchestrator.main --dry-run
```

### 4.6 Create a systemd Service

Create `/etc/systemd/system/investment-agent.service`:

```ini
[Unit]
Description=Investment Agent Scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/investment-agent
Environment="PATH=/home/deploy/.pyenv/versions/3.12/bin:/home/deploy/.local/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/home/deploy/investment-agent/.env
ExecStart=/home/deploy/.local/bin/poetry run python -m src.scheduler.scheduler
Restart=always
RestartSec=30

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/deploy/investment-agent/data
ReadWritePaths=/home/deploy/investment-agent/journals
ReadWritePaths=/home/deploy/investment-agent/logs

# Resource limits
MemoryMax=2G
CPUQuota=150%

# Graceful shutdown
KillSignal=SIGTERM
TimeoutStopSec=30

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=investment-agent

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable investment-agent
sudo systemctl start investment-agent
sudo systemctl status investment-agent
```

### 4.7 Verify Scheduler Operation

```bash
# View live logs
journalctl -u investment-agent -f

# Check scheduled jobs registered
journalctl -u investment-agent | grep "Scheduled jobs" -A 5
```

---

## 5. Monitoring

### 5.1 Live Log Monitoring

**Docker deployment:**

```bash
# Follow all logs
docker compose logs -f investment-agent

# Last 100 lines
docker compose logs --tail=100 investment-agent

# Filter for errors
docker compose logs investment-agent 2>&1 | grep -i "error\|failed\|exception"

# Filter for trade activity
docker compose logs investment-agent 2>&1 | grep -i "order\|trade\|filled\|BUY\|SELL"
```

**systemd deployment:**

```bash
# Follow live
journalctl -u investment-agent -f

# Last hour
journalctl -u investment-agent --since "1 hour ago"

# Today only
journalctl -u investment-agent --since today

# Errors only
journalctl -u investment-agent -p err

# Specific cycle (search by time window)
journalctl -u investment-agent --since "07:00" --until "07:30"
```

### 5.2 Per-Component Log Files

The application writes individual log files to `logs/` with format `YYYY-MM-DD HH:MM:SS | component | LEVEL | message`:

```bash
# Key log files to monitor
tail -f logs/scheduler.log          # Scheduler events
tail -f logs/orchestrator.log       # Cycle orchestration
tail -f logs/strategy_engine.log    # Strategy decisions
tail -f logs/order_manager.log      # Order placement and fills
tail -f logs/risk_manager.log       # Risk checks and vetoes
tail -f logs/cost_tracker.log       # LLM cost tracking
tail -f logs/t212_client.log        # Trading 212 API calls
tail -f logs/moderation_panel.log   # Moderator consensus

# Check for recent errors across all logs
grep -r "ERROR\|CRITICAL" logs/ --include="*.log" | tail -20
```

### 5.3 SQLite Database Inspection

Connect to the database for live inspection:

```bash
# Docker
docker compose exec investment-agent sqlite3 /app/data/investment_agent.db

# Non-Docker
sqlite3 /home/deploy/investment-agent/data/investment_agent.db
```

**System state:**

```sql
-- Current system state (ACTIVE, CAUTIOUS, or HALTED)
SELECT state, current_drawdown_pct, last_cycle_at, paused, notes
FROM system_state
ORDER BY id DESC
LIMIT 1;
```

**Recent trades:**

```sql
-- Last 20 orders
SELECT timestamp, ticker, action, quantity, price, value_gbp, status, strategy, conviction
FROM orders
ORDER BY timestamp DESC
LIMIT 20;

-- Failed orders (investigate errors)
SELECT timestamp, ticker, action, status, error_message
FROM orders
WHERE status IN ('failed', 'cancelled')
ORDER BY timestamp DESC
LIMIT 10;
```

**LLM cost monitoring:**

```sql
-- Today's spend by provider
SELECT provider, model,
       COUNT(*) as calls,
       SUM(input_tokens) as total_input,
       SUM(output_tokens) as total_output,
       ROUND(SUM(cost_gbp), 4) as total_gbp
FROM cost_logs
WHERE date(timestamp) = date('now')
GROUP BY provider, model;

-- Monthly spend totals
SELECT provider,
       COUNT(*) as calls,
       ROUND(SUM(cost_gbp), 4) as total_gbp
FROM cost_logs
WHERE timestamp >= date('now', 'start of month')
GROUP BY provider;

-- Daily spend trend (last 7 days)
SELECT date(timestamp) as day,
       ROUND(SUM(cost_gbp), 4) as total_gbp
FROM cost_logs
WHERE timestamp >= date('now', '-7 days')
GROUP BY date(timestamp)
ORDER BY day;
```

**Portfolio snapshots:**

```sql
-- Latest portfolio snapshot
SELECT timestamp, total_value_gbp, cash_gbp, invested_gbp,
       pnl_gbp, pnl_pct, alpha_pct, num_positions, state
FROM portfolio_snapshots
ORDER BY timestamp DESC
LIMIT 1;

-- Portfolio value over last 30 days
SELECT date(timestamp) as day,
       ROUND(total_value_gbp, 2) as value,
       ROUND(pnl_pct, 2) as pnl_pct,
       ROUND(alpha_pct, 2) as alpha_pct,
       num_positions
FROM portfolio_snapshots
WHERE timestamp >= date('now', '-30 days')
ORDER BY timestamp;
```

**API errors:**

```sql
-- Recent API failures
SELECT timestamp, service, method, endpoint, status_code, error
FROM api_logs
WHERE error IS NOT NULL
ORDER BY timestamp DESC
LIMIT 20;

-- API call volume by service (today)
SELECT service,
       COUNT(*) as calls,
       SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as errors,
       ROUND(AVG(duration_ms), 0) as avg_ms
FROM api_logs
WHERE date(timestamp) = date('now')
GROUP BY service;
```

### 5.4 Health Check Monitoring Script

Create `/home/deploy/investment-agent/scripts/health_check.sh`:

```bash
#!/usr/bin/env bash
# Investment Agent Health Check Script
# Run via cron every 15 minutes: */15 * * * * /home/deploy/investment-agent/scripts/health_check.sh
set -euo pipefail

PROJECT_DIR="/home/deploy/investment-agent"
DB_PATH="${PROJECT_DIR}/data/investment_agent.db"
LOG_FILE="${PROJECT_DIR}/logs/health_check.log"
ALERT_EMAIL="${ALERT_EMAIL:-}"  # Set in environment or leave empty to skip email

log() {
    echo "$(date -u '+%Y-%m-%d %H:%M:%S') | health_check | $1" >> "${LOG_FILE}"
}

alert() {
    local message="$1"
    log "ALERT: ${message}"

    if [[ -n "${ALERT_EMAIL}" ]]; then
        echo "${message}" | mail -s "[Investment Agent] Health Alert" "${ALERT_EMAIL}" 2>/dev/null || true
    fi
}

ISSUES=0

# --- Check 1: Process Running ---
if docker compose -f "${PROJECT_DIR}/docker-compose.yml" ps --status running | grep -q investment-agent; then
    log "OK: Container running"
else
    # Fallback: check systemd service
    if systemctl is-active --quiet investment-agent 2>/dev/null; then
        log "OK: systemd service running"
    else
        alert "CRITICAL: Investment agent is not running!"
        ISSUES=$((ISSUES + 1))
    fi
fi

# --- Check 2: Recent Cycle Activity ---
# On weekdays, a cycle should have run within the last 14 hours
DAY_OF_WEEK=$(date -u +%u)  # 1=Monday, 7=Sunday
if [[ ${DAY_OF_WEEK} -le 5 ]]; then
    LAST_CYCLE=$(sqlite3 "${DB_PATH}" \
        "SELECT MAX(timestamp) FROM strategy_decisions;" 2>/dev/null || echo "")

    if [[ -n "${LAST_CYCLE}" ]]; then
        LAST_EPOCH=$(date -d "${LAST_CYCLE}" +%s 2>/dev/null || echo 0)
        NOW_EPOCH=$(date +%s)
        HOURS_AGO=$(( (NOW_EPOCH - LAST_EPOCH) / 3600 ))

        if [[ ${HOURS_AGO} -gt 14 ]]; then
            alert "WARNING: Last analysis cycle was ${HOURS_AGO} hours ago (${LAST_CYCLE})"
            ISSUES=$((ISSUES + 1))
        else
            log "OK: Last cycle ${HOURS_AGO}h ago"
        fi
    else
        log "INFO: No strategy decisions found yet"
    fi
else
    log "INFO: Weekend -- skipping cycle freshness check"
fi

# --- Check 3: Database Size and Integrity ---
if [[ -f "${DB_PATH}" ]]; then
    DB_SIZE_MB=$(du -m "${DB_PATH}" | cut -f1)
    log "INFO: Database size: ${DB_SIZE_MB} MB"

    if [[ ${DB_SIZE_MB} -gt 500 ]]; then
        alert "WARNING: Database is ${DB_SIZE_MB} MB -- consider vacuuming"
        ISSUES=$((ISSUES + 1))
    fi

    # Quick integrity check
    INTEGRITY=$(sqlite3 "${DB_PATH}" "PRAGMA integrity_check;" 2>/dev/null || echo "error")
    if [[ "${INTEGRITY}" != "ok" ]]; then
        alert "CRITICAL: Database integrity check failed: ${INTEGRITY}"
        ISSUES=$((ISSUES + 1))
    else
        log "OK: Database integrity check passed"
    fi
else
    alert "CRITICAL: Database file not found at ${DB_PATH}"
    ISSUES=$((ISSUES + 1))
fi

# --- Check 4: Disk Space ---
DISK_USAGE_PCT=$(df "${PROJECT_DIR}" | tail -1 | awk '{print $5}' | tr -d '%')
if [[ ${DISK_USAGE_PCT} -gt 90 ]]; then
    alert "CRITICAL: Disk usage at ${DISK_USAGE_PCT}%"
    ISSUES=$((ISSUES + 1))
elif [[ ${DISK_USAGE_PCT} -gt 80 ]]; then
    alert "WARNING: Disk usage at ${DISK_USAGE_PCT}%"
    ISSUES=$((ISSUES + 1))
else
    log "OK: Disk usage at ${DISK_USAGE_PCT}%"
fi

# --- Check 5: LLM Cost Budget ---
MONTHLY_SPEND=$(sqlite3 "${DB_PATH}" \
    "SELECT COALESCE(ROUND(SUM(cost_gbp), 2), 0)
     FROM cost_logs
     WHERE timestamp >= date('now', 'start of month');" 2>/dev/null || echo "0")
MONTHLY_LIMIT="50.00"

if (( $(echo "${MONTHLY_SPEND} > ${MONTHLY_LIMIT}" | bc -l) )); then
    alert "CRITICAL: Monthly LLM spend (GBP ${MONTHLY_SPEND}) exceeds limit (GBP ${MONTHLY_LIMIT})"
    ISSUES=$((ISSUES + 1))
elif (( $(echo "${MONTHLY_SPEND} > ${MONTHLY_LIMIT} * 0.8" | bc -l) )); then
    alert "WARNING: Monthly LLM spend at GBP ${MONTHLY_SPEND} / GBP ${MONTHLY_LIMIT} (>80%)"
    ISSUES=$((ISSUES + 1))
else
    log "OK: Monthly LLM spend: GBP ${MONTHLY_SPEND} / GBP ${MONTHLY_LIMIT}"
fi

# --- Check 6: Recent Errors in Logs ---
ERROR_COUNT=$(grep -c "ERROR\|CRITICAL" "${PROJECT_DIR}/logs/orchestrator.log" 2>/dev/null \
    | tail -1 || echo "0")
# Count errors in last hour only
RECENT_ERRORS=$(grep "ERROR\|CRITICAL" "${PROJECT_DIR}/logs/orchestrator.log" 2>/dev/null \
    | awk -v cutoff="$(date -u -d '1 hour ago' '+%Y-%m-%d %H:%M:%S')" '$0 >= cutoff' \
    | wc -l || echo "0")

if [[ ${RECENT_ERRORS} -gt 10 ]]; then
    alert "WARNING: ${RECENT_ERRORS} errors in orchestrator.log in the last hour"
    ISSUES=$((ISSUES + 1))
else
    log "OK: ${RECENT_ERRORS} errors in last hour"
fi

# --- Check 7: System State ---
SYSTEM_STATE=$(sqlite3 "${DB_PATH}" \
    "SELECT state FROM system_state ORDER BY id DESC LIMIT 1;" 2>/dev/null || echo "UNKNOWN")
if [[ "${SYSTEM_STATE}" == "HALTED" ]]; then
    alert "CRITICAL: System state is HALTED -- drawdown threshold breached, all positions liquidated"
    ISSUES=$((ISSUES + 1))
elif [[ "${SYSTEM_STATE}" == "CAUTIOUS" ]]; then
    log "WARNING: System state is CAUTIOUS -- drawdown detected"
fi

# --- Summary ---
if [[ ${ISSUES} -eq 0 ]]; then
    log "SUMMARY: All checks passed"
else
    log "SUMMARY: ${ISSUES} issue(s) detected"
fi

exit ${ISSUES}
```

Make it executable and schedule via cron:

```bash
chmod +x /home/deploy/investment-agent/scripts/health_check.sh

# Run every 15 minutes
crontab -e
# Add:
*/15 * * * * /home/deploy/investment-agent/scripts/health_check.sh
```

---

## 6. Log Management

### 6.1 Logrotate Configuration

Create `/etc/logrotate.d/investment-agent`:

```
/home/deploy/investment-agent/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 deploy deploy
    dateext
    dateformat -%Y%m%d

    # Do not use copytruncate with Python logging;
    # the agent recreates file handles on next write.
    # If issues occur, switch to copytruncate.
}
```

Test the configuration:

```bash
sudo logrotate -d /etc/logrotate.d/investment-agent    # Dry run
sudo logrotate -f /etc/logrotate.d/investment-agent    # Force run
```

### 6.2 Disk Usage Monitoring

Quick commands to check disk usage:

```bash
# Total project disk usage
du -sh /home/deploy/investment-agent/

# Breakdown by directory
du -sh /home/deploy/investment-agent/data/
du -sh /home/deploy/investment-agent/logs/
du -sh /home/deploy/investment-agent/journals/

# Database size
ls -lh /home/deploy/investment-agent/data/investment_agent.db

# Largest log files
ls -lhS /home/deploy/investment-agent/logs/

# SQLite WAL file size (can grow large under load)
ls -lh /home/deploy/investment-agent/data/investment_agent.db-wal 2>/dev/null
```

### 6.3 SQLite WAL Maintenance

The database uses WAL (Write-Ahead Logging) mode for better concurrent access. Periodically checkpoint the WAL to keep it from growing:

```bash
# Manual WAL checkpoint
sqlite3 /home/deploy/investment-agent/data/investment_agent.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Vacuum to reclaim space (run monthly or when DB exceeds 200 MB)
sqlite3 /home/deploy/investment-agent/data/investment_agent.db "VACUUM;"
```

---

## 7. Backup Strategy

### 7.1 Database Backup Script

Create `/home/deploy/investment-agent/scripts/backup.sh`:

```bash
#!/usr/bin/env bash
# Investment Agent Backup Script
# Backs up SQLite database and journals to a timestamped archive.
# Run daily via cron: 0 2 * * * /home/deploy/investment-agent/scripts/backup.sh
set -euo pipefail

PROJECT_DIR="/home/deploy/investment-agent"
DB_PATH="${PROJECT_DIR}/data/investment_agent.db"
JOURNALS_DIR="${PROJECT_DIR}/journals"
BACKUP_DIR="${PROJECT_DIR}/backups"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Create backup directory
mkdir -p "${BACKUP_DIR}/daily"

# --- Database Backup ---
# Use SQLite .backup command for a consistent snapshot (safe even while running)
BACKUP_DB="${BACKUP_DIR}/daily/investment_agent_${TIMESTAMP}.db"
sqlite3 "${DB_PATH}" ".backup '${BACKUP_DB}'"

# Compress the backup
gzip "${BACKUP_DB}"
echo "$(date -u '+%Y-%m-%d %H:%M:%S') | Database backed up: ${BACKUP_DB}.gz ($(du -h "${BACKUP_DB}.gz" | cut -f1))" \
    >> "${PROJECT_DIR}/logs/backup.log"

# --- Journal Archive ---
# Archive journals weekly (only on Sundays)
if [[ $(date -u +%u) -eq 7 ]]; then
    JOURNAL_ARCHIVE="${BACKUP_DIR}/daily/journals_${TIMESTAMP}.tar.gz"
    tar -czf "${JOURNAL_ARCHIVE}" -C "${PROJECT_DIR}" journals/
    echo "$(date -u '+%Y-%m-%d %H:%M:%S') | Journals archived: ${JOURNAL_ARCHIVE} ($(du -h "${JOURNAL_ARCHIVE}" | cut -f1))" \
        >> "${PROJECT_DIR}/logs/backup.log"
fi

# --- Cleanup Old Backups ---
find "${BACKUP_DIR}/daily" -name "*.gz" -mtime +${RETENTION_DAYS} -delete
find "${BACKUP_DIR}/daily" -name "*.tar.gz" -mtime +${RETENTION_DAYS} -delete

REMAINING=$(find "${BACKUP_DIR}/daily" -type f | wc -l)
echo "$(date -u '+%Y-%m-%d %H:%M:%S') | Cleanup complete. ${REMAINING} backup files retained." \
    >> "${PROJECT_DIR}/logs/backup.log"
```

Make it executable and schedule:

```bash
chmod +x /home/deploy/investment-agent/scripts/backup.sh

crontab -e
# Add: run at 02:00 UTC daily
0 2 * * * /home/deploy/investment-agent/scripts/backup.sh
```

### 7.2 Off-Server Backup (Optional)

For critical deployments, push backups to an off-server location:

```bash
# rsync to a second server
rsync -avz /home/deploy/investment-agent/backups/ backup-server:/backups/investment-agent/

# Or to an S3-compatible bucket (install awscli or rclone)
rclone sync /home/deploy/investment-agent/backups/ remote:investment-agent-backups/
```

### 7.3 Restore from Backup

```bash
# Stop the agent
docker compose down
# or: sudo systemctl stop investment-agent

# Restore database
gunzip -k backups/daily/investment_agent_20260101_020000.db.gz
cp backups/daily/investment_agent_20260101_020000.db data/investment_agent.db

# Restart
docker compose up -d
# or: sudo systemctl start investment-agent
```

---

## 8. Updating

### 8.1 Docker Deployment Update

```bash
cd /home/deploy/investment-agent

# Pull latest code
git fetch origin
git pull origin main

# Review changes (especially config/settings.yaml and migrations)
git log --oneline HEAD@{1}..HEAD

# Rebuild and restart (zero-downtime is not required since the agent is idle between cycles)
docker compose down
docker compose up -d --build

# Verify
docker compose logs --tail=30 investment-agent
docker compose ps
```

### 8.2 Non-Docker Update

```bash
cd /home/deploy/investment-agent

# Pull latest code
git fetch origin
git pull origin main

# Update dependencies
poetry install --without dev

# Run any new migrations
poetry run alembic upgrade head

# Restart the service
sudo systemctl restart investment-agent
journalctl -u investment-agent -f --since "1 minute ago"
```

### 8.3 Rollback

If an update causes issues:

```bash
# Check what changed
git log --oneline -5

# Revert to previous commit
git checkout <previous-commit-hash>

# Docker
docker compose down && docker compose up -d --build

# Non-Docker
poetry install --without dev
sudo systemctl restart investment-agent
```

> **Note on migrations**: Alembic migrations are forward-only by convention in this project. If a migration causes issues, you may need to run `poetry run alembic downgrade -1` before reverting the code, or restore the database from backup.

---

## 9. Troubleshooting

### 9.1 API Key Errors

**Symptom**: Logs show `Missing required environment variable: T212_API_KEY` or `401 Unauthorized`.

**Diagnosis**:

```bash
# Docker: check .env is loaded
docker compose exec investment-agent env | grep -E "T212|ANTHROPIC|OPENAI|GOOGLE|FINNHUB|ALPHA"

# Non-Docker: check systemd environment
sudo systemctl show investment-agent | grep EnvironmentFile
```

**Fix**: Verify all keys in `.env` are set and have no trailing whitespace or quotes:

```bash
# Good
T212_API_KEY=abc123

# Bad (quotes are included as part of the value)
T212_API_KEY="abc123"

# Bad (OpenAI key accidentally duplicated prefix)
OPENAI_API_KEY=sk-sk-proj-...

# Good (OpenAI project key)
OPENAI_API_KEY=sk-proj-...
```

After editing `.env`:

```bash
# Docker
docker compose down && docker compose up -d

# Non-Docker
sudo systemctl restart investment-agent
```

If keys were ever pasted into chat, screenshots, or public logs, rotate/revoke them in provider dashboards before restarting the service.

### 9.2 Rate Limiting

**Symptom**: Logs show `429 Too Many Requests` or `RateLimitError` from LLM providers.

**Diagnosis**:

```sql
-- Check API call frequency
SELECT service,
       strftime('%H', timestamp) as hour,
       COUNT(*) as calls,
       SUM(CASE WHEN status_code = 429 THEN 1 ELSE 0 END) as rate_limited
FROM api_logs
WHERE date(timestamp) = date('now')
GROUP BY service, hour
ORDER BY service, hour;
```

**Fix**: The application uses `tenacity` for retries with exponential backoff. If rate limiting persists:

- Check that you are not running multiple instances of the agent.
- Reduce the number of instruments being analyzed (increase `min_conviction` in `config/settings.yaml`).
- Check your API plan limits with the provider.

### 9.3 Memory Issues

**Symptom**: Container killed by OOM or `MemoryError` in logs.

**Diagnosis**:

```bash
# Docker: check memory usage
docker stats investment-agent --no-stream

# Check for OOM kills
dmesg | grep -i "oom\|killed" | tail -10

# Non-Docker
journalctl -u investment-agent | grep -i "memory\|oom\|killed"
```

**Fix**:

- Increase the memory limit in `docker-compose.yml` (change `memory: 2G` to `memory: 3G`).
- For systemd, increase `MemoryMax` in the service file.
- Check for large DataFrames in `market_data_cache` that may need pruning:

```sql
-- Check cache size
SELECT data_type, COUNT(*), SUM(LENGTH(data_json)) / 1048576.0 as size_mb
FROM market_data_cache
GROUP BY data_type;

-- Prune expired cache entries
DELETE FROM market_data_cache WHERE expires_at < datetime('now');
```

### 9.4 Stale APScheduler Job Locks

**Symptom**: Scheduled jobs stop running. Logs show the scheduler is alive but no jobs fire.

**Diagnosis**:

```sql
-- Check APScheduler job store (SQLAlchemy-backed)
SELECT * FROM apscheduler_jobs;
```

**Fix**:

```bash
# Docker
docker compose restart investment-agent

# Non-Docker
sudo systemctl restart investment-agent
```

If restarts do not resolve it, clear the job store and restart:

```bash
sqlite3 /home/deploy/investment-agent/data/investment_agent.db "DELETE FROM apscheduler_jobs;"

# Then restart the agent -- jobs will be re-registered on startup
docker compose restart investment-agent
```

### 9.5 Runs stuck as RUNNING

**Symptom**: Dashboard and Run History show runs with status "RUNNING" (blue) or "Running..." even after the cycle has completed.

**Cause**: The scheduler or orchestrator failed to update the Run record to "completed" when the cycle finished (e.g. DB lock, exception in update block, process killed before commit). The update is fail-open, so the pipeline continues but the Run stays "running".

**Fix (automatic)**: The dashboard backend now **reconciles** stale runs when fetching: any run that has been "running" for more than 15 minutes and has `strategy_decisions` for its cycle_id is marked "completed". Refresh the dashboard or Run History — the next fetch will reconcile and display correctly.

**Fix (manual)** — if reconcile does not run (e.g. no strategy_decisions):

```python
# Mark specific run as completed (e.g. after verifying it finished)
poetry run python -c "
from src.data.database import get_session
from dashboard.backend.app.database import Run
from datetime import datetime, timezone
session = get_session()
run = session.query(Run).filter(Run.cycle_id == 'scheduled_20260313_120014').first()
if run and run.status == 'running':
    run.status = 'completed'
    run.completed_at = datetime.now(timezone.utc)
    session.commit()
    print('Updated')
session.close()
"
```

**Diagnosis**: Check orchestrator/scheduler logs for `Failed to update Run record (fail-open)` — now logged at WARNING level.

### 9.5a CAUTIOUS triggered incorrectly (few decisions, no real drawdown)

**Symptom**: Runs produce only 2–3 decisions (positions only), state shows CAUTIOUS, but you have not had a real drawdown meeting cautious_drawdown_pct.

**Cause**: Peak portfolio value may have been set incorrectly (e.g. from a data glitch, fallback calculation difference, or Practice account reset). Drawdown is measured from peak, so an inflated peak yields a false positive.

**Fix** — reset peak to current value and return to ACTIVE:

```bash
# CLI
poetry run python -m src.orchestrator.main --reset-peak
```

Or from the Dashboard: when state shows CAUTIOUS, a "Reset Peak" button appears next to the badge. Click it and confirm — peak is set to current portfolio value and state transitions to ACTIVE.

**API**: `POST /api/system/reset-peak` (requires T212 connection to read current value).

### 9.6 Database Locked Errors

**Symptom**: `sqlite3.OperationalError: database is locked`.

**Diagnosis**: This occurs when multiple processes try to write simultaneously. The WAL mode (configured in `src/data/database.py`) should prevent most cases.

**Fix**:

- Ensure only one instance of the agent is running.
- If running manual SQLite queries while the agent is active, use read-only mode:

```bash
sqlite3 -readonly /home/deploy/investment-agent/data/investment_agent.db
```

- Force a WAL checkpoint:

```bash
sqlite3 /home/deploy/investment-agent/data/investment_agent.db "PRAGMA wal_checkpoint(RESTART);"
```

### 9.7 Trading 212 API Issues

**Symptom**: Orders fail with `Connection refused` or unexpected status codes.

**Diagnosis**:

```sql
-- Recent T212 API errors
SELECT timestamp, method, endpoint, status_code, error, duration_ms
FROM api_logs
WHERE service = 't212' AND error IS NOT NULL
ORDER BY timestamp DESC
LIMIT 10;
```

**Common causes**:

- **Practice mode maintenance**: T212 practice API has occasional downtime. The agent will retry on the next cycle.
- **API key rotation**: T212 keys expire. Generate a new key in the T212 dashboard and update `.env`.
- **Order rejected**: Check `error_message` in the `orders` table for T212 rejection reasons (insufficient funds, instrument not tradeable, market closed).

### 9.8 Container Will Not Start

**Symptom**: `docker compose up -d` starts but the container exits immediately.

**Diagnosis**:

```bash
# Check exit code
docker compose ps -a

# View full startup logs
docker compose logs investment-agent

# Check for migration errors
docker compose logs investment-agent 2>&1 | grep -i "alembic\|migration\|error"
```

**Common causes**:

- **Migration error**: A migration fails due to schema conflict. Restore the database from backup or fix the migration.
- **Import error**: A missing dependency. Rebuild with `docker compose build --no-cache`.
- **Permission error**: Volume mount permissions. Ensure the `data/`, `journals/`, and `logs/` directories exist and are writable.

### 9.9 Run History polluted with test data (historical)

**Symptom**: Run History shows many failed runs with `error_message: "boom"` or `FakeOrchestrator` — these are from tests that previously wrote to the production DB.

**Note**: As of 2026-03, `conftest.py` sets `INVESTMENT_AGENT_USE_INMEMORY_DB=1` so pytest uses in-memory SQLite; new test runs no longer pollute production.

**Cleanup** (removes test-artifact runs; keep real runs):

```bash
# Local
poetry run python -c "
import sqlite3
conn = sqlite3.connect('data/investment_agent.db')
cur = conn.execute(\"DELETE FROM runs WHERE summary_json LIKE '%boom%' OR summary_json LIKE '%FakeOrchestrator%'\")
conn.commit()
print(f'Deleted {cur.rowcount} test-pollution rows')
conn.close()
"
```

### 9.10 SMTP TLS Mismatch (`STARTTLS extension not supported by server`)

**Symptom**: `notification_logs` contains repeated email failures with `error_message` like `STARTTLS extension not supported by server`.

**Diagnosis**: The SMTP server does not support STARTTLS while `SMTP_USE_TLS=true` is configured.

**Fix**:
- For production transactional SMTP on port `587`, keep `SMTP_USE_TLS=true`.
- For local mail sinks (Mailpit/MailHog/debug SMTP server), set `SMTP_USE_TLS=false`.
- Restart the service after `.env` changes:

```bash
# Docker
docker compose down && docker compose up -d

# Non-Docker
sudo systemctl restart investment-agent
```

---

## 10. Retrieving Activity Data

### 10.1 Pull Database and Journals to Local Machine

Use `scp` or `rsync` to copy data from the VPS to your local machine for analysis.

**Single file (database):**

```bash
# Adjust port (-P) if SSH is on a non-default port
scp -P 2222 deploy@your-vps-ip:/home/deploy/investment-agent/data/investment_agent.db ./local_analysis/

# Or with a specific SSH key
scp -P 2222 -i ~/.ssh/my_key deploy@your-vps-ip:/home/deploy/investment-agent/data/investment_agent.db ./local_analysis/
```

**Full journals directory:**

```bash
# rsync is better for directories -- only transfers new/changed files
rsync -avz -e "ssh -p 2222" \
    deploy@your-vps-ip:/home/deploy/investment-agent/journals/ \
    ./local_analysis/journals/
```

**Database + journals + logs in one command:**

```bash
rsync -avz -e "ssh -p 2222" \
    deploy@your-vps-ip:/home/deploy/investment-agent/data/investment_agent.db \
    deploy@your-vps-ip:/home/deploy/investment-agent/journals/ \
    deploy@your-vps-ip:/home/deploy/investment-agent/logs/ \
    ./local_analysis/
```

**Pull the latest backup instead (safer, no risk of copying during write):**

```bash
# Get latest backup
LATEST=$(ssh -p 2222 deploy@your-vps-ip \
    "ls -t /home/deploy/investment-agent/backups/daily/investment_agent_*.db.gz | head -1")
scp -P 2222 deploy@your-vps-ip:"${LATEST}" ./local_analysis/
gunzip ./local_analysis/investment_agent_*.db.gz
```

### 10.2 Sample SQLite Queries for Local Analysis

Once you have the database locally, open it with any SQLite client:

```bash
sqlite3 ./local_analysis/investment_agent.db
```

**Complete trade history with P&L:**

```sql
-- All filled orders with details
SELECT
    o.timestamp,
    o.ticker,
    o.action,
    o.quantity,
    ROUND(o.price, 2) as fill_price,
    ROUND(o.value_gbp, 2) as value_gbp,
    o.strategy,
    o.conviction,
    o.moderation_result,
    o.risk_result
FROM orders o
WHERE o.status = 'filled'
ORDER BY o.timestamp;
```

**Trade count and volume by ticker:**

```sql
SELECT
    ticker,
    SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buys,
    SUM(CASE WHEN action IN ('SELL', 'REDUCE') THEN 1 ELSE 0 END) as sells,
    ROUND(SUM(value_gbp), 2) as total_volume_gbp,
    MIN(timestamp) as first_trade,
    MAX(timestamp) as last_trade
FROM orders
WHERE status = 'filled'
GROUP BY ticker
ORDER BY total_volume_gbp DESC;
```

**Portfolio performance over time:**

```sql
SELECT
    date(timestamp) as date,
    ROUND(total_value_gbp, 2) as portfolio_value,
    ROUND(cash_gbp, 2) as cash,
    ROUND(pnl_pct, 2) as pnl_pct,
    ROUND(benchmark_pnl_pct, 2) as benchmark_pct,
    ROUND(alpha_pct, 2) as alpha_pct,
    num_positions,
    state
FROM portfolio_snapshots
ORDER BY timestamp;
```

**Total LLM costs by provider and month:**

```sql
SELECT
    strftime('%Y-%m', timestamp) as month,
    provider,
    COUNT(*) as api_calls,
    SUM(input_tokens) as input_tokens,
    SUM(output_tokens) as output_tokens,
    ROUND(SUM(cost_gbp), 4) as cost_gbp
FROM cost_logs
GROUP BY month, provider
ORDER BY month, provider;
```

**Cost per analysis cycle:**

```sql
SELECT
    cycle_id,
    MIN(timestamp) as started,
    COUNT(*) as llm_calls,
    ROUND(SUM(cost_gbp), 4) as cycle_cost_gbp,
    GROUP_CONCAT(DISTINCT provider) as providers
FROM cost_logs
WHERE cycle_id IS NOT NULL
GROUP BY cycle_id
ORDER BY started DESC
LIMIT 20;
```

**Strategy decision analysis:**

```sql
-- Win/loss analysis: trades that ended in profit vs loss
SELECT
    sd.primary_strategy,
    COUNT(*) as decisions,
    AVG(sd.conviction) as avg_conviction,
    SUM(CASE WHEN sd.action = 'BUY' THEN 1 ELSE 0 END) as buys,
    SUM(CASE WHEN sd.action = 'SELL' THEN 1 ELSE 0 END) as sells,
    AVG(sd.upside_target_pct) as avg_upside_target,
    AVG(sd.stop_loss_pct) as avg_stop_loss
FROM strategy_decisions sd
GROUP BY sd.primary_strategy;
```

**Moderation panel effectiveness:**

```sql
-- How often do moderators agree vs disagree?
SELECT
    moderator,
    verdict,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY moderator), 1) as pct
FROM moderation_logs
GROUP BY moderator, verdict
ORDER BY moderator, count DESC;

-- Consensus outcomes
SELECT
    consensus,
    COUNT(*) as count
FROM moderation_logs
WHERE consensus IS NOT NULL
GROUP BY consensus;
```

**Risk agent veto analysis:**

```sql
-- How often does risk veto or resize?
SELECT
    verdict,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM risk_decisions), 1) as pct
FROM risk_decisions
GROUP BY verdict;

-- Most common triggered rules
SELECT
    triggered_rules_json,
    COUNT(*) as times_triggered
FROM risk_decisions
WHERE triggered_rules_json IS NOT NULL
  AND triggered_rules_json != '[]'
GROUP BY triggered_rules_json
ORDER BY times_triggered DESC
LIMIT 10;
```

**Daily activity summary:**

```sql
-- Activity summary by day
SELECT
    date(o.timestamp) as day,
    COUNT(DISTINCT o.id) as orders,
    SUM(CASE WHEN o.action = 'BUY' THEN 1 ELSE 0 END) as buys,
    SUM(CASE WHEN o.action IN ('SELL', 'REDUCE') THEN 1 ELSE 0 END) as sells,
    ROUND(SUM(o.value_gbp), 2) as volume_gbp,
    (SELECT ROUND(SUM(c.cost_gbp), 4)
     FROM cost_logs c
     WHERE date(c.timestamp) = date(o.timestamp)) as llm_cost_gbp
FROM orders o
WHERE o.status = 'filled'
GROUP BY date(o.timestamp)
ORDER BY day DESC;
```

### 10.3 Export to CSV

For analysis in spreadsheets or Python notebooks:

```bash
# Export portfolio history to CSV
sqlite3 -header -csv ./local_analysis/investment_agent.db \
    "SELECT date(timestamp) as date, total_value_gbp, pnl_pct, alpha_pct, num_positions
     FROM portfolio_snapshots ORDER BY timestamp;" \
    > portfolio_history.csv

# Export trade history to CSV
sqlite3 -header -csv ./local_analysis/investment_agent.db \
    "SELECT timestamp, ticker, action, quantity, price, value_gbp, strategy, conviction, status
     FROM orders ORDER BY timestamp;" \
    > trade_history.csv

# Export cost data to CSV
sqlite3 -header -csv ./local_analysis/investment_agent.db \
    "SELECT timestamp, provider, model, input_tokens, output_tokens, cost_gbp, cycle_id, purpose
     FROM cost_logs ORDER BY timestamp;" \
    > cost_history.csv
```

---

## 11. Backtesting on VPS

The backtesting engine runs strategy validation on historical data. Use it before deploying strategy or config changes (see `docs/GOVERNANCE.md` §9.5).

### 11.1 Docker

```bash
cd /home/deploy/investment-agent

# Single backtest with real data (fetches from yfinance if data/backtest/ is empty; caches to CSV)
docker compose run --rm investment-agent python -m src.backtesting.main \
  --config backtests/default.yaml \
  --output-dir backtests/results/latest

# Walk-forward validation + promotion report
docker compose run --rm investment-agent python -m src.backtesting.main \
  --config backtests/default.yaml \
  --walk-forward \
  --output-dir backtests/results/walk_forward

# Synthetic data (no network, fast sanity check)
docker compose run --rm investment-agent python -m src.backtesting.main --synthetic
```

Results are written to `backtests/results/` and persisted via the `./backtests/results` volume mount in `docker-compose.yml`.

### 11.2 Non-Docker

```bash
cd /home/deploy/investment-agent

poetry run python -m src.backtesting.main --config backtests/default.yaml --walk-forward
```

### 11.3 Data Caching

On first run with real data, the CLI fetches OHLCV from yfinance and caches to `data/backtest/<TICKER>.csv`. Subsequent runs use the cache. To refresh data, delete the CSV files and re-run.

---

## 12. Transferring Project to VPS

### 12.1 Deploy Updates (Git Push + Pull)

1. **Local:** Commit and push your changes (including backtesting, feedback loop, etc.):

   ```bash
   git add -A
   git commit -m "feat: backtesting with yfinance fetch, CSV cache, walk-forward"
   git push origin main   # or your branch name
   ```

2. **VPS:** Pull and rebuild:

   ```bash
   ssh -p 2222 deploy@your-vps-ip
   cd /home/deploy/investment-agent

   git fetch origin
   git pull origin main

   # Docker
   docker compose down
   docker compose up -d --build

   # Non-Docker
   poetry install --without dev
   poetry run alembic upgrade head
   sudo systemctl restart investment-agent
   ```

### 12.2 Initial Clone (Fresh VPS)

```bash
cd /home/deploy
git clone https://github.com/your-org/Investment-agent.git investment-agent
cd investment-agent

cp config/.env.example .env
# Edit .env with API keys

# Docker
docker compose up -d --build

# Or Non-Docker
poetry install --without dev
poetry run alembic upgrade head
# Create systemd service (see §4.6)
```

### 12.3 rsync (Alternative to Git)

If you prefer to sync files without Git:

```bash
# From local to VPS (excludes .env, .venv, __pycache__)
rsync -avz --exclude='.env' --exclude='.venv' --exclude='__pycache__' \
  -e "ssh -p 2222" \
  ./investment-agent/ deploy@your-vps-ip:/home/deploy/investment-agent/
```

Then on the VPS: `docker compose up -d --build` or `sudo systemctl restart investment-agent`.

---

## 13. Dashboard VPS Deployment

The web dashboard (activity feed, portfolio, run history, universe, 7 pages) is deployed alongside the agent on the VPS. **Full plan and checklist:** `docs/DASHBOARD_DEPLOYMENT.md`. **Status:** US-1.8 delivered; dashboard running on VPS once the operator runs the deployment steps below.

### Access Options (no domain required)

| Option | Access | Notes |
|--------|--------|-------|
| **VPS IP** (recommended) | `http://YOUR_VPS_IP:8000` | No cost, no setup. Activity feed (SSE) and Run History work via relative API URLs. |
| **Domain** | `https://dashboard.yourdomain.com` | HTTPS via Let's Encrypt; ~£10–15/year. |
| **GitHub Pages** | Not suitable | Frontend must call VPS API; mixed content (HTTPS→HTTP) blocked. |

### Prerequisites

- Dashboard code on branch (e.g. `main` or `feature/dashboard-full-spec`)
- `config/settings.yaml`: `dashboard.enabled: true`, `dashboard.events_enabled: true`
- Agent already running in Docker on VPS

### Deployment Steps (run on VPS)

From the project directory (e.g. `/home/deploy/investment-agent`):

1. Pull latest: `git pull origin main` (or your deployment branch)
2. Allow firewall (one-time): `sudo ufw allow 8000/tcp comment "Dashboard"` then `sudo ufw reload`
3. Build and run: `docker compose up -d --build`
4. Verify: `curl http://localhost:8000/health` and open `http://YOUR_VPS_IP:8000` in a browser

**Outcome:** Dashboard is running on VPS. All 8 pages (Home, Universe, Run History, Portfolio, Opportunity, Order Management, Costs, Roadmap), activity feed (SSE), and API at `http://YOUR_VPS_IP:8000`.

**Run History** shows `runs` table entries (one per cycle). **One-off cycle:** use the **Dry Run** or **Live Run** buttons on Dashboard Home (Live Run requires confirmation), or `docker exec -it investment-agent poetry run python -m src.orchestrator.main` (live) / `... --dry-run` (dry).

---

## Appendix: Schedule Reference

| Job | Schedule | Description |
|-----|----------|-------------|
| `analysis_cycle_*` | From cycle_times_utc (intraday: 08/12/16 UTC; standard: 07/19 UTC) Mon-Fri | Analysis + trading cycle |
| `daily_snapshot` | 21:30 UTC daily | Portfolio snapshot + daily report |
| `weekly_report` | 22:00 UTC Friday | Weekly performance report |
| `instrument_refresh` | 12:00 UTC Sunday | Refresh tradeable instrument universe from T212 |

## Appendix: Directory Layout on VPS

```
/home/deploy/investment-agent/
├── .env                          # API keys (chmod 600)
├── config/
│   └── settings.yaml             # Trading, risk, cost, model configuration
├── data/
│   ├── investment_agent.db       # SQLite database (WAL mode)
│   ├── investment_agent.db-wal   # WAL file
│   └── investment_agent.db-shm   # Shared memory file
├── journals/
│   ├── daily/                    # Per-trade and daily decision journals
│   └── weekly/                   # Weekly summary reports
├── logs/
│   ├── scheduler.log
│   ├── orchestrator.log
│   ├── strategy_engine.log
│   ├── order_manager.log
│   ├── risk_manager.log
│   ├── cost_tracker.log
│   ├── t212_client.log
│   ├── moderation_panel.log
│   ├── health_check.log
│   └── backup.log
├── backups/
│   └── daily/                    # Timestamped DB snapshots and journal archives
├── scripts/
│   ├── health_check.sh           # Cron: every 15 minutes
│   └── backup.sh                 # Cron: daily at 02:00 UTC
├── docker-compose.yml
├── Dockerfile
└── src/                          # Application code
```

---

## Related Notes

- [Dashboard Deployment](DASHBOARD_DEPLOYMENT.md) — dashboard-specific Docker and VPS setup
- [Data Export Runbook](DATA_EXPORT_RUNBOOK.md) — exporting VPS data for local analysis
- [Local Setup](LOCAL_SETUP.md) — local development and Mac environment setup
- [Governance](GOVERNANCE.md) — operational controls, incident response, audit trail
- [Architecture](ARCHITECTURE.md) — system diagrams and pipeline flow
