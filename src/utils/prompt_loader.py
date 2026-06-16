"""Load committee prompts from config/prompts/*.md and compute stable hashes."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.utils.fingerprints import stable_hash

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "prompts"


@lru_cache(maxsize=32)
def load_prompt_file(relative_path: str) -> str:
    """Read a prompt markdown file relative to config/prompts/."""
    path = _PROMPTS_DIR / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def get_prompt_hash(*relative_paths: str, extra: dict | None = None) -> str:
    """Return a stable hash for one or more prompt files plus optional extra keys."""
    payload: dict[str, str] = {path: load_prompt_file(path) for path in relative_paths}
    if extra:
        payload.update({str(k): str(v) for k, v in extra.items()})
    return stable_hash(payload)


def prompts_dir() -> Path:
    """Return the canonical prompts directory path."""
    return _PROMPTS_DIR
