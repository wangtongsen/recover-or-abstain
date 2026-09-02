#!/usr/bin/env python3
"""Analyze local-flight evaluator output with only the Python standard library.

Seed values are reproducibility identifiers, not iid samples.  Wilson intervals
are therefore descriptive intervals for the observed rows, not population
claims.  Missing latency stays missing and is reported separately from zero.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable


FAULT_TYPES = ("replace_action", "force_error", "rate_limit", "wrong_tool", "drop_action")
BASELINES = ("raw", "recovery", "oracle")
CONFIDENCE_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
Z95 = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = Z95) -> dict[str, float | int] | None:
    """Return a two-sided 95% Wilson interval, or None when n is zero."""
    if n <= 0:
        return None
    successes = max(0, min(int(successes), int(n)))
    n = int(n)
    p = successes / n
    denominator = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n) / denominator
    lower = max(0.0, centre - margin)
    upper = min(1.0, centre + margin)
    # Avoid exposing floating-point residue at the mathematical boundaries.
    if lower < 1e-15:
        lower = 0.0
    if 1.0 - upper < 1e-15:
        upper = 1.0
    return {
        "successes": successes,
        "n": n,
        "lower": lower,
        "upper": upper,
    }


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        containers = [key for key in ("records", "entries", "results", "rows") if key in payload]
        if len(containers) > 1:
            raise ValueError("ambiguous_results_containers")
        if len(containers) == 1:
            value = payload[containers[0]]
            if not isinstance(value, list):
                raise ValueError("invalid_results_container")
            payload = value
        else:
            return [payload]
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _fault_type(row: dict[str, Any]) -> str:
    explicit = row.get("fault_type")
    if isinstance(explicit, str) and explicit:
        return explicit
    task_id = str(row.get("task_id", ""))
    for fault_type in FAULT_TYPES:
        if f"-{fault_type}-" in task_id or task_id.endswith(f"-{fault_type}"):
            return fault_type
    return "unknown"


def _bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return value
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


REPAIR_DECISIONS = frozenset({
    "oracle_repair",
    "patch",
    "replace_action",
    "replace_argument",
    "repair",
    "replay",
    "retry",
})


def _baseline_rows(row: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    baselines = row.get("baselines")
    if isinstance(baselines, dict):
        for baseline_id, value in baselines.items():
            if isinstance(baseline_id, str) and isinstance(value, dict):
                yield baseline_id, value
        return
    baseline_id = row.get("baseline_id", "recovery")
    if not isinstance(baseline_id, str):
        baseline_id = "recovery"
    yield baseline_id, row


def _metric_row(trajectory: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    merged = dict(trajectory)
    merged.update(baseline)
    decision = merged.get("decision")
    if isinstance(decision, dict):
        decision = decision.get("decision")
    decision_name = str(decision).lower()
    abstained = _bool(merged.get("abstained"), decision_name == "abstain")
    repair_steps = _number(merged.get("repair_steps"))
    explicit_attempt = baseline.get("repair_attempted")
    if explicit_attempt is None and "baselines" not in trajectory:
        explicit_attempt = trajectory.get("repair_attempted")
    repair_attempted = (
        _bool(explicit_attempt)
        if isinstance(explicit_attempt, bool)
        else (not abstained and (
            decision_name in REPAIR_DECISIONS
            or (repair_steps is not None and repair_steps > 0)
            or _bool(merged.get("recovered_success"))
            or _bool(merged.get("harmful_repair"))
        ))
    )
    # Original outcome belongs to the trajectory, not a baseline replay. Legacy
    # rows may omit it at trajectory level, in which case use the baseline value.
    original_value = (
        trajectory["original_success"]
        if "original_success" in trajectory
        else baseline.get("original_success")
    )
    original_success = _bool(original_value)
    recovered_claim = _bool(merged.get("recovered_success"))
    v2_main = (
        merged.get("main_comparison", True) is not False
        and merged.get("legacy") is not True
        and any(key in merged for key in ("strict_replay", "counterfactual_supported", "replay_valid"))
    )
    replay_gate = (
        merged.get("strict_replay") is True
        and merged.get("counterfactual_supported") is True
        and merged.get("replay_valid") is True
    )
    # A v2 main-table recovery claim without verified strict replay is not a
    # recovery statistic. Legacy rows retain their historical descriptive form.
    recovered_success = recovered_claim and (replay_gate if v2_main else True)
    # Prefer baseline metrics, but retain trajectory-level values for legacy rows.
    confidence = baseline.get("diagnosis_confidence", trajectory.get("diagnosis_confidence"))
    confidence = _number(confidence)
    latency_present = "latency_ms" in baseline or "latency_ms" in trajectory
    latency = baseline.get("latency_ms") if "latency_ms" in baseline else trajectory.get("latency_ms")
    latency = _number(latency) if latency_present else None
    # Evaluator's legacy default is 0, which means timing was unavailable rather
    # than a measured zero-duration run.  Keep it null and expose availability.
    if latency is None or latency == 0:
        latency_present = False
        latency = None
    return {
        "task_id": merged.get("task_id"),
        "run_id": merged.get("run_id"),
        "seed": merged.get("seed", merged.get("env_seed")),
        "original_success": original_success,
        "recovered_success": recovered_success,
        "harmful_repair": _bool(merged.get("harmful_repair")),
        "abstained": abstained,
        "attempted": repair_attempted,
        "repair_attempted": repair_attempted,
        "diagnosis_confidence": confidence,
        "step_exact": merged.get("step_exact") if isinstance(merged.get("step_exact"), bool) else None,
        "latency_ms": latency,
        "latency_available": latency_present and latency is not None,
    }


def _confidence_bucket(confidence: float | int | None) -> str:
    if confidence is None or confidence < 0.0 or confidence > 1.0:
        return "missing"
    for lower, upper in zip(CONFIDENCE_EDGES, CONFIDENCE_EDGES[1:]):
        if confidence < upper or (upper == 1.0 and confidence <= upper):
            close = "]" if upper == 1.0 else ")"
            return f"[{lower:.1f}, {upper:.1f}{close}"
    return "missing"


def _reliability(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = _confidence_bucket(row["diagnosis_confidence"])
        buckets.setdefault(bucket, []).append(row)
    ordered = [f"[{lo:.1f}, {hi:.1f}{']' if hi == 1.0 else ')'}" for lo, hi in zip(CONFIDENCE_EDGES, CONFIDENCE_EDGES[1:])]
    ordered.append("missing")
    result = []
    for bucket in ordered:
        selected = buckets.get(bucket, [])
        confidence_values = [row["diagnosis_confidence"] for row in selected if row["diagnosis_confidence"] is not None]
        exact_values = [row["step_exact"] for row in selected if row["step_exact"] is not None]
        exact_count = sum(exact_values)
        result.append(
            {
                "bucket": bucket,
                "n": len(selected),
                "mean_confidence": statistics.fmean(confidence_values) if confidence_values else None,
                "diagnosis_exact_count": exact_count,
                "diagnosis_exact_n": len(exact_values),
                "diagnosis_exact_rate": exact_count / len(exact_values) if exact_values else None,
                "attempted_count": sum(row["attempted"] for row in selected),
                "recovered_count": sum(row["recovered_success"] and not row["original_success"] for row in selected),
                "abstain_count": sum(row["abstained"] for row in selected),
            }
        )
    return result


def _latency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row["latency_ms"] for row in rows if row["latency_available"]]
    available = len(values)
    summary = None
    if values:
        summary = {
            "mean_ms": statistics.fmean(values),
            "median_ms": statistics.median(values),
            "min_ms": min(values),
            "max_ms": max(values),
        }
    return {
        "available_count": available,
        "missing_count": len(rows) - available,
        "availability_rate": available / len(rows) if rows else None,
        "summary": summary,
    }


def aggregate_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    failures = sum(not row["original_success"] for row in rows)
    attempted = sum(row["attempted"] for row in rows)
    recovered = sum(row["recovered_success"] and not row["original_success"] for row in rows)
    harmful = sum(row["harmful_repair"] and not row["original_success"] for row in rows)
    abstain = sum(row["abstained"] for row in rows)
    return {
        "n": n,
        "failures": failures,
        "failure_count": failures,
        "repair_attempted": attempted,
        "attempted_count": attempted,
        "recovered": recovered,
        "recovered_count": recovered,
        "harmful": harmful,
        "harmful_count": harmful,
        "abstain": abstain,
        "abstain_count": abstain,
        "attempted_rate": attempted / n if n else None,
        "recovery_rate": recovered / failures if failures else None,
        "harmful_rate": harmful / failures if failures else None,
        "abstain_rate": abstain / n if n else None,
        "attempted_ci95": wilson_interval(attempted, n),
        "recovery_rate_ci95": wilson_interval(recovered, failures),
        "harmful_rate_ci95": wilson_interval(harmful, failures),
        "abstain_ci95": wilson_interval(abstain, n),
        "latency": _latency(rows),
        "confidence_reliability": _reliability(rows),
    }


def analyze_payloads(evaluator_payload: Any, results_payload: Any | None = None) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    trajectory_ids: set[str] = set()
    seen_pairs: set[tuple[tuple[str, ...], str, str, str]] = set()
    duplicate_pair_count = 0
    for trajectory in _rows(evaluator_payload):
        if trajectory.get("run_id") is not None:
            trajectory_ids.add(str(trajectory["run_id"]))
        fault_type = _fault_type(trajectory)
        for baseline_id, baseline in _baseline_rows(trajectory):
            identity = trajectory.get("paired_identity")
            complete = trajectory.get("paired_identity_complete") is True and isinstance(identity, list)
            if complete:
                trial_id = trajectory.get("trial_id")
                model_resource_id = trajectory.get("model_resource_id")
                if trial_id is None or model_resource_id is None:
                    grouped.setdefault(fault_type, {}).setdefault(baseline_id, []).append(
                        _metric_row(trajectory, baseline)
                    )
                    continue
                pair_key = (tuple(str(part) for part in identity), baseline_id, str(trial_id), str(model_resource_id))
                if pair_key in seen_pairs:
                    duplicate_pair_count += 1
                    continue
                seen_pairs.add(pair_key)
            grouped.setdefault(fault_type, {}).setdefault(baseline_id, []).append(
                _metric_row(trajectory, baseline)
            )
    groups = {
        fault_type: {
            baseline_id: aggregate_group(rows)
            for baseline_id, rows in sorted(baselines.items())
        }
        for fault_type, baselines in sorted(grouped.items())
    }
    reference = results_payload if isinstance(results_payload, dict) else {}
    reference_groups = reference.get("groups") if isinstance(reference.get("groups"), dict) else {}
    reference_counts = {
        fault_type: {baseline_id: metrics.get("count") for baseline_id, metrics in baselines.items() if isinstance(metrics, dict)}
        for fault_type, baselines in reference_groups.items() if isinstance(baselines, dict)
    }
    return {
        "experiment": evaluator_payload.get("experiment", "local-flight") if isinstance(evaluator_payload, dict) else "local-flight",
        "trajectory_count": len(trajectory_ids),
        "baseline_row_count": sum(metrics["n"] for baselines in groups.values() for metrics in baselines.values()),
        "groups": groups,
        "inputs": {"evaluator": "reports/local-flight-evaluator.json", "results": "reports/local-flight-results.json"},
        "reference_summary": {
            "trajectory_count": reference.get("trajectory_count"),
            "baseline_row_count": reference.get("baseline_row_count"),
            "group_counts": reference_counts,
        },
        "paired_deduplication": {
            "strategy": "complete_paired_identity_plus_baseline",
            "dropped_duplicate_rows": duplicate_pair_count,
            "legacy_rows_retained": True,
        },
        "seed_note": "seed 仅是可复现标识而非 iid 样本；Wilson 区间仅描述观测行，不代表独立同分布总体推断。",
    }


def analyze_files(evaluator_path: str | Path, results_path: str | Path) -> dict[str, Any]:
    with Path(evaluator_path).open(encoding="utf-8") as handle:
        evaluator_payload = json.load(handle)
    with Path(results_path).open(encoding="utf-8") as handle:
        results_payload = json.load(handle)
    return analyze_payloads(evaluator_payload, results_payload)


def write_json(result: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return value


def write_csv(result: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "fault_type", "baseline_id", "n", "failures", "failure_count", "repair_attempted",
        "recovered", "harmful", "abstain", "attempted_count", "recovered_count",
        "harmful_count", "abstain_count", "attempted_rate", "recovery_rate",
        "harmful_rate", "abstain_rate", "recovery_rate_ci95",
        "attempted_ci95", "harmful_rate_ci95", "abstain_ci95", "latency",
        "confidence_reliability",
    ]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        groups = result.get("groups", {})
        if not isinstance(groups, dict):
            return
        for fault_type in sorted(groups):
            baselines = groups[fault_type]
            if not isinstance(baselines, dict):
                continue
            for baseline_id in sorted(baselines):
                metrics = baselines[baseline_id]
                if not isinstance(metrics, dict):
                    continue
                writer.writerow({
                    "fault_type": fault_type,
                    "baseline_id": baseline_id,
                    **{field: _csv_value(metrics.get(field)) for field in fields[2:]},
                })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="分析 local-flight 评估结果并输出统计")
    parser.add_argument("--evaluator", default="reports/local-flight-evaluator.json")
    parser.add_argument("--results", default="reports/local-flight-results.json")
    parser.add_argument("--output-json", default="reports/local-flight-statistics.json")
    parser.add_argument("--output-csv", default="reports/local-flight-statistics.csv")
    args = parser.parse_args(argv)
    result = analyze_files(args.evaluator, args.results)
    write_json(result, args.output_json)
    write_csv(result, args.output_csv)
    print(f"已生成统计: {args.output_json} 和 {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
