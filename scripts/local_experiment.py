#!/usr/bin/env python3
"""Generate and summarize reproducible local-flight experiments.

Only the Python standard library is required.  The generated specification is
consumed by ``agent_runner`` through its ``BATCH_SPEC`` environment variable.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_DIRECTORIES = tuple(
    PROJECT_ROOT / name for name in ("trajectories", "experiments", "reports")
)
OUTPUT_DIRECTORY = PROJECT_ROOT / "output"
INPUT_DIRECTORIES = (*ALLOWED_DIRECTORIES, OUTPUT_DIRECTORY)
BASELINES = ("raw", "recovery", "oracle")
PILOT_BASELINE_CATALOG = {
    "raw": {"role": "pilot_reference", "maps_to_protocol_id": None, "eligible_for_main": False},
    "recovery": {"role": "pilot_local_recovery", "maps_to_protocol_id": None, "eligible_for_main": False},
    "oracle": {"role": "oracle_upper_bound", "maps_to_protocol_id": None, "eligible_for_main": False},
}
FAULT_TYPES = ("replace_action", "force_error", "rate_limit", "wrong_tool", "drop_action")
TASK_VARIANTS = ("clean_success", "non_refundable", "suboptimal_refundable", "missing_confirmation", "force_error_confirm", "drop_confirm")
SEEDS = (0, 1, 2)
DEFAULT_ACTIONS = [
    {"tool": "search_flights", "arguments": {}},
    {"tool": "select_flight", "arguments": {"flight_id": "F2"}},
    {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
]


def _allowed_path(path: str | os.PathLike[str], *, output: bool = False) -> Path:
    """Resolve a path and reject filesystem operations outside project outputs."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    allowed_directories = ALLOWED_DIRECTORIES if output else INPUT_DIRECTORIES
    for directory in allowed_directories:
        allowed = directory.resolve()
        try:
            resolved.relative_to(allowed)
        except ValueError:
            continue
        if not output and allowed == OUTPUT_DIRECTORY.resolve() and resolved == allowed:
            continue
        return resolved
    action = "输出" if output else "输入"
    allowed_text = ", ".join(str(item) for item in allowed_directories)
    raise ValueError(f"{action}路径必须位于项目目录 {allowed_text} 内: {resolved}")


def _fault_for(fault_type: str, seed: int) -> Dict[str, Any]:
    fault: Dict[str, Any] = {
        "fault_id": f"{fault_type}-{seed}",
        "type": fault_type,
        "step_id": 1,
    }
    if fault_type == "replace_action":
        # The default action requests the unsafe F2, while the injected
        # effective action is the safe F1.  This creates an observable
        # requested/effective mismatch without exposing fault truth.
        fault["replacement"] = {
            "tool": "select_flight",
            "arguments": {"flight_id": "F1"},
        }
    elif fault_type in {"force_error", "rate_limit"}:
        fault["error"] = f"injected {fault_type}"
    return fault


def build_spec() -> Dict[str, Any]:
    """Build the deterministic fault-type x seed experiment matrix."""
    tasks: List[Dict[str, Any]] = []
    for fault_type in FAULT_TYPES:
        for seed in SEEDS:
            fault = _fault_for(fault_type, seed)
            tasks.append(
                {
                    "task_id": f"local-flight-{fault_type}-seed-{seed}",
                    "run_id": f"local-flight-{fault_type}-{seed}",
                    "seed": seed,
                    "episode_id": f"local-flight-{fault_type}-seed-{seed}",
                    "strict_replay": True,
                    "evaluation_tier": "pilot",
                    "baseline_registry_version": "local-flight-pilot-v1",
                    "main_comparison": False,
                    "fault_type": fault_type,
                    "faults": [copy.deepcopy(fault)],
                    # Fault truth is derived only by agent_runner's privileged
                    # oracle writer from the injected schedule; it is never part
                    # of the agent-visible batch task specification.
                    "baselines": list(BASELINES),
                    "actions": copy.deepcopy(DEFAULT_ACTIONS),
                }
            )
    return {
        "experiment": "local-flight",
        "version": 1,
        "description": "Deterministic local flight fault matrix",
        "environment": "task-env",
        "experiment_role": "pilot",
        "main_comparison": False,
        "baseline_registry_version": "local-flight-pilot-v1",
        "baseline_catalog": copy.deepcopy(PILOT_BASELINE_CATALOG),
        "baselines": list(BASELINES),
        "fault_types": list(FAULT_TYPES),
        "seeds": list(SEEDS),
        "tasks": tasks,
    }


