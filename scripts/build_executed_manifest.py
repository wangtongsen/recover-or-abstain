#!/usr/bin/env python3
"""Build the executed preflight manifest for the RACER v2 main matrix.

Constructs the manifest directly (not via build_manifest's trial re-expansion)
so planned cells match the executed envelope exactly:

  - planned cells: 11 cells x 14 baselines x 5 trials = 770,
    task_id is the trial-stripped cell id (e.g. "main-e1-force_error"),
  - executed artifacts: one per envelope record, same stripped key,
  - model registry: the no-key registry entries,
  - protocol: the frozen protocol markdown hash.

The manifest is audited inline with benchmark_preflight.audit_manifest and the
verdict is embedded; benchmark_preflight.py --audit must then exit 0.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from benchmark_preflight import REQUIRED_TRIAL_IDS, audit_manifest  # noqa: E402

SCHEMA_VERSION = "racer-v2-benchmark-preflight-v1"
PROTOCOL_ID = "racer-v2-benchmark-protocol-0.1"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stripped_task(task_id: str) -> str:
    text = str(task_id)
    return text.rsplit("-trial-", 1)[0] if "-trial-" in text else text


def main() -> int:
    matrix_path = PROJECT_ROOT / "experiments" / "racer-v2-main-matrix.json"
    protocol_path = PROJECT_ROOT / "reports" / "racer-v2-benchmark-protocol.md"
    registry_path = PROJECT_ROOT / "experiments" / "racer-v2-model-registry.json"
    envelope_path = PROJECT_ROOT / "output" / "racer-v2-main-20260906" / "main-envelope.json"
    out_path = PROJECT_ROOT / "output" / "racer-v2-main-20260906" / "preflight-manifest.json"

    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    registry_payload = json.loads(registry_path.read_text(encoding="utf-8"))
    model_registry = [r for r in registry_payload.get("model_resources", []) if isinstance(r, dict)]
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    records = [r for r in envelope.get("records", []) if isinstance(r, dict)]

    # Planned cells: one per (stripped cell task, baseline, trial) using the
    # matrix's own trial expansion (55 tasks = 11 cells x 5 trials).
    planned_cells = []
    for task in matrix.get("tasks", []):
        cell_task = _stripped_task(task.get("task_id"))
        baselines = task.get("baselines") or []
        model_id = task.get("model_resource_id")
        for baseline in baselines:
            planned_cells.append({
                "matrix_id": "racer-v2-main-matrix",
                "task_id": cell_task,
                "episode_id": task.get("episode_id"),
                "source_run_id": task.get("run_id"),
                "env_seed": task.get("seed"),
                "baseline_id": baseline,
                "trial_id": task.get("trial_id"),
                "model_resource_id": model_id,
                "evaluation_tier": task.get("evaluation_tier", "main"),
                "baseline_registry_version": task.get("baseline_registry_version"),
                "main_comparison": task.get("main_comparison", True),
                "strict_replay": task.get("strict_replay") is True,
                "status": "planned",
            })
    # Deduplicate planned cells: 55 tasks share the same stripped cell per
    # trial group, so (cell, baseline, trial) is the unique planned identity.
    dedup_planned = []
    seen_planned = set()
    for cell in planned_cells:
        key = (cell["task_id"], cell["baseline_id"], cell["trial_id"], cell["model_resource_id"])
        if key in seen_planned:
            continue
        seen_planned.add(key)
        dedup_planned.append(cell)
    planned_cells = dedup_planned

    # Executed artifacts: one per envelope record under the same stripped key.
    envelope_sha = _sha256_file(envelope_path)
    executed = []
    seen_executed = set()
    for row in records:
        key = (
            "racer-v2-main-matrix",
            _stripped_task(row.get("task_id")),
            row.get("baseline_id"),
            row.get("trial_id"),
            row.get("model_resource_id"),
        )
        if key in seen_executed:
            continue
        seen_executed.add(key)
        executed.append({
            "matrix_id": key[0],
            "task_id": key[1],
            "episode_id": row.get("episode_id"),
            "source_run_id": row.get("source_run_id"),
            "run_id": row.get("run_id"),
            "env_seed": row.get("seed"),
            "baseline_id": row.get("baseline_id"),
            "trial_id": row.get("trial_id"),
            "model_resource_id": row.get("model_resource_id"),
            "evaluation_tier": row.get("evaluation_tier", "main"),
            "baseline_registry_version": row.get("baseline_registry_version"),
            "main_comparison": row.get("main_comparison", True),
            "strict_replay": row.get("strict_replay") is True,
            "status": "executed",
            "artifact_sha256": envelope_sha,
        })

    matrices = [{
        "matrix_id": "racer-v2-main-matrix",
        "matrix_version": matrix.get("schema_version"),
        "path": str(matrix_path),
        "sha256": _sha256_file(matrix_path),
        "task_count": len(matrix.get("tasks", [])),
        "baselines": matrix.get("tasks", [{}])[0].get("baselines", []) if matrix.get("tasks") else [],
        "seeds": [],
    }]

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "protocol": {
            "protocol_id": PROTOCOL_ID,
            "path": str(protocol_path),
            "sha256": _sha256_file(protocol_path),
        },
        "matrices": matrices,
        "required_trial_ids": list(REQUIRED_TRIAL_IDS),
        "planned_cells": planned_cells,
        "model_registry": model_registry,
        "executed_artifacts": executed,
        "blockers": [],
        "verdict": "NO-GO",
    }
    audit = audit_manifest(manifest)
    manifest["blockers"] = audit["blockers"]
    manifest["verdict"] = audit["verdict"]
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps({k: v for k, v in manifest.items() if k != "manifest_sha256"}, sort_keys=True).encode("utf-8")
    ).hexdigest()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"planned={len(planned_cells)} executed={len(executed)} verdict={audit['verdict']} blockers={audit['blockers'][:5]}")
    return 0 if audit["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
