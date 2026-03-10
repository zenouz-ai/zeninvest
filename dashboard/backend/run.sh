#!/bin/bash
# Simple shell script to run the dashboard server
# This avoids path issues with spaces in directory names

cd "$(dirname "$0")/../.." || exit 1
poetry run uvicorn dashboard.backend.app.main:app --host 0.0.0.0 --port 8000 --reload
