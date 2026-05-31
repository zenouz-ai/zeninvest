"""Static HTML + JSON report generation for learning runs."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.learning.models.calibration import ConvictionCalibrator
from src.learning.models.gbm import GBMTrainingResult
from src.learning.models.stall import StallTrainingResult
from src.utils.logger import get_logger

logger = get_logger("learning.reports")


@dataclass
class LearningReport:
    """Bundled report payload for a single learning run."""

    run_id: str
    dataset_version: str
    rows: int
    label_distribution: dict[str, int]
    calibrator: ConvictionCalibrator | None
    gbm_result: GBMTrainingResult | None
    stall_result: StallTrainingResult | None
    baseline_metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metrics_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dataset_version": self.dataset_version,
            "rows": self.rows,
            "label_distribution": self.label_distribution,
            "calibrator": self.calibrator.curve.to_dict() if self.calibrator else None,
            "gbm": self.gbm_result.to_dict() if self.gbm_result else None,
            "stall": self.stall_result.to_dict() if self.stall_result else None,
            "baselines": self.baseline_metrics,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def write_report(report: LearningReport, output_dir: str | Path) -> dict[str, str]:
    """Write the full report bundle (metrics.json + index.html)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = output_dir / "metrics.json"
    with open(metrics_path, "w") as fh:
        json.dump(report.to_metrics_dict(), fh, indent=2, default=str)

    index_path = output_dir / "index.html"
    index_path.write_text(_render_html(report))

    return {
        "metrics": str(metrics_path),
        "html": str(index_path),
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def _render_html(report: LearningReport) -> str:
    parts: list[str] = [
        "<html><head><meta charset='utf-8'>",
        f"<title>Learning Run {html.escape(report.run_id)}</title>",
        "<style>",
        "body{font-family:'Inter',system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#0f172a;background:#f8fafc;}",
        "h1,h2,h3{color:#0f172a;}",
        "table{border-collapse:collapse;width:100%;margin-bottom:24px;background:white;}",
        "th,td{border:1px solid #e2e8f0;padding:6px 10px;text-align:left;font-size:14px;}",
        "th{background:#f1f5f9;}",
        ".grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;}",
        ".card{background:white;padding:16px;border:1px solid #e2e8f0;border-radius:8px;box-shadow:0 1px 2px rgba(0,0,0,0.04);}",
        ".tag{display:inline-block;padding:2px 6px;border-radius:4px;background:#0f172a;color:white;font-size:12px;}",
        "</style>",
        "</head><body>",
        f"<h1>Learning Run <code>{html.escape(report.run_id)}</code></h1>",
        f"<p><span class='tag'>dataset {html.escape(report.dataset_version)}</span> · ",
        f"{report.rows:,} rows · generated {datetime.now(timezone.utc).isoformat()}</p>",
    ]

    # Dataset summary
    parts.append("<h2>Dataset summary</h2>")
    parts.append("<table><tr><th>Label</th><th>Count</th></tr>")
    for label, count in report.label_distribution.items():
        parts.append(f"<tr><td>{html.escape(label)}</td><td>{count:,}</td></tr>")
    parts.append("</table>")

    # Calibration curve
    if report.calibrator is not None:
        parts.append("<h2>Conviction calibration (US-2.1)</h2>")
        curve = report.calibrator.curve
        parts.append("<table><tr><th>Bin</th><th>Count</th><th>Empirical win rate</th></tr>")
        for label, count, rate in zip(curve.bin_labels, curve.bin_counts, curve.bin_win_rates):
            badge = "&#x2705;" if count >= curve.min_samples_for_activation else "&#x26A0;"
            parts.append(
                f"<tr><td>{html.escape(label)}</td><td>{count:,}</td><td>{rate*100:.1f}% {badge}</td></tr>"
            )
        parts.append("</table>")
        active = ", ".join(report.calibrator.curve.active_bins) or "none"
        parts.append(f"<p>Active bins (>= {curve.min_samples_for_activation} samples): {html.escape(active)}</p>")

    # GBM results
    if report.gbm_result is not None:
        gbm = report.gbm_result
        agg = gbm.aggregate_metrics or {}
        parts.append("<h2>LightGBM 3-class (US-6.1)</h2>")
        parts.append("<div class='grid'>")
        parts.append("<div class='card'><h3>Aggregate metrics</h3>")
        parts.append("<table>")
        parts.append(f"<tr><th>Accuracy</th><td>{agg.get('accuracy', 0.0):.3f}</td></tr>")
        parts.append(f"<tr><th>Folds</th><td>{agg.get('n_folds', 0)}</td></tr>")
        for cls, value in (agg.get("auc") or {}).items():
            parts.append(f"<tr><th>AUC ({html.escape(cls)})</th><td>{value:.3f}</td></tr>")
        for cls, value in (agg.get("per_class_recall") or {}).items():
            parts.append(f"<tr><th>Recall ({html.escape(cls)})</th><td>{value:.3f}</td></tr>")
        parts.append("</table></div>")

        parts.append("<div class='card'><h3>Confusion matrix</h3><table>")
        classes = gbm.classes
        parts.append("<tr><th></th>" + "".join(f"<th>pred {html.escape(c)}</th>" for c in classes) + "</tr>")
        for true_cls in classes:
            row = "".join(
                f"<td>{gbm.confusion_matrix.get(true_cls, {}).get(pred_cls, 0)}</td>" for pred_cls in classes
            )
            parts.append(f"<tr><th>true {html.escape(true_cls)}</th>{row}</tr>")
        parts.append("</table></div>")
        parts.append("</div>")

        if gbm.feature_importance:
            parts.append("<h3>Top features (gain)</h3>")
            parts.append("<table><tr><th>Feature</th><th>Relative gain</th></tr>")
            for feature, value in sorted(gbm.feature_importance.items(), key=lambda kv: kv[1], reverse=True)[:15]:
                parts.append(f"<tr><td>{html.escape(feature)}</td><td>{value*100:.2f}%</td></tr>")
            parts.append("</table>")

        if gbm.decile_lift:
            parts.append("<h3>Decile lift (out-of-fold)</h3>")
            parts.append("<table><tr><th>Decile</th><th>Count</th><th>Mean ret_30d (%)</th></tr>")
            for decile_row in gbm.decile_lift:
                parts.append(
                    f"<tr><td>{decile_row['decile']}</td><td>{decile_row['count']}</td><td>{decile_row['mean_ret_30d_pct']:.2f}</td></tr>"
                )
            parts.append("</table>")

    # Stall model
    if report.stall_result is not None:
        stall = report.stall_result
        parts.append("<h2>Stall model (US-3.7-aligned)</h2>")
        parts.append("<table>")
        for key, value in stall.aggregate_metrics.items():
            parts.append(f"<tr><th>{html.escape(str(key))}</th><td>{value}</td></tr>")
        parts.append("</table>")

    # Baseline
    if report.baseline_metrics:
        parts.append("<h2>Baselines</h2><pre>")
        parts.append(html.escape(json.dumps(report.baseline_metrics, indent=2, default=str)))
        parts.append("</pre>")

    parts.append("</body></html>")
    return "\n".join(parts)
