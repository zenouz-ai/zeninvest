> **Archived 2026-03-29:** Superseded by TESTING.md and QUICK_START.md. Moved to docs/archive/.

# Quick Test Guide

## The file isn't synced yet?

If you get "No such file or directory", pull the latest changes:

```bash
git pull
```

## Alternative: Test without the script

You can test the endpoints directly using Python:

```bash
# Set PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Test event logger
poetry run python -c "
from dashboard.backend.app.services.event_logger import log_event
log_event('test_event', 'manual', 'Test message', {'test': True})
print('Event logged!')
"

# Check events
curl http://localhost:8000/api/events/ | python -m json.tool
```

## Or use the API directly

You can also POST data directly to the API:

```bash
# Create a test run
curl -X POST http://localhost:8000/api/runs/ \
  -H "Content-Type: application/json" \
  -d '{
    "cycle_id": "test-123",
    "run_type": "manual",
    "summary_json": {"test": true}
  }'

# Then check it
curl http://localhost:8000/api/runs/
```
