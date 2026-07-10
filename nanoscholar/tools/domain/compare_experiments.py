"""Compare experiment results by metric."""

import csv
import json
from pathlib import Path

from nanoscholar.tools.tool import Tool, register

_EXP_DIR = Path("_experiments")


def compare_experiments(metric_key: str, top_n: int = 5) -> str:
    """Read experiment log and compare by metric."""
    csv_path = _EXP_DIR / "experiments.csv"
    if not csv_path.exists():
        return "[No experiments found. Run log_experiment first.]"

    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                metrics = json.loads(row.get("metrics", "{}"))
                if metric_key in metrics:
                    rows.append((row["name"], row["timestamp"], metrics[metric_key]))
            except (json.JSONDecodeError, KeyError):
                continue

    if not rows:
        return f"[No experiments with metric '{metric_key}' found.]"

    rows.sort(key=lambda x: float(x[2]) if x[2] is not None else 0, reverse=True)
    rows = rows[:top_n]

    lines = [f"Top {len(rows)} experiments by '{metric_key}':", ""]
    for i, (name, ts, val) in enumerate(rows, 1):
        lines.append(f"{i}. {name}")
        lines.append(f"   {metric_key}: {val}")
        lines.append(f"   Date: {ts}")
        lines.append("")

    return "\n".join(lines).strip()


compare_tool = Tool(
    name="compare_experiments",
    description="Read experiment records and compare by a metric key. Returns top-N results sorted by value.",
    input_schema={
        "type": "object",
        "properties": {
            "metric_key": {"type": "string", "description": "Metric key to compare (e.g. 'accuracy')"},
            "top_n": {"type": "integer", "description": "Number of top results to return", "default": 5},
        },
        "required": ["metric_key"],
    },
    handler=compare_experiments,
    category="file_read",
    approval_required=False,
)
register(compare_tool)


