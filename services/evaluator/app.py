import glob
import json
import os
import sys
from pathlib import Path

_COMMON_DIR = next(
    candidate
    for candidate in (Path(__file__).resolve().parent / "common", Path(__file__).resolve().parents[1] / "common")
    if candidate.is_dir()
)
if str(_COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMON_DIR))
from environment_contract import (
    CONTRACT_VERSION,
    expected_clean_replay_contract,
    paired_identity,
)

ORACLE_DIR = os.environ.get("ORACLE_DIR", "/data/oracle")
CANONICAL_RESULTS_SCHEMA = "racer-v2-results-envelope"


_MISSING = object()


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _number(value, default=None):
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_or_number(value):
    number = _number(value, 0)
    if isinstance(number, float) and number.is_integer():
        return int(number)
    return number


def _decision_value(decision):
    if isinstance(decision, str):
        return decision
    return _mapping(decision).get("decision")


def _diagnosis_top1(diagnosis):
    diagnosis = _mapping(diagnosis)
    candidates = diagnosis.get("candidates")
    if isinstance(candidates, list):
        candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
        if candidates:
            return max(candidates, key=lambda candidate: _number(candidate.get("confidence"), 0))
    if diagnosis.get("cause") is not None:
        return diagnosis
    return {}


def _fault_truth_with_cause_and_step(fault_truth):
    if isinstance(fault_truth, dict):
        nested = fault_truth.get("faults")
        if isinstance(nested, list):
            fault_truth = nested
        else:
            fault_truth = [fault_truth]
    if not isinstance(fault_truth, list):
        return None
    for fault in fault_truth:
        if not isinstance(fault, dict) or fault.get("step_id") is None:
            continue
        # The privileged runner oracle writer stores the injected schedule
        # verbatim, where the cause is the fault "type"; legacy manifests and
        # unit fixtures may spell it "cause" directly.
        cause = fault.get("cause", fault.get("type"))
        if cause is not None:
            normalized = dict(fault)
            normalized["cause"] = cause
            return normalized
    return None


def _step_value(value):
    number = _number(value)
    if number is not None and float(number).is_integer():
        return int(number)
    return value


def _step_exact(root, fault_truth):
    truth = _fault_truth_with_cause_and_step(fault_truth)
    if truth is None:
        return None
    return (
        root.get("cause") == truth.get("cause")
        and _step_value(root.get("step_id")) == _step_value(truth.get("step_id"))
    )


def _repair_step_count(item, decision, counterfactual, trace):
    for source in (item, decision, counterfactual):
        if not isinstance(source, dict) or "repair_steps" not in source:
            continue
        value = source["repair_steps"]
        if isinstance(value, (list, tuple, set, dict)):
            return len(value)
        return _int_or_number(value)

    if isinstance(decision, dict):
        patches = decision.get("patches")
        if isinstance(patches, (list, tuple, set)):
            return len(patches)
        if patches is not None:
            return 1
        if decision.get("patch") is not None:
            return 1

    if isinstance(counterfactual, dict) and counterfactual.get("patched_step_id") is not None:
        return 1

    if isinstance(trace, list):
        return sum(
            1
            for step in trace
            if isinstance(step, dict)
            and (
                step.get("is_repair") is True
                or step.get("repair_step") is True
                or step.get("phase") == "repair"
            )
        )
    return 0


def _latency_in_mapping(mapping):
    if not isinstance(mapping, dict):
        return _MISSING
    for key in (
        "latency_ms",
        "total_latency_ms",
        "elapsed_ms",
        "duration_ms",
        "latency",
        "elapsed",
        "duration",
    ):
        if key in mapping:
            value = _number(mapping[key])
            if value is not None:
                return value
    for container in ("metrics", "timing", "timings", "metadata"):
        value = _latency_in_mapping(mapping.get(container))
        if value is not _MISSING:
            return value
    return _MISSING


def _latency_ms(item, trace, counterfactual):
    value = _latency_in_mapping(item)
    if value is not _MISSING:
        return _int_or_number(value)

    values = []
    if isinstance(trace, list):
        for step in trace:
            step_value = _latency_in_mapping(step)
            if step_value is not _MISSING:
                values.append(step_value)
    if values:
        return _int_or_number(sum(values))

    # Older replay-only trajectories may expose timings only on the replay trace.
    if isinstance(counterfactual, dict):
        replay_trace = counterfactual.get("trace")
        if isinstance(replay_trace, list):
            for step in replay_trace:
                step_value = _latency_in_mapping(step)
                if step_value is not _MISSING:
                    values.append(step_value)
    return _int_or_number(sum(values)) if values else 0


