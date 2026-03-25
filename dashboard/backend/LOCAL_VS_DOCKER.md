# Local vs Docker for Testing Dashboard

## Quick Answer: **Local is Better for Testing Dashboard**

For testing the dashboard instrumentation, **running locally is recommended** because:
- ✅ Easier debugging and log access
- ✅ Dashboard server accessible on localhost:8000
- ✅ Faster iteration and testing
- ✅ Can see both agent and dashboard logs together
- ✅ No port mapping or networking complexity

**Docker is better for:**
- Production deployment
- Testing production-like environment
- Isolated environment
- Consistent setup across team

## Comparison

### Running Locally (Recommended for Testing)

**Pros:**
- ✅ Dashboard accessible at `http://localhost:8000` directly
- ✅ See all logs in terminal
- ✅ Easy to debug - can add print statements, breakpoints
- ✅ Faster to restart and test changes
- ✅ Can run dashboard and agent in separate terminals
- ✅ Direct access to database file
- ✅ No Docker networking complexity

**Cons:**
- ⚠️ Need Poetry and dependencies installed locally
- ⚠️ Environment might differ from production

**Setup:**
```bash
# Terminal 1: Dashboard
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
poetry run python dashboard/backend/run_server.py

# Terminal 2: Agent cycle
poetry run python -m src.orchestrator.main
```

### Running in Docker

**Pros:**
- ✅ Matches production environment exactly
- ✅ Isolated - doesn't affect local Python environment
- ✅ Consistent across different machines
- ✅ Easy to reset (just restart container)
 - ✅ Includes the nginx ingress used in production

**Cons:**
- ⚠️ Production compose now expects Cloudflare-origin certs for the nginx ingress
- ⚠️ Harder to debug - need `docker logs` or exec into container
- ⚠️ Slower iteration - need to rebuild/restart container
- ⚠️ Database file is in volume - need to access via Docker
- ⚠️ Can't easily run dashboard separately

**Setup:**
```bash
# Production-style compose:
docker compose up -d
docker compose logs -f investment-agent

# Public ingress is via nginx on 80/443, not a direct dashboard port mapping
```

## Recommendation for Your Use Case

**For testing dashboard instrumentation: Use Local**

1. You want to see events in real-time → easier with local dashboard
2. You want to debug quickly → local logs are immediate
3. You want to test changes fast → no Docker rebuild needed
4. You want to use browser at localhost:8000 → works directly

**For production deployment: Use Docker**

1. Consistent environment
2. Isolated from host system
3. Easy to manage on VPS
4. Matches deployment setup

## Hybrid Approach (Best of Both)

You can run:
- **Dashboard locally** (for easy access and debugging)
- **Agent in Docker** (for production-like testing)

But this requires:
- Dashboard connecting to Docker database volume (complex)
- Or agent writing to local database (defeats purpose)

**Simpler: Just run both locally for testing!**

## Current Docker Setup

The existing `docker-compose.yml` runs:
- Agent scheduler (main process)
- Nginx ingress (80/443)
- Internal-only dashboard service on the Compose network
- Database in volume (`./data`)
- Logs in volume (`./logs`)

This matches production, but it is still more complex than needed for rapid dashboard debugging.

## Bottom Line

**For testing dashboard instrumentation right now:**
👉 **Run locally** - it's simpler, faster, and easier to debug.

**For production deployment later:**
👉 **Use Docker** - matches VPS setup and is more robust.

You can always test in Docker later once the dashboard is working locally!
