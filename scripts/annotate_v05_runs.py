#!/usr/bin/env python3
"""v0.5 annotation pipeline: independent oracle labels over execution runs.

Input: a runner execution artifact ({count, results:[...]}, one result per
episode, each carrying trace + 14 baselines) plus the model_resource_id of
the pass. Output: an annotation JSON with, per episode per baseline:

  - truth binding (fingerprint) from the frozen spec env_config
  - chain verification of cf/direct evidence (harm_oracle)
  - oracle terminal labels (harm/success) per protocol v0.4 I.3 semantics,
    parametrized to 3 domains (v0.5)
  - veto prediction labels for vetoed rows
  - agreement with the runner's runtime side_effect signals (informational)

Also emits a compact per-scenario x per-baseline separation table used by
the GO/NO-GO check (protocol v0.5 R.2-5).

Usage:
  python scripts/annotate_v05_runs.py <run.json> --model <model_resource_id> \
      --out <annotation.json> --table <separation-table.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "common"))
import harm_oracle as oracle  # noqa: E402

RETRY_FAMILY = [
    "fixed_retry", "exponential_backoff", "generic_reflection", "full_trace_judge",
    "step_by_step_diagnosis", "binary_search_diagnosis", "agentdebug_targeted_feedback",
    "always_recover",
]
RACER_FAMILY = ["racer", "racer_no_abstain"]


def source_final_state(result):
    trace = result.get("trace") or []
    if not trace:
        return None
    obs = trace[-1].get("observation")
    return obs.get("state") if isinstance(obs, dict) else None


def annotate_run(run_path: Path, model_resource_id: str):
    data = json.loads(run_path.read_text(encoding="utf-8"))
    results = data.get("results", [])
    annotations = []
    separation = defaultdict(lambda: defaultdict(lambda: {"harm": 0, "abstain": 0, "n": 0, "fault_fired": "unknown"}))
    for result in results:
        task_id = result.get("task_id", "")
        scenario_id = result.get("scenario_id") or (task_id.split("-")[2] + "-" + task_id.split("-")[3] if task_id.count("-") >= 3 else task_id)
        env_config = result.get("environment_contract", {}).get("env_config") or {}
        # The runner's canonical env_config lives in the contract; fall back
        # to the original spec embedded in reset (not present in results).
        if not env_config:
            # reconstruct from the batch spec task (same task_id)
            env_config = _env_config_from_spec(task_id)
        truth = oracle.truth_from_env_config(env_config)
        row = {
            "task_id": task_id,
            "scenario_id": scenario_id,
            "model_resource_id": model_resource_id,
            "run_id": result.get("run_id"),
            "termination_reason": result.get("termination_reason"),
            "truth_binding_fingerprint": oracle.truth_binding_fingerprint(truth),
            "source_chain": oracle.verify_trace_state_chain(result.get("trace") or []),
            "source_initial_state": oracle.verify_initial_state(result.get("trace") or [], truth),
            "baselines": {},
        }
        src_state = source_final_state(result)
        fault_fired = result.get("termination_reason") == "tool_error"
        for baseline_id, entry in (result.get("baselines") or {}).items():
            label = oracle.label_baseline(entry, truth, src_state)
            row["baselines"][baseline_id] = label
            sep = separation[scenario_id][baseline_id]
            sep["n"] += 1
            sep["harm"] += 1 if label.get("oracle_harm") is True else 0
            sep["abstain"] += 1 if (entry.get("decision") or {}).get("decision") == "abstain" else 0
            sep["fault_fired"] = "yes" if fault_fired else "no"
        annotations.append(row)
    return annotations, separation


def _env_config_from_spec(task_id: str):
    # batch specs embed the full env_config; load from the known run dirs
    for spec_path in sorted((PROJECT_ROOT / "output").glob("racer-v2-v05-run-*/batch-spec.json")):
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for task in spec.get("tasks", []):
            if task.get("task_id") == task_id:
                return task.get("env_config") or {}
    return {}


def separation_table(separation, model_resource_id):
    out = {"model_resource_id": model_resource_id, "scenarios": {}}
    for scenario_id in sorted(separation):
        rows = separation[scenario_id]
        retry_rows = [rows[b] for b in RETRY_FAMILY]
        racer_rows = [rows[b] for b in RACER_FAMILY]
        no_cf = rows.get("racer_no_counterfactual", {"harm": 0, "n": 0})
        out["scenarios"][scenario_id] = {
            "fault_fired": rows["racer"]["fault_fired"] if "racer" in rows else "unknown",
            "retry_family_harm": f"{sum(r['harm'] for r in retry_rows)}/{sum(r['n'] for r in retry_rows)}",
            "racer_family_veto_abstain": f"{sum(r['abstain'] for r in racer_rows)}/{sum(r['n'] for r in racer_rows)}",
            "no_counterfactual_harm": f"{no_cf['harm']}/{no_cf['n']}",
            "per_baseline": {b: {"harm": rows[b]["harm"], "abstain": rows[b]["abstain"], "n": rows[b]["n"]} for b in sorted(rows)},
        }
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--table", type=Path, required=True)
    args = parser.parse_args()
    annotations, separation = annotate_run(args.run, args.model)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "schema_version": "racer-v2-v05-oracle-annotation-v1",
        "harm_label_source": oracle.ORACLE_LABEL_VERSION_V05,
        "model_resource_id": args.model,
        "episodes": len(annotations),
        "annotations": annotations,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    table = separation_table(separation, args.model)
    args.table.write_text(json.dumps(table, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    # GO-style summary to stdout
    print(f"episodes: {len(annotations)}")
    for sid, info in table["scenarios"].items():
        print(f"  {sid}: fault={info['fault_fired']} retry-harm={info['retry_family_harm']} "
              f"racer-abstain={info['racer_family_veto_abstain']} no_cf-harm={info['no_counterfactual_harm']}")


if __name__ == "__main__":
    main()
