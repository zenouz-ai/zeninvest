#!/usr/bin/env python3
"""Read-only proof-of-value analysis of rejected-ticker decisions (US-6.7).

Thin CLI wrapper around src.learning.dataset.rejection_analysis.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.learning.dataset.rejection_analysis import (
    analyze_rejections,
    render_markdown,
    write_analysis_artifacts,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "learning" / "reports"


def build_readonly_session(db_path: str | None):
    resolved = db_path or os.environ.get("INVESTMENT_AGENT_DB_PATH") or str(
        PROJECT_ROOT / "data" / "investment_agent.db"
    )
    engine = create_engine(f"sqlite:///{resolved}")
    return sessionmaker(bind=engine)()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    session = build_readonly_session(args.db_path)
    try:
        analysis = analyze_rejections(session)
    finally:
        session.close()

    markdown = render_markdown(analysis)
    print(markdown)

    if not args.no_write:
        out_dir = Path(args.output_dir)
        artifacts = write_analysis_artifacts(analysis, out_dir)
        stamp = artifacts.get("stamp", datetime.now(timezone.utc).strftime("%Y%m%d"))
        (out_dir / f"rejected_analysis_{stamp}.md").write_text(markdown)
        print(f"Wrote summary to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
