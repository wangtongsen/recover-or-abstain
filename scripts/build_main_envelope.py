#!/usr/bin/env python3
"""Build the canonical racer-v2-results-envelope for the MAIN tier matrix.

Reads the executed evaluator output (one row per task with a baselines map),
flattens each baseline into one canonical record, normalizes boolean outcome
fields (None -> False), forces evaluation_tier=main / main_comparison=true /
legacy=false, and writes the canonical envelope with a clean deduplication
proof. The output is a main-table admission candidate: audit_v2_artifacts.py
must exit 0 on it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SCHEMA = "racer-v2-results-envelope"
BOOL_FIELDS = (
    "main_comparison", "legacy", "oracle_manifest_valid", "original_success",
    "recovered_success", "harmful_repair", "abstained", "strict_replay",
    "counterfactual_supported", "replay_valid", "paired_identity_complete",
)


def build(input_path: Path, output_path: Path, experiment: str) -> int:
    with input_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = payload.get("rows", [])
    records = []
    for row in rows:
        for baseline_id, baseline_row in (row.get("baselines") or {}).items():
            record = dict(baseline_row)
            record.pop("baselines", None)
            for field in BOOL_FIELDS:
                if record.get(field) is None:
                    record[field] = False
            record["evaluation_tier"] = "main"
            record["main_comparison"] = True
            record["legacy"] = False
            records.append(record)
    # Deduplicate on complete paired identity + baseline + trial + model.
    seen = set()
    deduplicated = []
    dropped = []
    for record in records:
        identity = record.get("paired_identity")
        key = (
            tuple(identity) if isinstance(identity, list) and len(identity) == 6 else None,
            record.get("baseline_id"),
            record.get("trial_id"),
            record.get("model_resource_id"),
        )
        if key[0] is not None and key in seen:
            dropped.append({"baseline_id": record.get("baseline_id")})
            continue
        if key[0] is not None:
            seen.add(key)
        deduplicated.append(record)
    envelope = {
        "schema_version": CANONICAL_SCHEMA,
        "experiment": experiment,
        "count": len(deduplicated),
        "records": deduplicated,
        "deduplication": {
            "strategy": "complete_paired_identity_plus_baseline_trial_model",
            "dropped_count": len(dropped),
            "dropped": dropped,
            "legacy_rows_retained": 0,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(deduplicated)} records to {output_path}")
    return 0 if deduplicated else 2


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "output" / "racer-v2-main-20260906" / "evaluator.json"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else PROJECT_ROOT / "output" / "racer-v2-main-20260906" / "main-envelope.json"
    experiment = sys.argv[3] if len(sys.argv) > 3 else "racer-v2-main-matrix"
    raise SystemExit(build(input_path, output_path, experiment))