def _evidence_value(sources, key):
    for source in sources:
        if isinstance(source, dict) and key in source:
            return source[key]
    return None


def _oracle_join(item, oracle):
    """Return whether an oracle may supply evaluator-only truth to this v2 row.

    A run_id collision is not a pairing proof. v2 accepts oracle truth only when
    the full trajectory identity and environment contract match exactly.
    """
    if not isinstance(item, dict) or not isinstance(oracle, dict):
        return False
    required = ("run_id", "task_id", "source_run_id", "episode_id")
    if any(item.get(key) in (None, "") or oracle.get(key) in (None, "") for key in required):
        return False
    if any(item.get(key) != oracle.get(key) for key in required):
        return False
    item_seed = item.get("env_seed", item.get("seed"))
    oracle_seed = oracle.get("env_seed", oracle.get("seed"))
    if item_seed is None or oracle_seed is None or item_seed != oracle_seed:
        return False
    item_contract = item.get("environment_contract")
    oracle_contract = oracle.get("environment_contract")
    if not isinstance(item_contract, dict) or not isinstance(oracle_contract, dict):
        return False
    required_contract = (
        "contract_version",
        "episode_id",
        "source_run_id",
        "run_id",
        "env_seed",
        "initial_state_fingerprint",
        "fault_schedule_fingerprint",
        "environment_fingerprint",
    )
    if any(item_contract.get(key) in (None, "") for key in required_contract):
        return False
    if any(oracle_contract.get(key) != item_contract.get(key) for key in required_contract):
        return False
    if item_contract.get("contract_version") != CONTRACT_VERSION:
        return False
    return _fault_truth_with_cause_and_step(oracle.get("fault_truth")) is not None


def _refund_evidence(trace, counterfactual):
    """Collect only public refund/reconciliation evidence from recorded steps."""
    evidence = {}
    fields = (
        "refund_entity_id", "ledger_witness", "ledger_entry_count",
        "refund_witness_valid", "idempotent_replay", "response_loss", "reconciled",
    )
    replay_trace = _mapping(counterfactual).get("trace")
    steps = list(trace) if isinstance(trace, list) else []
    if isinstance(replay_trace, list):
        steps.extend(replay_trace)
    for step in steps:
        result = _mapping(_mapping(step).get("result"))
        for key in fields:
            if key in result:
                evidence[key] = result[key]
    for source in (_mapping(counterfactual.get("evaluation")), _mapping(counterfactual)):
        for key in fields:
            if key in source:
                evidence[key] = source[key]
    return evidence


