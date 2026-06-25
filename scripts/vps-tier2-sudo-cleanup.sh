#!/usr/bin/env bash
# Tier 2 VPS cleanup — run with: sudo bash scripts/vps-tier2-sudo-cleanup.sh
set -euo pipefail

echo "=== Before ==="
df -h /

echo "=== Journal vacuum (cap at 100M) ==="
journalctl --vacuum-size=100M

echo "=== APT cache clean ==="
apt-get clean

echo "=== Remove rotated /var/log gzip archives ==="
du -h --max-depth=1 /var/log | sort -rh | head -10
find /var/log -type f -name '*.gz' -delete

echo "=== Old cursor sandbox caches (deploy_zengrowth-owned) ==="
find /tmp/cursor-sandbox-cache -mindepth 1 -maxdepth 1 -type d -mtime +1 -exec rm -rf {} + 2>/dev/null || true

echo "=== deploy_zengrowth IDE cache sizes (inspect only) ==="
du -h --max-depth=2 /home/deploy_zengrowth/.cursor-server /home/deploy_zengrowth/.vscode-server 2>/dev/null | sort -rh | head -20 || true

echo "=== fstrim ==="
fstrim -v /

echo "=== After ==="
df -h /
