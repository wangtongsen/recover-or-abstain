#!/usr/bin/env python3
"""Offline verification driver for the isolated-container v2 smoke run.

Reads the smoke trajectory + oracle manifest produced by the Dockerized
agent-runner, then verifies the v2 contract chain end to end:

1. G5 truth isolation: the public trajectory carries no fault truth.
2. Oracle manifest identity join: evaluator accepts truth only via the
   exact full-key join (run/task/source/episode/seed + environment contract).
3. Strict replay receipt: counterfactual branches carry verified provenance.
4. Admission gate: the pilot-tier canonical envelope is correctly rejected
   from the main table.

Standard library only; no containers, models, or provider configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "common"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "evaluator"))

import importlib.util

_evaluator_spec = importlib.util.spec_from_file_location(
    "smoke_evaluator", PROJECT_ROOT / "services" / "evaluator" / "app.py"
)
evaluator = importlib.util.module_from_spec(_evaluator_spec)
_evaluator_spec.loader.exec_module(evaluator)

_audit_spec = importlib.util.spec_from_file_location(
    "smoke_audit", PROJECT_ROOT / "scripts" / "audit_v2_artifacts.py"
)
audit = importlib.util.module_from_spec(_audit_spec)
_audit_spec.loader.exec_module(audit)

SMOKE_SCHEMA = "racer-v2-smoke-verification-v1"


def _load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _walk_keys(value, prefix="$"):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield f"{prefix}.{key}", key
            yield from _walk_keys(nested, f"{prefix}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk_keys(nested, f"{prefix}[{index}]")


def verify(trajectory_path: Path, oracle_path: Path) -> dict:
    issues = []
    checks = {}
    trajectory = _load(trajectory_path)
    oracle = _load(oracle_path)

    # 1. G5: no evaluator-only truth in the public trajectory.
    truth_keys = [path for path, key in _walk_keys(trajectory) if key in {"fault_truth", "oracle_manifest", "target_patch", "future_state"}]
    checks["g5_trajectory_truth_free"] = not truth_keys
    if truth_keys:
        issues.append({"code": "G5_TRAJECTORY_TRUTH_LEAK", "paths": truth_keys[:10]})

    # 2. Oracle identity: trajectory and manifest must agree on the v2 identity.
    identity_fields = ("run_id", "source_run_id", "episode_id", "task_id")
    identity_match = all(trajectory.get(field) == oracle.get(field) for field in identity_fields)
    checks["oracle_identity_fields_match"] = identity_match
    if not identity_match:
        issues.append({"code": "ORACLE_IDENTITY_MISMATCH"})

    # The privileged manifest must carry truth + the source anchor.
    checks["oracle_has_truth"] = isinstance(oracle.get("fault_truth"), list) and bool(oracle["fault_truth"])
    checks["oracle_has_source_anchor"] = isinstance(oracle.get("source_manifest_sha256"), str) and len(oracle["source_manifest_sha256"]) == 64
    checks["oracle_has_contract"] = isinstance(oracle.get("environment_contract"), dict)
    if not checks["oracle_has_truth"]:
        issues.append({"code": "ORACLE_TRUTH_MISSING"})
    if not checks["oracle_has_source_anchor"]:
        issues.append({"code": "ORACLE_ANCHOR_MISSING"})

    # 3. Evaluator full-key join over the produced files.
    row = evaluator.evaluate_file(str(trajectory_path), oracle_path=str(oracle_path))
    checks["evaluator_oracle_join_valid"] = row.get("oracle_manifest_valid") is True
    if not checks["evaluator_oracle_join_valid"]:
        issues.append({"code": "EVALUATOR_ORACLE_JOIN_INVALID"})
    checks["trajectory_tier_is_pilot"] = row.get("evaluation_tier") == "pilot"
    checks["trajectory_main_comparison_false"] = row.get("main_comparison") is False

    # 4. Strict replay receipt on counterfactual branches (raw trajectory, not
    #    evaluator metrics rows — those flatten away the counterfactual body).
    replay_branches = []
    for baseline_id, baseline in (trajectory.get("baselines") or {}).items():
        counterfactual = (baseline or {}).get("counterfactual") or {}
        provenance = counterfactual.get("replay_provenance") or {}
        replay_branches.append({
            "baseline_id": baseline_id,
            "replay_run_id": counterfactual.get("run_id"),
            "provenance_valid": provenance.get("valid") is True,
            "provenance_strict": provenance.get("strict") is True,
            "has_source_contract": isinstance(provenance.get("source_contract"), dict),
        })
    checks["strict_replay_branches"] = replay_branches
    verified = [branch for branch in replay_branches if branch["provenance_valid"] and branch["provenance_strict"]]
    checks["at_least_one_verified_replay"] = bool(verified)
    if not verified:
        issues.append({"code": "NO_VERIFIED_STRICT_REPLAY"})

    # 5. Admission gate: pilot-tier envelope must be rejected from the main table.
    envelope = evaluator.canonical_results_envelope([row], experiment="smoke-v2")
    admission = audit.audit_payload(envelope)
    checks["admission_rejects_pilot_envelope"] = admission["verdict"] == "NO-GO"
    if admission["verdict"] != "NO-GO":
        issues.append({"code": "ADMISSION_UNEXPECTEDLY_PASSED_PILOT_ENVELOPE"})
    checks["admission_codes"] = sorted({issue["code"] for issue in admission.get("issues", [])})

    verdict = "PASS" if not issues else "FAIL"
    return {
        "schema_version": SMOKE_SCHEMA,
        "verdict": verdict,
        "smoke_tier": "pilot",
        "counts": {"replay_branches": len(replay_branches), "verified_replay_branches": len(verified)},
        "checks": checks,
        "admission_verdict": admission["verdict"],
        "issues": issues,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify the isolated-container v2 smoke artifacts")
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("oracle", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = verify(args.trajectory, args.oracle)
    result["input"] = {
        "trajectory": str(args.trajectory),
        "oracle": str(args.oracle),
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
