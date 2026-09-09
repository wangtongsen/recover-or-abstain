#!/usr/bin/env python3
"""Stamp the independent-oracle labels and v0.5 identity fields onto a
canonical v0.5 envelope produced by the evaluator.

Two-stage pipeline (protocol v0.5 R.1):
  Stage A (in-container): services/evaluator/app.py evaluate_file over the
    runner trajectories with the privileged oracle join, then
    canonical_results_envelope -> raw canonical envelope (metrics, receipts,
    paired identities, dedup proof). The canonical invocation is:
      docker compose -f compose.yaml --profile analysis run --rm --no-deps \
        -v "<repo>/output:/app/output:rw" evaluator python3 - <<PY
        import json, sys, glob; sys.path.insert(0, "/app"); import app as ev
        rows = [ev.evaluate_file(p, oracle_path="/data/oracle/"+p.rsplit("/",1)[1])
                for p in sorted(glob.glob("/data/trajectories/<run-prefix>-*.json"))]
        env = ev.canonical_results_envelope({"results": rows}, experiment="<exp>")
        json.dump(env, open("/app/output/<raw-envelope>.json", "w"), ensure_ascii=False, indent=2)
        PY
  Stage B (this script, offline): stamp the independent oracle labels
    (annotate_v05_runs.py output), domain/scenario_id identity, and the v0.5
    label-source fields; fail closed on label disagreement.

Fail-closed checks:
  1. every record must find an oracle annotation row (run_id + baseline_id);
  2. oracle harm label must be a bool (rows with evidence_error fail closed);
  3. runtime harmful_repair vs oracle harm disagreement -> hard STOP for
     manual adjudication (same policy as rebuild_v04_envelope.py).

Usage:
  python scripts/build_v05_envelope.py <raw-envelope.json> <annotation.json> \
      --spec <batch-spec.json> --experiment <id> --output <envelope.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Behavioral fields that must never drift when harm labels are overwritten.
BEHAVIOR_FIELDS = (
    "recovered_success", "abstained", "decision", "original_success",
    "repair_steps", "latency_ms", "diagnosis_top1", "step_exact",
)


# Boolean outcome/provenance fields normalized None -> False (v0.1/v0.3
# build_main_envelope semantics: absence of evidence is "not supported",
# never an invalid null that fails the G7 boolean gate).
BOOL_FIELDS = (
    "main_comparison", "legacy", "oracle_manifest_valid", "original_success",
    "recovered_success", "harmful_repair", "abstained", "strict_replay",
    "counterfactual_supported", "replay_valid", "paired_identity_complete",
    "idempotent_replay", "reconciled", "refund_witness_valid",
    "direct_applied", "direct_apply_receipt_valid",
)


def _load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _oracle_lookup(annotation: dict) -> dict:
    """run_id -> baseline_id -> oracle label entry."""
    lookup = {}
    for row in annotation.get("annotations", []):
        lookup[row["run_id"]] = row.get("baselines") or {}
    return lookup


def build_envelope(raw_envelope: dict, annotation: dict, spec: dict, experiment: str) -> dict:
    envelope = dict(raw_envelope)
    envelope["experiment"] = experiment
    envelope["count"] = len(raw_envelope.get("records", []))
    lookup = _oracle_lookup(annotation)
    task_map = {t.get("task_id"): t for t in spec.get("tasks", [])}
    mismatches = []
    for record in envelope["records"]:
        for field in BOOL_FIELDS:
            if record.get(field) is None:
                record[field] = False
        run_id = record.get("run_id")
        baseline_id = record.get("baseline_id")
        oracle_entry = lookup.get(run_id, {}).get(baseline_id)
        if oracle_entry is None:
            raise ValueError(f"annotation missing run/baseline: {run_id}/{baseline_id}")
        oracle_harm = oracle_entry.get("oracle_harm")
        if not isinstance(oracle_harm, bool):
            raise ValueError(
                f"oracle label unavailable: {run_id}/{baseline_id}: {oracle_entry.get('evidence_error')}")
        runtime_harm = record.get("harmful_repair") is True
        if oracle_harm != runtime_harm:
            mismatches.append({
                "run_id": run_id, "baseline_id": baseline_id,
                "runtime_harm": runtime_harm, "oracle_harm": oracle_harm,
                "evidence_form": oracle_entry.get("evidence_form"),
            })
        record["harmful_repair"] = oracle_harm
        record["harm_recomputed"] = oracle_harm
        record["harm_label_source"] = "independent_oracle_v05"
        record["cf_outcome_harm"] = bool(oracle_entry.get("veto_prediction_harm")) \
            if oracle_entry.get("veto_prediction_harm") is not None else False
        task = task_map.get(record.get("task_id"))
        if task is None:
            raise ValueError(f"spec task missing for task_id: {record.get('task_id')}")
        record["domain"] = task.get("domain")
        if task.get("scenario_id") is not None:
            record["scenario_id"] = task["scenario_id"]
    if mismatches:
        raise SystemExit(
            "RUNTIME_ORACLE_HARM_DISAGREEMENT: "
            + json.dumps(mismatches[:5], ensure_ascii=False)
            + f" ({len(mismatches)} rows) — manual adjudication required")
    return envelope


def verify_behavior_zero_drift(before: dict, after: dict) -> list[dict]:
    """Behavior fields must be identical between raw and stamped envelopes."""
    before_rows = {(r["run_id"], r["baseline_id"]): r for r in before.get("records", [])}
    drift = []
    for row in after.get("records", []):
        key = (row.get("run_id"), row.get("baseline_id"))
        old = before_rows.get(key)
        if old is None:
            drift.append({"key": key, "issue": "row_absent_in_raw"})
            continue
        for field in BEHAVIOR_FIELDS:
            if old.get(field) != row.get(field):
                drift.append({"key": key, "field": field, "raw": old.get(field), "stamped": row.get(field)})
    return drift


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Stamp v0.5 oracle labels onto a raw canonical envelope")
    parser.add_argument("raw_envelope", type=Path)
    parser.add_argument("annotation", type=Path)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    raw = _load(args.raw_envelope)
    annotation = _load(args.annotation)
    spec = _load(args.spec)
    stamped = build_envelope(raw, annotation, spec, args.experiment)
    drift = verify_behavior_zero_drift(raw, stamped)
    if drift:
        raise SystemExit("BEHAVIOR_DRIFT_DETECTED: " + json.dumps(drift[:5], ensure_ascii=False))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(stamped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {stamped['count']} records to {args.output}; oracle labels stamped (v05)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
