"""Run the dashboard backend server."""

import os
import sys
from pathlib import Path

# Add project root to Python path (for both main process and subprocess)
project_root = Path(__file__).parent.parent.parent.resolve()
project_root_str = str(project_root)

# Set PYTHONPATH environment variable so subprocesses inherit it
if "PYTHONPATH" in os.environ:
    if project_root_str not in os.environ["PYTHONPATH"]:
        os.environ["PYTHONPATH"] = f"{project_root_str}:{os.environ['PYTHONPATH']}"
else:
    os.environ["PYTHONPATH"] = project_root_str

# Also add to sys.path for current process
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "dashboard.backend.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
