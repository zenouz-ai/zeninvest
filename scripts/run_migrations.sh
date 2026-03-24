#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POETRY_BIN="${POETRY_BIN:-$HOME/.local/bin/poetry}"
LOCK_FILE="$ROOT_DIR/data/runtime/migrations.lock"

if [[ ! -x "$POETRY_BIN" ]]; then
  echo "Poetry not found at $POETRY_BIN" >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/data/runtime"
cd "$ROOT_DIR"

exec flock "$LOCK_FILE" "$POETRY_BIN" run alembic upgrade head
