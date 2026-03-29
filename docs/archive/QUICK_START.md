> **Archived 2026-03-29:** Content merged into dashboard/backend/README.md Quick Start section.

# Quick Start Guide - Dashboard Backend

## Step 1: Install Dependencies

The dashboard backend requires FastAPI, uvicorn, and pydantic. Install them:

```bash
poetry install
```

This will install all dependencies including the new dashboard ones.

## Step 2: Run Database Migration

Create the dashboard tables:

```bash
poetry run alembic upgrade head
```

## Step 3: Start the Server

**Recommended method (module syntax):**
```bash
poetry run python -m dashboard.backend
```

**Alternative (uvicorn directly):**
```bash
poetry run uvicorn dashboard.backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Alternative (script file):**
```bash
poetry run python dashboard/backend/run_server.py
```

## Step 4: Test It

1. **Open API docs in browser:**
   ```
   http://localhost:8000/docs
   ```

2. **Test health endpoint:**
   ```bash
   curl http://localhost:8000/health
   ```

3. **Test other endpoints:**
   ```bash
   curl http://localhost:8000/api/runs/
   curl http://localhost:8000/api/universe/
   curl http://localhost:8000/api/portfolio/
   ```

## Troubleshooting

### "ModuleNotFoundError: No module named 'uvicorn'"

**Solution:** Run `poetry install` to install dependencies.

### "No such file or directory"

**Solution:** Make sure you're in the project root and files are synced:
```bash
cd "/Users/Kayvan/Library/Mobile Documents/com~apple~CloudDocs/AI_Projects/Investment-agent"
git pull
poetry install
```

### Port 8000 already in use

**Solution:** Use a different port:
```bash
poetry run uvicorn dashboard.backend.app.main:app --host 0.0.0.0 --port 8001 --reload
```

Then access at `http://localhost:8001`
