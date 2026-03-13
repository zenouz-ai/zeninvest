"""Serve documentation files from the project docs/ directory."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter()

# Project root: dashboard/backend/app/routers/docs.py -> investment-agent/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_DOCS_DIR = _PROJECT_ROOT / "docs"

# Whitelist of doc files we are allowed to serve (no path traversal)
_ALLOWED_DOCS = {
    "ARCHITECTURE": "ARCHITECTURE.md",
    "SOPHISTICATION_ROADMAP": "SOPHISTICATION_ROADMAP.md",
}


@router.get("/{doc_key}", response_class=PlainTextResponse)
async def get_doc(doc_key: str):
    """Serve a documentation file. Keys: ARCHITECTURE, SOPHISTICATION_ROADMAP."""
    key = doc_key.upper().replace("-", "_").replace(".MD", "")
    if key not in _ALLOWED_DOCS:
        raise HTTPException(status_code=404, detail="Documentation not found")
    path = _DOCS_DIR / _ALLOWED_DOCS[key]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Documentation file not found")
    content = path.read_text(encoding="utf-8")
    return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")
