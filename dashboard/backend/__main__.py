"""Module entry point for running the dashboard server."""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "dashboard.backend.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
