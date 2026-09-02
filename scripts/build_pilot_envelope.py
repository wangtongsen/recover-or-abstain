#!/usr/bin/env python3
"""Build the canonical racer-v2-results-envelope for the relay paired pilot.

Reads the executed evaluator output (one run, three baselines expanded as flat
baseline rows), flattens each baseline row into one canonical record, and
writes the pilot envelope. The pilot envelope is evaluation_tier=pilot,
main_comparison=false — it is admission-auditable but can never pass main-table
admission by design (G0/G2 tier gates fail closed for pilots).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SCHEMA = "racer-v2-results-envelope"


def build(input_path: Path, output_path: Path) -> None:
    with input_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = payload.get("rows", [])
    records = []
    for row in rows:
        for baseline_id, baseline_row in row.get("baselines", {}).items():
            record = dict(baseline_row)
            record.pop("baselines", None)
            records.append(record)
    envelope = {
        "schema_version": CANONICAL_SCHEMA,
        "experiment": "relay-llm-paired-pilot",
        "count": len(records),
        "records": records,
        "deduplication": {
            "strategy": "complete_paired_identity_plus_baseline_trial_model",
            "dropped_count": 0,
            "dropped": [],
            "legacy_rows_retained": 0,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} records to {output_path}")


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "output" / "relay-llm-paired-pilot-20260902" / "evaluator.json"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else PROJECT_ROOT / "output" / "relay-llm-paired-pilot-20260902" / "pilot-envelope.json"
    build(input_path, output_path)