def build_extended_spec() -> Dict[str, Any]:
    """Build task-semantic cells that vary constraints and confirmation faults."""
    tasks: List[Dict[str, Any]] = []
    for variant in TASK_VARIANTS:
        for seed in SEEDS:
            if variant == "clean_success":
                actions = [
                    {"tool": "search_flights", "arguments": {}},
                    {"tool": "select_flight", "arguments": {"flight_id": "F1"}},
                    {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
                ]
            elif variant == "non_refundable":
                actions = [
                    {"tool": "search_flights", "arguments": {}},
                    {"tool": "select_flight", "arguments": {"flight_id": "F2"}},
                    {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
                ]
            elif variant == "suboptimal_refundable":
                actions = [
                    {"tool": "search_flights", "arguments": {}},
                    {"tool": "select_flight", "arguments": {"flight_id": "F3"}},
                    {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
                ]
            elif variant == "missing_confirmation":
                actions = [
                    {"tool": "search_flights", "arguments": {}},
                    {"tool": "select_flight", "arguments": {"flight_id": "F1"}},
                    {"tool": "confirm_booking", "arguments": {"user_confirmed": False}},
                ]
            else:
                actions = [
                    {"tool": "search_flights", "arguments": {}},
                    {"tool": "select_flight", "arguments": {"flight_id": "F1"}},
                    {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
                ]
            if variant in {"clean_success", "force_error_confirm", "drop_confirm"}:
                flights = [
                    {"id": "F1", "price": 390, "refundable": True},
                    {"id": "F2", "price": 350, "refundable": False},
                    {"id": "F3", "price": 450, "refundable": True},
                ]
                budget = 500
            elif variant == "suboptimal_refundable":
                flights = [
                    {"id": "F1", "price": 400, "refundable": True},
                    {"id": "F2", "price": 450, "refundable": False},
                    {"id": "F3", "price": 480, "refundable": True},
                ]
                budget = 500
            elif variant == "missing_confirmation":
                flights = [
                    {"id": "F1", "price": 410, "refundable": True},
                    {"id": "F2", "price": 360, "refundable": False},
                    {"id": "F3", "price": 440, "refundable": True},
                ]
                budget = 450
            else:
                flights = [
                    {"id": "F1", "price": 420, "refundable": False},
                    {"id": "F2", "price": 360, "refundable": False},
                    {"id": "F3", "price": 480, "refundable": False},
                ]
                budget = 500
            invariants = [
                "selected_flight must satisfy task variant",
                "price must be <= budget",
                "selected_flight must be cheapest eligible flight",
                "confirmation requires explicit user confirmation",
            ]
            env_config = {
                "budget": budget,
                "flights": copy.deepcopy(flights),
                "task_variant": variant,
                "variant": variant,
                "actions": copy.deepcopy(actions),
                "invariants": copy.deepcopy(invariants),
            }
            variant_faults = ([
                {"fault_id": "force-error-confirm", "type": "force_error", "step_id": 2},
            ] if variant == "force_error_confirm" else [
                {"fault_id": "drop-confirm", "type": "drop_action", "step_id": 2},
            ] if variant == "drop_confirm" else [])
            env_config["faults"] = copy.deepcopy(variant_faults)
            tasks.append({
                "task_id": f"local-flight-extended-{variant}-seed-{seed}",
                "run_id": f"local-flight-extended-{variant}-{seed}",
                "seed": seed,
                "episode_id": f"local-flight-extended-{variant}-seed-{seed}",
                "strict_replay": True,
                "evaluation_tier": "pilot",
                "baseline_registry_version": "local-flight-pilot-v1",
                "main_comparison": False,
                "task_variant": variant,
                "variant": variant,
                "cell": variant,
                "env_config": env_config,
                "reset": copy.deepcopy(env_config),
                "faults": copy.deepcopy(variant_faults),
                "baselines": list(BASELINES),
                "actions": actions,
            })
    return {
        "experiment": "local-flight-extended",
        "version": 1,
        "description": "Task-semantic local flight cells: constraints, planning quality, confirmation, and tool faults",
        "environment": "task-env",
        "experiment_role": "pilot",
        "main_comparison": False,
        "baseline_registry_version": "local-flight-pilot-v1",
        "baseline_catalog": copy.deepcopy(PILOT_BASELINE_CATALOG),
        "baselines": list(BASELINES),
        "task_variants": list(TASK_VARIANTS),
        "seeds": list(SEEDS),
        "tasks": tasks,
    }


def write_extended_spec(path: str | os.PathLike[str]) -> Path:
    target = _allowed_path(path, output=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(build_extended_spec(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, target)
    return target


def write_spec(path: str | os.PathLike[str]) -> Path:
    target = _allowed_path(path, output=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(build_spec(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, target)
    return target


def _is_mapping(value: Any) -> bool:
    return isinstance(value, dict)


def _nested_mapping(value: Any, *keys: str) -> Dict[str, Any]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _success(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _baseline_items(item: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    baselines = item.get("baselines")
    if isinstance(baselines, dict):
        for baseline_id, value in baselines.items():
            if isinstance(baseline_id, str) and isinstance(value, dict):
                yield baseline_id, value
        return
    decision = item.get("decision")
    baseline_id = item.get("baseline_id")
    if not isinstance(baseline_id, str) and isinstance(decision, dict):
        baseline_id = decision.get("baseline_id")
    if not isinstance(baseline_id, str):
        baseline_id = "recovery"
    yield baseline_id, item


def _fault_type(item: Dict[str, Any]) -> str:
    explicit = item.get("fault_type")
    if isinstance(explicit, str) and explicit:
        return explicit
    variant = item.get("cell", item.get("task_variant", item.get("variant")))
    if isinstance(variant, str) and variant:
        return variant
    for key in ("faults_applied", "fault_truth", "faults"):
        entries = item.get(key)
        if isinstance(entries, dict):
            entries = entries.get("faults", entries.get("fault_truth", [entries]))
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and isinstance(entry.get("type"), str):
                    return entry["type"]
    task_id = str(item.get("task_id", ""))
    for fault_type in (*FAULT_TYPES, *TASK_VARIANTS):
        if fault_type in task_id:
            return fault_type
    return "unknown"


def _baseline_metrics(item: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    original = item.get("original_evaluation")
    if not isinstance(original, dict):
        original = item.get("original") if isinstance(item.get("original"), dict) else {}
    baseline_original = baseline.get("original_evaluation")
    if isinstance(baseline_original, dict):
        original = baseline_original

    counterfactual = baseline.get("counterfactual")
    if not isinstance(counterfactual, dict):
        counterfactual = baseline.get("recovered") if isinstance(baseline.get("recovered"), dict) else {}
    evaluation = counterfactual.get("evaluation")
    if not isinstance(evaluation, dict) and "success" in counterfactual:
        evaluation = counterfactual
    if not isinstance(evaluation, dict):
        evaluation = {}

    original_success = baseline.get("original_success", original.get("success", False))
    recovered_success = baseline.get("recovered_success", evaluation.get("success", False))
    harmful = baseline.get(
        "harmful_repair",
        evaluation.get("harmful_repair", evaluation.get("side_effect", False)),
    )
    decision = baseline.get("decision")
    if isinstance(decision, dict):
        decision = decision.get("decision")
    abstained = baseline.get("abstained", str(decision).lower() == "abstain")
    return {
        "task_id": item.get("task_id"),
        "run_id": item.get("run_id"),
        "seed": item.get("seed", item.get("env_seed")),
        "original_success": _success(original_success),
        "recovered_success": _success(recovered_success),
        "harmful_repair": _success(harmful),
        "abstained": _success(abstained),
    }


def _aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    count = len(rows)
    failure_count = sum(not row["original_success"] for row in rows)
    recovered_count = sum(
        row["recovered_success"] for row in rows if not row["original_success"]
    )
    harmful_count = sum(
        row["harmful_repair"] for row in rows if not row["original_success"]
    )
    abstained_count = sum(row["abstained"] for row in rows)
    rate = lambda numerator, denominator: numerator / denominator if denominator else 0.0
    seeds = sorted({row.get("seed") for row in rows if row.get("seed") is not None})
    task_ids = sorted({row.get("task_id") for row in rows if row.get("task_id") is not None})
    run_ids = sorted({row.get("run_id") for row in rows if row.get("run_id") is not None})
    return {
        "count": count,
        "failure_count": failure_count,
        "original_success_count": count - failure_count,
        "recovered_count": recovered_count,
        "harmful_count": harmful_count,
        "abstained_count": abstained_count,
        "recovery_rate": rate(recovered_count, failure_count),
        "harm_rate": rate(harmful_count, failure_count),
        "abstention_rate": rate(abstained_count, count),
        "seed_count": len(seeds),
        "seeds": seeds,
        "task_ids": task_ids,
        "run_ids": run_ids,
    }


def _records_from_payload(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        payload = payload["results"]
    elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        payload = payload["rows"]
    if isinstance(payload, list):
        for value in payload:
            if isinstance(value, dict):
                yield value
    elif isinstance(payload, dict):
        yield payload


def write_csv(result: Dict[str, Any], output_csv: str | os.PathLike[str]) -> Path:
    target = _allowed_path(output_csv, output=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "fault_type", "baseline_id", "count", "failure_count",
        "original_success_count", "recovered_count", "harmful_count",
        "abstained_count", "recovery_rate", "harm_rate",         "abstention_rate", "seed_count", "seeds", "task_ids", "run_ids",
    ]
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for fault_type, baselines in result.get("groups", {}).items():
            for baseline_id, metrics in baselines.items():
                writer.writerow({"fault_type": fault_type, "baseline_id": baseline_id, **{key: metrics.get(key) for key in fields[2:]}})
    os.replace(temporary, target)
    return target


def summarize(input_dir: str | os.PathLike[str], output_json: str | os.PathLike[str], output_csv: str | os.PathLike[str] | None = None) -> Path:
    source = _allowed_path(input_dir)
    target = _allowed_path(output_json, output=True)
    if not source.is_dir():
        raise ValueError(f"输入目录不存在或不是目录: {source}")
    grouped: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    trajectory_ids = set()
    skipped: List[str] = []
    for path in sorted(source.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            skipped.append(path.name)
            continue
        for item in _records_from_payload(payload):
            run_id = item.get("run_id")
            if run_id is not None:
                trajectory_ids.add(str(run_id))
            fault_type = _fault_type(item)
            for baseline_id, baseline in _baseline_items(item):
                grouped[fault_type][baseline_id].append(_baseline_metrics(item, baseline))
    groups = {
        fault_type: {
            baseline_id: _aggregate(rows)
            for baseline_id, rows in sorted(baselines.items())
        }
        for fault_type, baselines in sorted(grouped.items())
    }
    baseline_row_count = sum(
        len(rows)
        for baselines in grouped.values()
        for rows in baselines.values()
    )
    experiment_name = "local-flight-extended" if any(
        fault_type in TASK_VARIANTS for fault_type in groups
    ) else "local-flight"
    result = {
        "experiment": experiment_name,
        "trajectory_count": len(trajectory_ids),
        "baseline_row_count": baseline_row_count,
        # Keep count as an alias for the expanded baseline row count for
        # backwards compatibility; new consumers should use explicit fields.
        "count": baseline_row_count,
        "fault_type_count": len(groups),
        "baseline_count": len(BASELINES),
        "groups": groups,
    }
    if skipped:
        result["skipped_files"] = skipped
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, target)
    if output_csv is not None:
        write_csv(result, output_csv)
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成或汇总 local-flight 实验结果")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write-spec", metavar="PATH", help="写入 local-flight matrix JSON")
    modes.add_argument("--write-extended-spec", metavar="PATH", help="写入 local-flight-extended task-cell JSON")
    modes.add_argument(
        "--summarize",
        nargs=2,
        metavar=("INPUT_DIR", "OUTPUT_JSON"),
        help="读取结果目录并按 fault_type/baseline 汇总",
    )
    parser.add_argument("--csv", metavar="OUTPUT_CSV", help="汇总时同时写出 CSV 表格")
    return parser


def main(argv: List[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.write_spec:
            target = write_spec(args.write_spec)
            print(f"已生成 local-flight matrix: {target}")
        elif args.write_extended_spec:
            target = write_extended_spec(args.write_extended_spec)
            print(f"已生成 local-flight-extended cells: {target}")
        else:
            target = summarize(args.summarize[0], args.summarize[1], args.csv)
            print(f"已生成汇总报告: {target}")
            if args.csv:
                print(f"已生成 CSV 表格: {_allowed_path(args.csv, output=True)}")
    except (OSError, ValueError, TypeError) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