def _evaluate_metrics(item, decision, counterfactual, baseline_id=None):
    original = _mapping(item.get("original_evaluation") or item.get("original"))
    counterfactual = _mapping(counterfactual)
    cf_evaluation = _mapping(counterfactual.get("evaluation"))
    if not cf_evaluation and "success" in counterfactual:
        cf_evaluation = counterfactual
    diagnosis = item.get("diagnosis", {})
    root = _diagnosis_top1(diagnosis)
    trace = item.get("trace", [])
    if not isinstance(trace, list):
        trace = []

    original_success = (
        item.get("original_success", original.get("success", False))
        if baseline_id is None
        else original.get("success", False)
    )
    recovered_success = (
        item.get("recovered_success", cf_evaluation.get("success", False))
        if baseline_id is None
        else cf_evaluation.get("success", False)
    )
    harmful_repair = (
        item.get(
            "harmful_repair",
            cf_evaluation.get("harmful_repair", cf_evaluation.get("side_effect", False)),
        )
        if baseline_id is None
        else cf_evaluation.get("harmful_repair", cf_evaluation.get("side_effect", False))
    )
    decision_name = _decision_value(decision)
    confidence = _mapping(diagnosis).get("diagnosis_confidence")
    if confidence is None:
        confidence = root.get("confidence")

    seed = item.get("seed", item.get("env_seed"))
    if seed is None:
        seed = original.get("seed", original.get("env_seed"))
    if seed is None:
        for step in trace:
            observation = _mapping(step).get("observation", {})
            if "seed" in observation or "env_seed" in observation:
                seed = observation.get("seed", observation.get("env_seed"))
                break

    source_run_id = item.get("source_run_id", item.get("run_id"))
    episode_id = item.get("episode_id", source_run_id)
    environment = _mapping(item.get("environment_contract"))
    identity = paired_identity(item, baseline_id=baseline_id)
    refund_evidence = _refund_evidence(trace, counterfactual)
    evidence_sources = (refund_evidence, cf_evaluation, counterfactual, _mapping(decision), item)
    strict_replay = _evidence_value(evidence_sources, "strict_replay")
    if strict_replay is None:
        strict_replay = _mapping(counterfactual.get("replay_provenance")).get("strict")
    metrics = {
        "protocol_id": item.get("protocol_id"),
        "task_id": item.get("task_id"),
        "run_id": item.get("run_id"),
        "source_run_id": source_run_id,
        "episode_id": episode_id,
        "trial_id": item.get("trial_id"),
        "model_resource_id": item.get("model_resource_id"),
        "main_comparison": item.get("main_comparison", True),
        "legacy": item.get("legacy", False),
        "evaluation_tier": item.get("evaluation_tier", "unregistered"),
        "baseline_registry_version": item.get("baseline_registry_version"),
        "oracle_manifest_valid": item.get("oracle_manifest_valid"),
        "seed": seed,
        "environment_contract": environment or None,
        "source_manifest_sha256": item.get("source_manifest_sha256"),
        "replay_provenance": _mapping(counterfactual.get("replay_provenance")) or None,
        "expected_replay_contract": expected_clean_replay_contract(
            environment, counterfactual.get("run_id", counterfactual.get("replay_run_id"))
        ) if environment and counterfactual.get("run_id", counterfactual.get("replay_run_id")) else None,
        "replay_run_id": counterfactual.get("run_id", counterfactual.get("replay_run_id")),
        "paired_identity": list(identity) if identity is not None else None,
        "paired_identity_complete": identity is not None,
        "strict_replay": strict_replay,
        "counterfactual_supported": _evidence_value(evidence_sources, "counterfactual_supported"),
        "replay_valid": _evidence_value(evidence_sources, "replay_valid"),
        "refund_entity_id": _evidence_value(evidence_sources, "refund_entity_id"),
        "ledger_witness": _evidence_value(evidence_sources, "ledger_witness"),
        "ledger_entry_count": _evidence_value(evidence_sources, "ledger_entry_count"),
        "refund_witness_valid": _evidence_value(evidence_sources, "refund_witness_valid"),
        "idempotent_replay": _evidence_value(evidence_sources, "idempotent_replay"),
        "response_loss": _evidence_value(evidence_sources, "response_loss"),
        "reconciled": _evidence_value(evidence_sources, "reconciled"),
        "abstained": bool(item.get("abstained", str(decision_name).lower() == "abstain")),
        "diagnosis_top1": root.get("cause"),
        "step_exact": _step_exact(root, item.get("fault_truth")),
        "repair_steps": _repair_step_count(item, _mapping(decision), counterfactual, trace),
        "latency_ms": _latency_ms(item, trace, counterfactual),
        "decision": decision_name,
        "diagnosis_confidence": confidence,
        "original_success": bool(original_success),
        "recovered_success": bool(recovered_success),
        "harmful_repair": bool(harmful_repair),
    }
    if baseline_id is not None:
        metrics["baseline_id"] = baseline_id
    return metrics


def evaluate_file(path, oracle_path=None):
    with open(path, encoding="utf-8") as file:
        item = _mapping(json.load(file))
    item = dict(item)
    item["oracle_manifest_valid"] = None
    if oracle_path:
        item["oracle_manifest_valid"] = False
        # Truth embedded in a public trajectory cannot substitute for evaluator
        # oracle evidence when an oracle manifest is expected.
        item.pop("fault_truth", None)
        try:
            with open(oracle_path, encoding="utf-8") as file:
                oracle = _mapping(json.load(file))
        except (OSError, json.JSONDecodeError):
            oracle = {}
        if _oracle_join(item, oracle):
            item["fault_truth"] = oracle["fault_truth"]
            item["oracle_manifest_valid"] = True
    decision = item.get("decision", {})
    counterfactual = item.get("counterfactual") or item.get("recovered")
    row = _evaluate_metrics(item, decision, counterfactual)

    baseline_rows = {}
    baselines = item.get("baselines")
    if isinstance(baselines, dict):
        for baseline_id, value in baselines.items():
            if not isinstance(baseline_id, str):
                continue
            value = _mapping(value)
            baseline_decision = value.get("decision", {})
            baseline_counterfactual = value.get("counterfactual")
            baseline_rows[baseline_id] = _evaluate_metrics(
                item, baseline_decision, baseline_counterfactual, baseline_id
            )
    row["baselines"] = baseline_rows
    return row


def derived_rows_from_trajectory(item, oracle_path=None):
    """Expand one trajectory into one canonical derived row per baseline.

    The legacy top-level row is used only when no baseline map exists. This
    prevents a multi-baseline trajectory from being admitted as one ambiguous
    comparison record.
    """
    row = evaluate_file(item, oracle_path=oracle_path) if isinstance(item, (str, os.PathLike)) else _mapping(item)
    baselines = _mapping(row.get("baselines"))
    if not baselines:
        single = dict(row)
        single.pop("baselines", None)
        return [single]
    derived = []
    for baseline_id, baseline in baselines.items():
        if not isinstance(baseline, dict):
            continue
        flattened = dict(row)
        flattened.pop("baselines", None)
        flattened.update(baseline)
        flattened["baseline_id"] = baseline_id
        derived.append(flattened)
    return derived


