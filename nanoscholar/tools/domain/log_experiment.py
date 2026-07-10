"""Log experiments to CSV and Markdown."""

import csv
import json
import os
from datetime import datetime
from pathlib import Path

from nanoscholar.tools.tool import Tool, register

_EXP_DIR = Path("_experiments")


def _ensure_dir():
    _EXP_DIR.mkdir(parents=True, exist_ok=True)


def log_experiment(name: str, params_json: str = "{}", metrics_json: str = "{}") -> str:
    """Log an experiment record to CSV and Markdown."""
    _ensure_dir()
    params = json.loads(params_json) if isinstance(params_json, str) else params_json
    metrics = json.loads(metrics_json) if isinstance(metrics_json, str) else metrics_json
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exp_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    params_str = json.dumps(params, ensure_ascii=False)
    metrics_str = json.dumps(metrics, ensure_ascii=False)

    # CSV
    csv_path = _EXP_DIR / "experiments.csv"
    is_new = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["id", "timestamp", "name", "params", "metrics"])
        w.writerow([exp_id, timestamp, name, params_str, metrics_str])

    # Markdown
    md_path = _EXP_DIR / "experiments.md"
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(f"\n## {name}  ({exp_id})\n")
        f.write(f"- **Timestamp**: {timestamp}\n")
        f.write(f"- **Params**: {params_str}\n")
        f.write(f"- **Metrics**: {metrics_str}\n")

    return f"[Experiment logged: {exp_id}] {name}"


log_tool = Tool(
    name="log_experiment",
    description="Log an experiment record with name, parameters (JSON), and metrics (JSON). Appends to CSV and Markdown files in _experiments/.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Experiment name"},
            "params_json": {"type": "string", "description": "JSON string of parameters"},
            "metrics_json": {"type": "string", "description": "JSON string of metrics"},
        },
        "required": ["name"],
    },
    handler=log_experiment,
    category="file_write",
    approval_required=False,
)
register(log_tool)


