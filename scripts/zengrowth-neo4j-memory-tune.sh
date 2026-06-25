#!/usr/bin/env bash
# Run as deploy_zengrowth on the VPS to cap zengrowth-prod-neo4j memory.
# Current live settings: heap 512m/1G — target: 256m/256m + 256m pagecache.
set -euo pipefail

COMPOSE_FILE="${1:-/home/deploy_zengrowth/zengrowth/docker-compose.prod.yml}"

if [[ ! -r "$COMPOSE_FILE" ]]; then
  echo "Cannot read $COMPOSE_FILE — run as deploy_zengrowth"
  exit 1
fi

cp -a "$COMPOSE_FILE" "${COMPOSE_FILE}.bak.$(date +%Y%m%d%H%M%S)"

# Replace or insert Neo4j memory settings (YAML key: "value" or KEY=value list form).
python3 - <<'PY' "$COMPOSE_FILE"
import re, sys
path = sys.argv[1]
text = open(path).read()
text = re.sub(
    r'(NEO4J_server_memory_heap_initial__size:\s*)"[^"]+"',
    r'\1"256m"',
    text,
)
text = re.sub(
    r'(NEO4J_server_memory_heap_max__size:\s*)"[^"]+"',
    r'\1"256m"',
    text,
)
text = re.sub(
    r'NEO4J_server_memory_heap_initial__size=\d+[mMgG]',
    'NEO4J_server_memory_heap_initial__size=256m',
    text,
)
text = re.sub(
    r'NEO4J_server_memory_heap_max__size=\d+[mMgG]',
    'NEO4J_server_memory_heap_max__size=256m',
    text,
)
if 'NEO4J_server_memory_pagecache_size' not in text:
    if 'NEO4J_server_memory_heap_max__size: "256m"' in text:
        text = text.replace(
            'NEO4J_server_memory_heap_max__size: "256m"',
            'NEO4J_server_memory_heap_max__size: "256m"\n      NEO4J_server_memory_pagecache_size: "256m"',
            1,
        )
    elif 'NEO4J_server_memory_heap_max__size=256m' in text:
        text = text.replace(
            'NEO4J_server_memory_heap_max__size=256m',
            'NEO4J_server_memory_heap_max__size=256m\n      - NEO4J_server_memory_pagecache_size=256m',
            1,
        )
else:
    text = re.sub(
        r'(NEO4J_server_memory_pagecache_size:\s*)"[^"]+"',
        r'\1"256m"',
        text,
    )
    text = re.sub(
        r'NEO4J_server_memory_pagecache_size=\d+[mMgG]',
        'NEO4J_server_memory_pagecache_size=256m',
        text,
    )
open(path, 'w').write(text)
print(f"Updated {path}")
PY

cd "$(dirname "$COMPOSE_FILE")"
ENV_FILE="${ENV_FILE:-.env.production}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE in $(pwd) — set ENV_FILE or create .env.production"
  exit 1
fi
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml -f docker-compose.zeninvest-ingress.yml up -d --force-recreate neo4j
docker inspect zengrowth-prod-neo4j --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -i memory
