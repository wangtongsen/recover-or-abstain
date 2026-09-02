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
import random
import statistics
from pathlib import Path
from typing import Any, Iterable


FAULT_TYPES = ("replace_action", "force_error", "rate_limit", "wrong_tool", "drop_action")
TASK_VARIANTS = ("clean_success", "non_refundable", "suboptimal_refundable", "missing_confirmation", "force_error_confirm", "drop_confirm")
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
        for key in ("rows", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if isinstance(payload, dict):
        return [payload]
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _fault_type(row: dict[str, Any]) -> str:
    explicit = row.get("fault_type")
    if isinstance(explicit, str) and explicit:
        return explicit
    for key in ("cell", "task_variant", "variant"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    task_id = str(row.get("task_id", ""))
    for fault_type in sorted((*FAULT_TYPES, *TASK_VARIANTS), key=len, reverse=True):
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


USAGE_FIELDS = (
    "provider",
    "model",
    "calls",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "latency_ms",
)
_USAGE_INTEGER_FIELDS = {"calls", "prompt_tokens", "completion_tokens", "total_tokens"}


def _usage_payload(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    source = item.get("actor_usage")
    if not isinstance(source, dict):
        source = item.get("llm_usage")
    if not isinstance(source, dict):
        source = item.get("usage")
    if not isinstance(source, dict) and any(key in item for key in USAGE_FIELDS):
        source = item
    if not isinstance(source, dict):
        return None
    usage: dict[str, Any] = {}
    for key in USAGE_FIELDS:
        value = source.get(key)
        if key in {"provider", "model"}:
            usage[key] = value if isinstance(value, str) and value else None
            continue
        value = _number(value)
        if value is None or value < 0 or (key in _USAGE_INTEGER_FIELDS and not float(value).is_integer()):
            usage[key] = None
        elif key in _USAGE_INTEGER_FIELDS:
            usage[key] = int(value)
        else:
            usage[key] = value
    return usage


def _dedupe_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        run_id = row.get("run_id")
        if run_id is not None:
            key = str(run_id)
            if key in seen:
                continue
            seen.add(key)
        unique.append(row)
    return unique


def _usage_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = _dedupe_rows(rows)
    usages = [usage for row in rows if (usage := _usage_payload(row)) is not None]
    summary: dict[str, Any] = {
        "run_count": len(rows),
        "usage_run_count": len(usages),
        "missing_usage_count": len(rows) - len(usages),
    }
    providers = sorted({usage["provider"] for usage in usages if usage["provider"] is not None})
    models = sorted({usage["model"] for usage in usages if usage["model"] is not None})
    summary["provider"] = providers[0] if len(providers) == 1 else None
    summary["model"] = models[0] if len(models) == 1 else None
    if len(providers) > 1:
        summary["providers"] = providers
    if len(models) > 1:
        summary["models"] = models
    for key in USAGE_FIELDS[2:]:
        values = [usage[key] for usage in usages if usage[key] is not None]
        summary[key] = sum(values) if values else None
        if key == "cost_usd" and summary[key] is not None:
            summary[key] = round(summary[key], 8)
        elif key == "latency_ms" and summary[key] is not None:
            summary[key] = round(summary[key], 3)
        summary[f"{key}_available_count"] = len(values)
        summary[f"{key}_missing_count"] = len(usages) - len(values)
    return summary


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
    # Prefer baseline metrics, but retain trajectory-level values for legacy rows.
    confidence = baseline.get("diagnosis_confidence", trajectory.get("diagnosis_confidence"))
    confidence = _number(confidence)
    latency_present = "latency_ms" in baseline or "latency_ms" in trajectory
    latency = baseline.get("latency_ms") if "latency_ms" in baseline else trajectory.get("latency_ms")
    latency = _number(latency) if latency_present else None
    usage = _usage_payload(trajectory)
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
        "recovered_success": _bool(merged.get("recovered_success")),
        "harmful_repair": _bool(merged.get("harmful_repair")),
        "abstained": abstained,
        "attempted": repair_attempted,
        "repair_attempted": repair_attempted,
        "diagnosis_confidence": confidence,
        "confidence": confidence,
        "step_exact": merged.get("step_exact") if isinstance(merged.get("step_exact"), bool) else None,
        "label": merged.get("step_exact") if isinstance(merged.get("step_exact"), bool) else None,
        "latency_ms": latency,
        "latency_available": latency_present and latency is not None,
        "actor_usage": usage,
        **({key: usage.get(key) for key in USAGE_FIELDS} if usage is not None else {key: None for key in USAGE_FIELDS}),
    }


def _confidence_bucket(confidence: float | int | None) -> str:
    if confidence is None or confidence < 0.0 or confidence > 1.0:
        return "missing"
    for lower, upper in zip(CONFIDENCE_EDGES, CONFIDENCE_EDGES[1:]):
        if confidence < upper or (upper == 1.0 and confidence <= upper):
            close = "]" if upper == 1.0 else ")"
            return f"[{lower:.1f}, {upper:.1f}{close}"
    return "missing"


def _calibration_rows(
    rows: Iterable[dict[str, Any]],
    labels: Iterable[Any] | None = None,
) -> list[dict[str, Any]]:
    """Return rows with numeric confidence in [0, 1] and an explicit bool label."""
    if labels is not None:
        source = ({"confidence": confidence, "label": label} for confidence, label in zip(rows, labels))
    else:
        source = rows
    valid: list[dict[str, Any]] = []
    for row in source:
        if not isinstance(row, dict):
            continue
        confidence = _number(row.get("confidence", row.get("diagnosis_confidence")))
        if confidence is None or not 0.0 <= float(confidence) <= 1.0:
            continue
        label = row["label"] if "label" in row else row.get("step_exact")
        if isinstance(label, bool):
            valid.append({"confidence": float(confidence), "label": label})
    return valid


def _calibration_samples(
    rows: Iterable[dict[str, Any]],
    labels: Iterable[Any] | None = None,
) -> list[tuple[float, bool]]:
    return [(row["confidence"], row["label"]) for row in _calibration_rows(rows, labels)]


def _bin_index(confidence: float, edges: tuple[float, ...]) -> int:
    for index, upper in enumerate(edges[1:]):
        if confidence < upper or (index == len(edges) - 2 and confidence <= upper):
            return index
    return len(edges) - 2


def expected_calibration_error(
    rows: Iterable[dict[str, Any]],
    labels: Iterable[Any] | None = None,
    edges: tuple[float, ...] = CONFIDENCE_EDGES,
) -> dict[str, Any]:
    """Calculate ECE and per-bin details from confidence/boolean-label pairs."""
    samples = _calibration_samples(rows, labels)
    if len(edges) < 2 or any(not math.isfinite(float(edge)) for edge in edges):
        raise ValueError("edges must contain at least two finite values")
    if tuple(edges) != tuple(sorted(edges)) or edges[0] < 0.0 or edges[-1] > 1.0:
        raise ValueError("edges must be sorted and within [0, 1]")
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(len(edges) - 1)]
    for confidence, label in samples:
        buckets[_bin_index(confidence, edges)].append((confidence, label))
    n = len(samples)
    bins: list[dict[str, Any]] = []
    ece = 0.0
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        mean_confidence = statistics.fmean(confidence for confidence, _ in bucket)
        accuracy = statistics.fmean(label for _, label in bucket)
        gap = abs(accuracy - mean_confidence)
        contribution = len(bucket) / n * gap
        ece += contribution
        bins.append({
            "lower": float(edges[index]),
            "upper": float(edges[index + 1]),
            "n": len(bucket),
            "mean_confidence": mean_confidence,
            "accuracy": accuracy,
            "gap": gap,
            "contribution": contribution,
        })
    return {"ece": ece if n else None, "n": n, "bins": bins}


def brier_score(
    rows: Iterable[dict[str, Any]], labels: Iterable[Any] | None = None
) -> dict[str, Any]:
    """Calculate the binary Brier score and valid sample count."""
    samples = _calibration_samples(rows, labels)
    return {
        "brier": statistics.fmean((confidence - float(label)) ** 2 for confidence, label in samples)
        if samples else None,
        "n": len(samples),
    }


def risk_coverage(
    rows: Iterable[dict[str, Any]], labels: Iterable[Any] | None = None
) -> dict[str, Any]:
    """Return a descending-confidence risk/coverage curve grouped by ties."""
    samples = _calibration_samples(rows, labels)
    ordered = sorted(enumerate(samples), key=lambda item: (-item[1][0], item[0]))
    n = len(ordered)
    points: list[dict[str, float]] = []
    errors = 0
    index = 0
    while index < n:
        confidence = ordered[index][1][0]
        end = index
        while end < n and ordered[end][1][0] == confidence:
            errors += not ordered[end][1][1]
            end += 1
        retained = end
        current_coverage = retained / n
        current_risk = errors / retained
        points.append({"coverage": current_coverage, "risk": current_risk, "threshold": confidence})
        index = end
    coverage = [point["coverage"] for point in points]
    risks = [point["risk"] for point in points]
    return {
        "n": n,
        "coverage": coverage,
        "risk": risks,
        "points": points,
        "curve": points,
        "aurc": statistics.fmean(risks) if risks else None,
    }


def _percentile(values: list[float], probability: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def bootstrap_ci(
    rows: Iterable[dict[str, Any]],
    metric_fn: Any,
    *,
    n_resamples: int = 1000,
    alpha: float = 0.05,
    seed: int = 0,
    n_bootstrap: int | None = None,
    labels: Iterable[Any] | None = None,
) -> dict[str, Any] | None:
    """Return a reproducible percentile bootstrap CI for a scalar metric."""
    if callable(rows) and not callable(metric_fn):
        rows, metric_fn = metric_fn, rows
    if n_bootstrap is not None:
        n_resamples = n_bootstrap
    if n_resamples <= 0 or not 0.0 <= alpha < 1.0:
        raise ValueError("n_resamples must be positive and alpha in [0, 1)")
    source = _calibration_rows(rows, labels)
    if not source:
        return None
    rng = random.Random(seed)
    estimates: list[float] = []

    def scalar_metric(value: Any) -> float | None:
        if isinstance(value, dict):
            key = "ece" if "ece" in value else "brier" if "brier" in value else "estimate"
            value = value.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if math.isfinite(float(value)) else None

    point = scalar_metric(metric_fn(source))
    if point is None:
        return None
    for _ in range(n_resamples):
        sample = [source[rng.randrange(len(source))] for _ in source]
        estimate = scalar_metric(metric_fn(sample))
        if estimate is not None:
            estimates.append(estimate)
    if not estimates:
        return None
    estimates.sort()
    return {
        "estimate": point,
        "lower": _percentile(estimates, alpha / 2.0),
        "upper": _percentile(estimates, 1.0 - alpha / 2.0),
        "n": len(source),
        "n_resamples": n_resamples,
        "resamples": n_resamples,
        "seed": seed,
    }


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
        "usage": _usage_summary(rows),
        "confidence_reliability": _reliability(rows),
        "calibration": {
            "descriptive": True,
            "note": "校准指标仅描述有效观测行；seed 不是 iid 抽样标识。",
            "n": len(_calibration_samples(rows)),
            "expected_calibration_error": expected_calibration_error(rows),
            "brier_score": brier_score(rows),
            "risk_coverage": risk_coverage(rows),
            "bootstrap_ci": {
                "expected_calibration_error": bootstrap_ci(rows, expected_calibration_error),
                "brier_score": bootstrap_ci(rows, brier_score),
            },
        },
    }


def analyze_payloads(evaluator_payload: Any, results_payload: Any | None = None) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    trajectory_ids: set[str] = set()
    trajectories = _dedupe_rows(_rows(evaluator_payload))
    for trajectory in trajectories:
        if trajectory.get("run_id") is not None:
            trajectory_ids.add(str(trajectory["run_id"]))
        fault_type = _fault_type(trajectory)
        for baseline_id, baseline in _baseline_rows(trajectory):
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
        "usage": _usage_summary(trajectories),
        "groups": groups,
        "inputs": {"evaluator": "reports/local-flight-evaluator.json", "results": "reports/local-flight-results.json"},
        "reference_summary": {
            "trajectory_count": reference.get("trajectory_count"),
            "baseline_row_count": reference.get("baseline_row_count"),
            "group_counts": reference_counts,
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
        "confidence_reliability", "calibration_descriptive", "calibration_n",
        "expected_calibration_error", "brier_score", "risk_coverage",
        "bootstrap_ci",
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
                calibration = metrics.get("calibration")
                calibration = calibration if isinstance(calibration, dict) else {}
                writer.writerow({
                    "fault_type": fault_type,
                    "baseline_id": baseline_id,
                    **{field: _csv_value(metrics.get(field)) for field in fields[2:] if field not in {
                        "calibration_descriptive", "calibration_n", "expected_calibration_error",
                        "brier_score", "risk_coverage", "bootstrap_ci",
                    }},
                    "calibration_descriptive": calibration.get("descriptive"),
                    "calibration_n": calibration.get("n"),
                    "expected_calibration_error": calibration.get("expected_calibration_error"),
                    "brier_score": calibration.get("brier_score"),
                    "risk_coverage": _csv_value(calibration.get("risk_coverage")),
                    "bootstrap_ci": _csv_value(calibration.get("bootstrap_ci")),
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