def _rate(numerator, denominator):
    return numerator / denominator if denominator else 0


def _input_rows(payload):
    """Normalize input once; reject ambiguous multi-container envelopes."""
    if isinstance(payload, dict):
        present = [key for key in ("records", "entries", "results", "rows") if key in payload]
        list_containers = [key for key in present if isinstance(payload.get(key), list)]
        if len(present) > 1:
            raise ValueError("ambiguous_results_containers")
        if len(list_containers) == 1:
            return payload[list_containers[0]], list_containers[0]
        if present:
            raise ValueError("invalid_results_container")
        return [payload], None
    if isinstance(payload, list):
        return payload, "list"
    raise ValueError("invalid_results_payload")


def canonical_results_envelope(payload, *, experiment=None):
    """Serialize v2 rows once, accepting legacy rows/results/records/entries input.

    Deduplication is deliberately limited to complete paired identities plus
    baseline, trial, and model-resource identifiers. Rows missing any of those
    comparison keys are retained because guessing cross-trial equivalence is unsafe.
    """
    raw_rows, _container = _input_rows(payload)
    rows = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        baselines = _mapping(row.get("baselines"))
        if baselines:
            for baseline_id, baseline in baselines.items():
                if not isinstance(baseline, dict):
                    continue
                flattened = dict(row)
                flattened.pop("baselines", None)
                flattened.update(baseline)
                flattened["baseline_id"] = baseline_id
                rows.append(flattened)
        else:
            rows.append(row)
    deduplicated = []
    seen = set()
    duplicates = []
    for row in rows:
        identity = row.get("paired_identity")
        baseline = row.get("baseline_id")
        trial_id = row.get("trial_id")
        model_resource_id = row.get("model_resource_id")
        complete_comparison_key = (
            isinstance(identity, list)
            and len(identity) == 6
            and row.get("paired_identity_complete") is True
            and isinstance(baseline, str)
            and bool(baseline.strip())
            and trial_id is not None
            and model_resource_id is not None
        )
        if complete_comparison_key:
            key = (
                tuple(str(part) for part in identity),
                baseline.strip(),
                str(trial_id),
                str(model_resource_id),
            )
            if key in seen:
                duplicates.append({
                    "paired_identity": identity,
                    "baseline_id": baseline,
                    "trial_id": trial_id,
                    "model_resource_id": model_resource_id,
                })
                continue
            seen.add(key)
        deduplicated.append(row)
    return {
        "schema_version": CANONICAL_RESULTS_SCHEMA,
        "experiment": experiment,
        "count": len(deduplicated),
        "records": deduplicated,
        "deduplication": {
            "strategy": "complete_paired_identity_plus_baseline_trial_model",
            "dropped_count": len(duplicates),
            "dropped": duplicates,
            "legacy_rows_retained": sum(
                row.get("paired_identity_complete") is not True
                or row.get("trial_id") is None
                or row.get("model_resource_id") is None
                for row in deduplicated
            ),
        },
    }


def _summary(rows):
    failure_count = sum(not row["original_success"] for row in rows)
    recovered_count = sum(row["recovered_success"] for row in rows if not row["original_success"])
    harmful_count = sum(row["harmful_repair"] for row in rows if not row["original_success"])
    abstained_count = sum(row["abstained"] for row in rows)
    return {
        "failure_count": failure_count,
        "recovery_rate": _rate(recovered_count, failure_count),
        "harm_rate": _rate(harmful_count, failure_count),
        "abstention_rate": _rate(abstained_count, len(rows)),
    }


def summarize_baselines(rows):
    grouped = {}
    for row in rows:
        for baseline_id, baseline_row in _mapping(row.get("baselines")).items():
            grouped.setdefault(baseline_id, []).append(baseline_row)
    return {baseline_id: _summary(baseline_rows) for baseline_id, baseline_rows in grouped.items()}


if __name__ == "__main__":
    paths = glob.glob("/data/trajectories/*.json")
    rows = []
    for path in paths:
        oracle_path = str(Path(ORACLE_DIR) / Path(path).name)
        rows.append(evaluate_file(path, oracle_path=oracle_path))
    summary = _summary(rows)
    summary["baselines"] = summarize_baselines(rows)
    print(json.dumps({"count": len(rows), "rows": rows, "summary": summary}, ensure_ascii=False, indent=2))
