# Starting the Dashboard Server

## The Problem

Uvicorn's reload mode spawns subprocesses that don't inherit Python path modifications. This causes `ModuleNotFoundError: No module named 'dashboard'`.

## Solutions (in order of preference)

### Solution 1: Set PYTHONPATH before running (RECOMMENDED)

```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
poetry run python dashboard/backend/run_server.py
```

Or in one line:
```bash
PYTHONPATH="$(pwd):${PYTHONPATH}" poetry run python dashboard/backend/run_server.py
```

### Solution 2: Use the simple script (no reload)

```bash
poetry run python dashboard/backend/run_server_simple.py
```

This disables reload mode but avoids subprocess path issues.

### Solution 3: Use uvicorn directly with PYTHONPATH

```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
poetry run uvicorn dashboard.backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Solution 4: Run from project root with explicit path

```bash
cd "/Users/Kayvan/Library/Mobile Documents/com~apple~CloudDocs/AI_Projects/Investment-agent"
PYTHONPATH="$(pwd)" poetry run uvicorn dashboard.backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Quick Test

Once the server starts, you should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started server process [XXXX]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

Then test it:
```bash
curl http://localhost:8000/health
```

Or open in browser:
```
http://localhost:8000/docs
```
