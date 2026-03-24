#!/bin/bash
# Simple shell script to run the dashboard server safely in a single process.

cd "$(dirname "$0")/../.." || exit 1
poetry run python -m dashboard.backend
