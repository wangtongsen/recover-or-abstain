#!/usr/bin/env python3
"""Build the protocol v0.3 rerun batch spec for the E3 track.

Same matrix (experiments/racer-v2-main-matrix-e3.json), same model, same 14
baselines, same seeds — only the run_id timestamp and protocol_id change, so
the rerun writes fresh trajectories with direct-apply receipts under the
v0.3 pre-registered terms (reports/racer-v2-benchmark-protocol-v0.3.md).

Reads the frozen matrix, rewrites identity fields, and prints the new batch
spec to stdout (consumed as BATCH_SPEC by services/agent_runner/app.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

V03_RUN_STAMP = "20260909T110000Z"
V03_PROTOCOL_ID = "racer-v2-benchmark-protocol-0.3"


def main() -> int:
    matrix_path = PROJECT_ROOT / "experiments" / "racer-v2-main-matrix-e3.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    tasks = matrix.get("tasks", [])
    if not tasks:
        print("matrix has no tasks", file=sys.stderr)
        return 1

    new_tasks = []
    for task in tasks:
        task = json.loads(json.dumps(task))  # deep copy
        old_run_id = str(task.get("run_id", ""))
        # main-e3-<variant>-<stamp>-trial-<n> -> keep variant/trial, new stamp
        variant = task.get("task_variant", task.get("variant", "clean_success"))
        trial = task.get("trial_id", 0)
        task["run_id"] = f"main-e3-{variant}-{V03_RUN_STAMP}-trial-{trial}"
        task["protocol_id"] = V03_PROTOCOL_ID
        # episode_id / task_id keep trial suffix; they identify the trial slot
        # (identical to the v0.2 execution which reused the matrix task ids).
        new_tasks.append(task)

    out = PROJECT_ROOT / "output" / "racer-v2-e3-v03-20260909"
    out.mkdir(parents=True, exist_ok=True)
    spec_path = out / "batch-spec-v03.json"
    spec_path.write_text(json.dumps(new_tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    stamps = sorted({t["run_id"].split("-")[-3] for t in new_tasks})
    protocols = sorted({t["protocol_id"] for t in new_tasks})
    print(f"tasks={len(new_tasks)} stamp={stamps} protocol={protocols}")
    print(f"spec: {spec_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
