#!/usr/bin/env python3
"""Fail-closed admission audit for RACER v2 canonical derived artifacts.

This is intentionally offline. It reads one JSON payload and never starts
containers, calls models, imports benchmark packages, or reads provider
configuration. A PASS is a narrow main-table admission token, not evidence that
an environment actually executed; therefore provenance anchors, exact canonical
serialization, replay receipts, and public/oracle isolation all fail closed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON_DIR = PROJECT_ROOT / "services" / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))
from environment_contract import CONTRACT_VERSION, expected_clean_replay_contract, paired_identity

CANONICAL_SCHEMA = "racer-v2-results-envelope"
SCHEMA_VERSION = "racer-v2-artifact-admission-v2"
CONTAINERS = ("records", "entries", "results", "rows")
DEDUP_STRATEGY = "complete_paired_identity_plus_baseline_trial_model"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")

TOP_LEVEL_FIELDS = frozenset({"schema_version", "experiment", "count", "records", "deduplication"})
ROW_FIELDS = frozenset({
    "protocol_id", "task_id", "run_id", "source_run_id", "episode_id", "trial_id",
    "model_resource_id", "main_comparison", "legacy", "evaluation_tier", "baseline_registry_version", "oracle_manifest_valid", "seed",
    "environment_contract", "source_manifest_sha256", "replay_provenance",
    "expected_replay_contract", "replay_run_id", "paired_identity",
    "paired_identity_complete", "strict_replay", "counterfactual_supported",
    "replay_valid", "baseline_id", "original_success", "recovered_success",
    "harmful_repair", "abstained", "refund_entity_id", "ledger_witness",
    "ledger_entry_count", "refund_witness_valid", "idempotent_replay",
    "response_loss", "reconciled", "side_effect_attempted", "side_effect",
    "side_effect_status", "diagnosis_top1", "step_exact", "repair_steps",
    "latency_ms", "decision", "diagnosis_confidence",
})
CONTRACT_FIELDS = frozenset({
    "contract_version", "episode_id", "source_run_id", "run_id", "env_seed",
    "initial_state_fingerprint", "fault_schedule_fingerprint", "environment_fingerprint",
})
PROVENANCE_FIELDS = frozenset({"valid", "strict", "source_contract"})
REPLAY_CONTRACT_FIELDS = frozenset({
    "contract_version", "episode_id", "source_run_id", "source_environment_fingerprint",
    "initial_state_fingerprint", "fault_schedule_fingerprint", "replay_run_id",
})
TRUSTED_SAFE_FIELDS = frozenset({
    "fault_schedule_fingerprint", "source_environment_fingerprint",
    "oracle_manifest_valid",
})


def _issue(code: str, severity: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "path": path, "message": message}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _walk(value: Any, path: str = "$") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, nested in value.items():
            child = f"{path}.{key}"
            yield child, str(key), nested
            yield from _walk(nested, child)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk(nested, f"{path}[{index}]")


def _scan_sensitive(value: Any, issues: list[dict[str, str]]) -> None:
    """Detect secrets/truth in the complete payload, including ignored aliases."""
    for path, key, nested in _walk(value):
        normalized = key.lower().replace("-", "_")
        if normalized in TRUSTED_SAFE_FIELDS:
            continue
        if any(token in normalized for token in (
            "authorization", "credential", "secret", "password", "private_key",
            "api_key", "apikey", "access_token", "auth_token", "client_key",
            "connection_string",
        )) or normalized.endswith("_token"):
            issues.append(_issue("G5_SECRET_FIELD_EXPOSED", "ERROR", path, "公开/derived artifact 不得包含密钥、认证或私有连接字段。"))
        if any(token in normalized for token in (
            "fault_truth", "oracle_manifest", "oracle_patch", "ground_truth",
            "gold_patch", "target_patch", "expected_patch", "future_state",
            "future_observation", "fault_schedule",
        )) or normalized.startswith("oracle_"):
            issues.append(_issue("G5_ORACLE_TRUTH_EXPOSED", "ERROR", path, "公开/derived artifact 不得包含 oracle、truth、future 或完整 fault schedule。"))
        if isinstance(nested, str):
            lowered = nested.lower()
            if "bearer " in lowered or "sk-" in lowered or "-----begin " in lowered:
                issues.append(_issue("G5_SECRET_VALUE_PATTERN", "ERROR", path, "检测到疑似密钥、Authorization 或 PEM 值。"))


def _selected_rows(payload: Any, issues: list[dict[str, str]]) -> tuple[list[dict[str, Any]], bool]:
    """Return records for inspection; canonical validity is returned separately."""
    if not isinstance(payload, dict):
        issues.append(_issue("G7_INVALID_ENVELOPE", "ERROR", "$", "主表 artifact 必须是 JSON object envelope。"))
        return [], False
    present = [key for key in CONTAINERS if key in payload]
    schema_matches = payload.get("schema_version") == CANONICAL_SCHEMA
    canonical = schema_matches and present == ["records"] and isinstance(payload.get("records"), list)
    if len(present) > 1:
        issues.append(_issue("G7_MULTIPLE_CONTAINERS", "ERROR", "$", "一个 artifact 不得同时声明 records/entries/results/rows。"))
    if schema_matches and not canonical:
        issues.append(_issue("G7_CANONICAL_RECORDS_REQUIRED", "ERROR", "$", "canonical envelope 必须且只能包含 records:list。"))
    if not schema_matches:
        issues.append(_issue("G7_NONCANONICAL_ENVELOPE", "ERROR", "$.schema_version", "主比较 artifact 必须使用 racer-v2-results-envelope。"))
    raw_rows = payload.get("records") if isinstance(payload.get("records"), list) else []
    if not raw_rows:
        issues.append(_issue("EMPTY_OR_INVALID_ARTIFACT", "ERROR", "$.records", "未找到非空 canonical records。"))
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            issues.append(_issue("G7_NONOBJECT_RECORD", "ERROR", f"$.records[{index}]", "canonical records 的每个元素必须是 object。"))
            continue
        rows.append(row)
    return rows, canonical


def _pair_key(row: dict[str, Any]) -> tuple[str, ...] | None:
    identity = row.get("paired_identity")
    if row.get("paired_identity_complete") is not True or not isinstance(identity, list) or len(identity) != 6:
        return None
    if not all(isinstance(part, str) and part for part in identity):
        return None
    return tuple(identity)


def _baseline(row: dict[str, Any]) -> str | None:
    value = row.get("baseline_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _main_required_fields(row: dict[str, Any], index: int, issues: list[dict[str, str]]) -> bool:
    path = f"$.records[{index}]"
    required = (
        "protocol_id", "task_id", "run_id", "source_run_id", "episode_id", "trial_id",
        "model_resource_id", "main_comparison", "legacy", "evaluation_tier", "baseline_registry_version", "oracle_manifest_valid",
        "environment_contract", "source_manifest_sha256", "paired_identity",
        "paired_identity_complete", "baseline_id", "original_success", "recovered_success",
        "harmful_repair", "abstained", "strict_replay", "counterfactual_supported",
        "replay_valid",
    )
    missing = [field for field in required if field not in row]
    if missing:
        issues.append(_issue("G7_REQUIRED_ROW_FIELD_MISSING", "ERROR", path, f"主比较 row 缺少: {', '.join(missing)}。"))
        return False
    if not all(_text(row.get(field)) for field in ("protocol_id", "task_id", "run_id", "source_run_id", "episode_id", "model_resource_id")):
        issues.append(_issue("G2_INCOMPLETE_COMPARISON_KEY", "ERROR", path, "主比较 row 的 protocol/task/run/source/episode/model 不能为空。"))
    if not isinstance(row.get("trial_id"), int) or isinstance(row.get("trial_id"), bool):
        issues.append(_issue("G2_INVALID_TRIAL_ID", "ERROR", path, "trial_id 必须是整数。"))
    if not _baseline(row):
        issues.append(_issue("G7_BASELINE_ID_MISSING", "ERROR", path, "主比较 row 的 baseline_id 必须是非空字符串。"))
    if row.get("evaluation_tier") != "main":
        issues.append(_issue("G0_NON_MAIN_EVALUATION_TIER", "ERROR", f"{path}.evaluation_tier", "主比较 row 必须显式标为 evaluation_tier=main。"))
    if not _text(row.get("baseline_registry_version")):
        issues.append(_issue("G0_BASELINE_REGISTRY_MISSING", "ERROR", f"{path}.baseline_registry_version", "主比较 row 必须引用冻结 baseline registry version。"))
    for field in ("main_comparison", "legacy", "oracle_manifest_valid", "original_success", "recovered_success", "harmful_repair", "abstained", "strict_replay", "counterfactual_supported", "replay_valid"):
        if not _is_bool(row.get(field)):
            issues.append(_issue("G7_INVALID_BOOLEAN_FIELD", "ERROR", f"{path}.{field}", "主比较 outcome/provenance 字段必须是 bool。"))
    digest = _text(row.get("source_manifest_sha256"))
    if not HEX_SHA256.fullmatch(digest):
        issues.append(_issue("G1_SOURCE_MANIFEST_ANCHOR_MISSING", "ERROR", f"{path}.source_manifest_sha256", "主比较 row 必须带 64 位 source manifest SHA-256 锚点。"))
    return not missing


def _validate_contract(row: dict[str, Any], index: int, issues: list[dict[str, str]]) -> tuple[str, ...] | None:
    path = f"$.records[{index}]"
    contract = row.get("environment_contract")
    if not isinstance(contract, dict):
        issues.append(_issue("G2_ENVIRONMENT_CONTRACT_MISSING", "ERROR", f"{path}.environment_contract", "主比较 row 必须带完整 environment_contract。"))
        return None
    extra = set(contract) - CONTRACT_FIELDS
    missing = CONTRACT_FIELDS - set(contract)
    if extra or missing:
        issues.append(_issue("G2_INVALID_ENVIRONMENT_CONTRACT_SHAPE", "ERROR", f"{path}.environment_contract", "environment_contract 字段必须恰为 v2 固定契约字段。"))
    if contract.get("contract_version") != CONTRACT_VERSION:
        issues.append(_issue("G2_CONTRACT_VERSION_MISMATCH", "ERROR", f"{path}.environment_contract.contract_version", "environment_contract version 不匹配。"))
    for field in CONTRACT_FIELDS - {"env_seed"}:
        if not _text(contract.get(field)):
            issues.append(_issue("G2_CONTRACT_FIELD_MISSING", "ERROR", f"{path}.environment_contract.{field}", "environment_contract 缺少非空字段。"))
    if contract.get("env_seed") is None or isinstance(contract.get("env_seed"), bool):
        issues.append(_issue("G2_CONTRACT_SEED_INVALID", "ERROR", f"{path}.environment_contract.env_seed", "environment_contract env_seed 缺失或类型无效。"))
    for field in ("run_id", "source_run_id", "episode_id"):
        if row.get(field) != contract.get(field):
            issues.append(_issue("G2_ROW_CONTRACT_IDENTITY_MISMATCH", "ERROR", f"{path}.{field}", f"row.{field} 必须与 environment_contract 一致。"))
    if row.get("seed", row.get("env_seed")) is not None and row.get("seed", row.get("env_seed")) != contract.get("env_seed"):
        issues.append(_issue("G2_ROW_CONTRACT_SEED_MISMATCH", "ERROR", path, "row seed/env_seed 必须与 environment_contract 一致。"))
    expected = paired_identity(row)
    given = _pair_key(row)
    if expected is None or given is None:
        issues.append(_issue("G2_INCOMPLETE_PAIRED_IDENTITY", "ERROR", path, "主比较 row 必须提供完整的 string-only 6 字段 paired_identity。"))
        return None
    if tuple(expected) != given:
        issues.append(_issue("G2_PAIRED_IDENTITY_CONTRACT_MISMATCH", "ERROR", f"{path}.paired_identity", "paired_identity 必须由 task_id 和 environment_contract 重算得到。"))
        return None
    return given


def _validate_replay(row: dict[str, Any], index: int, issues: list[dict[str, str]]) -> None:
    path = f"$.records[{index}]"
    supported = row.get("counterfactual_supported")
    valid = row.get("replay_valid")
    strict = row.get("strict_replay")
    recovered = row.get("recovered_success")
    if _is_bool(supported) and _is_bool(valid) and supported != valid:
        issues.append(_issue("G3_COUNTERFACTUAL_REPLAY_INCONSISTENT", "ERROR", path, "counterfactual_supported 与 replay_valid 必须同时为 true 或 false。"))
    if recovered is True and (supported is not True or valid is not True or strict is not True):
        issues.append(_issue("G3_RECOVERY_WITHOUT_VALID_REPLAY", "ERROR", path, "恢复成功必须同时具有 strict_replay/counterfactual_supported/replay_valid=true。"))
    if supported is True or valid is True or recovered is True:
        provenance = row.get("replay_provenance")
        replay_run_id = _text(row.get("replay_run_id"))
        expected = row.get("expected_replay_contract")
        contract = row.get("environment_contract")
        if not isinstance(provenance, dict) or set(provenance) != PROVENANCE_FIELDS:
            issues.append(_issue("G3_REPLAY_PROVENANCE_MISSING", "ERROR", f"{path}.replay_provenance", "有效 replay claim 必须提供固定 replay_provenance receipt。"))
            return
        if provenance.get("valid") is not True or provenance.get("strict") is not True:
            issues.append(_issue("G3_REPLAY_PROVENANCE_INVALID", "ERROR", f"{path}.replay_provenance", "replay receipt 必须声明 valid=true 且 strict=true。"))
        if provenance.get("source_contract") != contract:
            issues.append(_issue("G3_REPLAY_SOURCE_CONTRACT_MISMATCH", "ERROR", f"{path}.replay_provenance.source_contract", "replay receipt source_contract 必须精确匹配 row environment_contract。"))
        if not replay_run_id or not isinstance(expected, dict):
            issues.append(_issue("G3_EXPECTED_REPLAY_CONTRACT_MISSING", "ERROR", path, "有效 replay claim 必须提供 replay_run_id 与 expected_replay_contract。"))
            return
        wanted = expected_clean_replay_contract(contract, replay_run_id) if isinstance(contract, dict) else {}
        if set(expected) != REPLAY_CONTRACT_FIELDS or expected != wanted:
            issues.append(_issue("G3_EXPECTED_REPLAY_CONTRACT_MISMATCH", "ERROR", f"{path}.expected_replay_contract", "expected_replay_contract 必须由 row environment_contract 和 replay_run_id 重算。"))


def _has_side_effect_claim(row: dict[str, Any]) -> bool:
    return row.get("harmful_repair") is True or row.get("side_effect") in (True, "attempted", "committed", "unknown", "reconciled") or row.get("side_effect_attempted") is True or row.get("response_loss") is True or row.get("side_effect_status") in {"attempted", "committed", "unknown", "reconciled"}


def _validate_side_effect(row: dict[str, Any], index: int, issues: list[dict[str, str]]) -> None:
    if not _has_side_effect_claim(row):
        return
    path = f"$.records[{index}]"
    entity = _text(row.get("refund_entity_id"))
    witness = _text(row.get("ledger_witness"))
    count = row.get("ledger_entry_count")
    if not entity or not witness or not isinstance(count, int) or isinstance(count, bool) or count < 1:
        issues.append(_issue("G4_INCOMPLETE_REFUND_WITNESS", "ERROR", path, "副作用行必须包含实体 ID、ledger witness 与正整数 ledger_entry_count。"))
    if row.get("refund_witness_valid") is not True:
        issues.append(_issue("G4_UNVERIFIED_REFUND_WITNESS", "ERROR", path, "副作用行必须显式标为 refund_witness_valid=true。"))
    if row.get("response_loss") is True and row.get("reconciled") is not True:
        issues.append(_issue("G4_UNRECONCILED_RESPONSE_LOSS", "ERROR", path, "response_loss 后必须对账，不能直接作为安全完成。"))


def _validate_schema(payload: Any, rows: list[dict[str, Any]], canonical: bool, issues: list[dict[str, str]]) -> None:
    if not isinstance(payload, dict):
        return
    extra_top = set(payload) - TOP_LEVEL_FIELDS
    if extra_top:
        issues.append(_issue("G7_UNKNOWN_TOP_LEVEL_FIELD", "ERROR", "$", f"canonical envelope 含未登记顶层字段: {', '.join(sorted(extra_top))}。"))
    if canonical:
        if payload.get("count") != len(payload.get("records", [])):
            issues.append(_issue("G7_RECORD_COUNT_MISMATCH", "ERROR", "$.count", "count 必须等于 records 长度。"))
        dedup = payload.get("deduplication")
        if not isinstance(dedup, dict) or set(dedup) != {"strategy", "dropped_count", "dropped", "legacy_rows_retained"}:
            issues.append(_issue("G7_DEDUPLICATION_PROOF_MISSING", "ERROR", "$.deduplication", "canonical envelope 必须提供完整 deduplication proof。"))
        else:
            if dedup.get("strategy") != DEDUP_STRATEGY or dedup.get("dropped_count") != 0 or dedup.get("dropped") != [] or dedup.get("legacy_rows_retained") != 0:
                issues.append(_issue("G7_DEDUPLICATION_NOT_CLEAN", "ERROR", "$.deduplication", "主表 envelope 不得含 dropped duplicate 或 legacy retained row。"))
    for index, row in enumerate(rows):
        extra = set(row) - ROW_FIELDS
        if extra:
            issues.append(_issue("G7_UNKNOWN_RECORD_FIELD", "ERROR", f"$.records[{index}]", f"canonical row 含未登记字段: {', '.join(sorted(extra))}。"))
        if "baselines" in row:
            issues.append(_issue("G7_NESTED_BASELINES_FORBIDDEN", "ERROR", f"$.records[{index}].baselines", "canonical record 必须是一 baseline 一行的 flat row。"))


def audit_payload(payload: Any) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    _scan_sensitive(payload, issues)
    rows, canonical = _selected_rows(payload, issues)
    _validate_schema(payload, rows, canonical, issues)

    comparable_count = 0
    non_main_count = 0
    seen: dict[tuple[tuple[str, ...], str, int, str], int] = {}
    for index, row in enumerate(rows):
        path = f"$.records[{index}]"
        main = row.get("main_comparison") is True and row.get("legacy") is False
        if not main:
            non_main_count += 1
            issues.append(_issue("G2_NON_MAIN_RECORD", "ERROR", path, "主表 admission 不接受 legacy 或 main_comparison=false record。"))
            continue
        comparable_count += 1
        _main_required_fields(row, index, issues)
        pair = _validate_contract(row, index, issues)
        _validate_replay(row, index, issues)
        _validate_side_effect(row, index, issues)
        baseline = _baseline(row)
        if pair is None or baseline is None or not isinstance(row.get("trial_id"), int) or isinstance(row.get("trial_id"), bool) or not _text(row.get("model_resource_id")):
            continue
        key = (pair, baseline, row["trial_id"], _text(row.get("model_resource_id")))
        if key in seen:
            issues.append(_issue("G7_DUPLICATE_PAIRED_BASELINE", "ERROR", path, f"与 $.records[{seen[key]}] 共享 paired identity + baseline + trial + model。"))
        else:
            seen[key] = index
    if comparable_count == 0:
        issues.append(_issue("G2_NO_MAIN_COMPARISON_ROWS", "ERROR", "$.records", "主表 admission 至少需要一条 main_comparison=true、legacy=false 的 canonical row。"))

    levels = Counter(issue["severity"] for issue in issues)
    verdict = "PASS" if not issues else "NO-GO"
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": verdict,
        "return_code": 0 if verdict == "PASS" else 2,
        "input": {"canonical_envelope": canonical, "row_count": len(rows)},
        "counts": {
            "main_comparison_rows": comparable_count,
            "non_main_or_legacy_rows": non_main_count,
            "errors": levels.get("ERROR", 0),
            "warnings": levels.get("WARNING", 0),
        },
        "checks": {
            "G1_source_manifest_anchor": "PASS" if not any(issue["code"].startswith("G1_") for issue in issues) else "FAIL",
            "G2_paired_identity": "PASS" if not any(issue["code"].startswith("G2_") for issue in issues) else "FAIL",
            "G3_strict_replay": "PASS" if not any(issue["code"].startswith("G3_") for issue in issues) else "FAIL",
            "G4_side_effect_witness": "PASS" if not any(issue["code"].startswith("G4_") for issue in issues) else "FAIL",
            "G5_truth_and_secret_isolation": "PASS" if not any(issue["code"].startswith("G5_") for issue in issues) else "FAIL",
            "G7_canonical_envelope": "PASS" if not any(issue["code"].startswith("G7_") for issue in issues) else "FAIL",
        },
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="审计 RACER v2 canonical derived artifact 的 fail-closed 准入条件")
    parser.add_argument("artifact", type=Path, help="待审计的 JSON envelope")
    parser.add_argument("--output", type=Path, help="写入审计 JSON；默认输出 stdout")
    args = parser.parse_args(argv)
    try:
        with args.artifact.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "verdict": "NO-GO",
            "return_code": 64,
            "input": {"path": str(args.artifact)},
            "issues": [_issue("UNREADABLE_ARTIFACT", "ERROR", "$", str(error))],
        }
    else:
        result = audit_payload(payload)
        result["input"]["path"] = str(args.artifact)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return result["return_code"]


if __name__ == "__main__":
    raise SystemExit(main())
