"""HTML/JSON report writer for decision quality evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.learning.evaluation.policies import PolicyId


def write_evaluation_report(payload: dict[str, Any], *, root: Path) -> dict[str, str]:
    run_id = payload["run_id"]
    out_dir = root / "data" / "learning" / "evaluation" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "metrics.json"
    json_path.write_text(json.dumps(payload, indent=2, default=str))

    gates = payload.get("gates") or {}
    gates_path = out_dir / "evaluation_gates.json"
    gates_path.write_text(json.dumps(gates, indent=2, default=str))

    html_path = out_dir / "index.html"
    html_path.write_text(_render_html(payload))

    return {
        "metrics": str(json_path),
        "gates": str(gates_path),
        "html": str(html_path),
    }


def _render_html(payload: dict[str, Any]) -> str:
    policies = payload.get("policies") or {}
    gates = payload.get("gates") or {}
    summary = gates.get("summary") or ""
    rows_html = ""
    for pid, metrics in policies.items():
        rows_html += (
            f"<tr><td>{pid}</td>"
            f"<td>{metrics.get('bad_decision_rate_realized', '—')}</td>"
            f"<td>{metrics.get('realized_n', '—')}</td>"
            f"<td>{metrics.get('net_counterfactual_gbp', '—')}</td>"
            f"<td>{metrics.get('big_loser_recall', '—')}</td>"
            f"<td>{metrics.get('precision_at_veto', '—')}</td></tr>"
        )

    tier_rows = ""
    for tier in gates.get("tiers") or []:
        status = "PASS" if tier.get("passed") else "FAIL"
        tier_rows += (
            f"<tr><td>{tier.get('label')}</td><td>{status}</td>"
            f"<td>{'; '.join(tier.get('reasons') or [])}</td></tr>"
        )

    disagreements = payload.get("disagreements") or []
    dis_rows = ""
    for d in disagreements[:25]:
        dis_rows += (
            f"<tr><td>{d.get('ticker')}</td><td>{d.get('label_3class')}</td>"
            f"<td>{d.get('champion_action')}</td><td>{d.get('combined_action')}</td>"
            f"<td>{d.get('trade_pnl_gbp')}</td></tr>"
        )

    champion = policies.get(PolicyId.CHAMPION_AS_IS.value, {})
    low_n = champion.get("low_confidence")
    warning = (
        "<p><strong>Low sample:</strong> Realized trade count is below 200 — "
        "treat PnL counterfactuals as directional only.</p>"
        if low_n
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Decision Quality Evaluation — {payload.get('run_id')}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:2rem;color:#0f172a;}}
table{{border-collapse:collapse;width:100%;margin:1rem 0;}}
th,td{{border:1px solid #e2e8f0;padding:8px;text-align:left;font-size:14px;}}
th{{background:#f8fafc;}}
.summary{{background:#f1f5f9;padding:1rem;border-radius:8px;margin:1rem 0;}}
</style></head><body>
<h1>Champion vs Challengers</h1>
<p>Run <code>{payload.get('run_id')}</code> · {payload.get('n_rows')} rows ·
{payload.get('closed_trades')} realized trades · dataset {payload.get('dataset_version')}</p>
<div class="summary">{summary}</div>
{warning}
<h2>Policy comparison</h2>
<table><thead><tr>
<th>Policy</th><th>Bad rate (realized)</th><th>n</th><th>Net counterfactual £</th>
<th>Big-loser recall</th><th>Veto precision</th></tr></thead><tbody>{rows_html}</tbody></table>
<h2>Promotion gates</h2>
<table><thead><tr><th>Tier</th><th>Status</th><th>Notes</th></tr></thead><tbody>{tier_rows}</tbody></table>
<h2>Champion vs combined disagreements (sample)</h2>
<table><thead><tr><th>Ticker</th><th>Label</th><th>Champion</th><th>Combined</th><th>PnL £</th></tr></thead>
<tbody>{dis_rows or '<tr><td colspan="5">No disagreements in sample</td></tr>'}</tbody></table>
</body></html>"""
