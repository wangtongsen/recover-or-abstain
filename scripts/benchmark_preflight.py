#!/usr/bin/env python3
"""Build and audit RACER v2 planned benchmark manifests without execution.

The tool intentionally reads only local JSON manifests and the frozen protocol
text. It does not start containers, call models, import benchmark packages, or
read provider configuration. A planned manifest is not execution evidence:
missing model registry, five-trial coverage, provenance, or executed artifacts
returns NO-GO by design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


PROTOCOL_ID = "racer-v2-benchmark-protocol-0.1"
SCHEMA_VERSION = "racer-v2-benchmark-preflight-v1"
REQUIRED_TRIAL_IDS = tuple(range(5))
REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "protocol_id",
    "matrices",
    "planned_cells",
    "model_registry",
    "executed_artifacts",
    "blockers",
    "verdict",
)


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used for manifest hashes."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _issue(code: str, severity: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "path": path, "message": message}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _matrix_record(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"matrix 不是 JSON object: {path}")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not all(isinstance(task, dict) for task in tasks):
        raise ValueError(f"matrix 缺少 tasks object list: {path}")
    experiment = _text(payload.get("experiment"))
    if not experiment:
        raise ValueError(f"matrix 缺少 experiment: {path}")
    record = {
        "matrix_id": experiment,
        "matrix_version": payload.get("version"),
        "path": str(path),
        "sha256": sha256_value(payload),
        "task_count": len(tasks),
        "baselines": list(payload.get("baselines", [])) if isinstance(payload.get("baselines"), list) else [],
        "seeds": list(payload.get("seeds", [])) if isinstance(payload.get("seeds"), list) else [],
    }
    return record, tasks


def build_manifest(
    matrix_paths: Iterable[Path],
    *,
    protocol_path: Path | None = None,
    model_registry: list[dict[str, Any]] | None = None,
    executed_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a planned-only manifest from frozen matrix JSON files.

    Every source task expands into baseline × trial planned cells. The result
    intentionally leaves model_registry and executed_artifacts empty unless
    supplied by a separate, non-secret registry/provenance workflow.
    """
    matrices: list[dict[str, Any]] = []
    planned_cells: list[dict[str, Any]] = []
    registered_model_ids = [
        _text(model.get("model_resource_id"))
        for model in (model_registry or [])
        if isinstance(model, dict) and _text(model.get("model_resource_id"))
    ]
    # Until a non-secret model registry is supplied, retain an explicitly
    # unbound planned cell instead of guessing a resource from provider config.
    # Auditing then fails closed on G0_MODEL_REGISTRY_MISSING.
    planned_model_ids: list[str | None] = registered_model_ids or [None]
    for matrix_path in matrix_paths:
        record, tasks = _matrix_record(matrix_path)
        matrices.append(record)
        matrix_id = record["matrix_id"]
        matrix_baselines = record["baselines"]
        for task_index, task in enumerate(tasks):
            task_id = _text(task.get("task_id"))
            episode_id = _text(task.get("episode_id"))
            run_id = _text(task.get("run_id"))
            if not task_id or not episode_id or not run_id:
                raise ValueError(f"matrix task 缺少 task_id/episode_id/run_id: {matrix_path} tasks[{task_index}]")
            baselines = task.get("baselines") if isinstance(task.get("baselines"), list) else matrix_baselines
            for baseline_id in baselines:
                baseline_text = _text(baseline_id)
                if not baseline_text:
                    raise ValueError(f"matrix task 包含空 baseline: {matrix_path} tasks[{task_index}]")
                for trial_id in REQUIRED_TRIAL_IDS:
                    for model_resource_id in planned_model_ids:
                        planned_cells.append({
                            "matrix_id": matrix_id,
                            "task_id": task_id,
                            "episode_id": episode_id,
                            "source_run_id": run_id,
                            "env_seed": task.get("seed"),
                        "baseline_id": baseline_text,
                        "trial_id": trial_id,
                        "model_resource_id": model_resource_id,
                        "evaluation_tier": task.get("evaluation_tier", "unregistered"),
                        "baseline_registry_version": task.get("baseline_registry_version"),
                        "main_comparison": task.get("main_comparison", True),
                        "strict_replay": task.get("strict_replay") is True,
                        "status": "planned",
                        })
    protocol = {
        "protocol_id": PROTOCOL_ID,
        "path": str(protocol_path) if protocol_path is not None else None,
        "sha256": sha256_value(protocol_path.read_text(encoding="utf-8")) if protocol_path is not None else None,
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "protocol": protocol,
        "matrices": matrices,
        "required_trial_ids": list(REQUIRED_TRIAL_IDS),
        "planned_cells": planned_cells,
        "model_registry": model_registry if model_registry is not None else [],
        "executed_artifacts": executed_artifacts if executed_artifacts is not None else [],
        "blockers": [],
        "verdict": "NO-GO",
    }
    preview = audit_manifest(result)
    result["blockers"] = preview["blockers"]
    result["verdict"] = preview["verdict"]
    result["manifest_sha256"] = sha256_value({key: value for key, value in result.items() if key != "manifest_sha256"})
    return result


def _check_protocol(manifest: dict[str, Any], issues: list[dict[str, str]]) -> None:
    if manifest.get("protocol_id") != PROTOCOL_ID:
        issues.append(_issue("PREFLIGHT_PROTOCOL_ID_MISMATCH", "ERROR", "$.protocol_id", f"必须为 {PROTOCOL_ID}。"))
    protocol = manifest.get("protocol")
    if not isinstance(protocol, dict) or not _text(protocol.get("sha256")):
        issues.append(_issue("G0_PROTOCOL_HASH_MISSING", "ERROR", "$.protocol", "预检清单必须记录冻结 protocol 的 SHA-256。"))


def _check_matrices(manifest: dict[str, Any], issues: list[dict[str, str]]) -> None:
    matrices = manifest.get("matrices")
    if not isinstance(matrices, list) or not matrices:
        issues.append(_issue("G0_MATRIX_MANIFEST_MISSING", "ERROR", "$.matrices", "必须至少登记一个冻结 matrix manifest。"))
        return
    seen: set[str] = set()
    for index, matrix in enumerate(matrices):
        path = f"$.matrices[{index}]"
        if not isinstance(matrix, dict):
            issues.append(_issue("G0_INVALID_MATRIX_RECORD", "ERROR", path, "matrix record 必须是 object。"))
            continue
        matrix_id = _text(matrix.get("matrix_id"))
        if not matrix_id or not _text(matrix.get("sha256")) or not _text(matrix.get("path")):
            issues.append(_issue("G0_INCOMPLETE_MATRIX_RECORD", "ERROR", path, "matrix record 必须包含 matrix_id、path 和 sha256。"))
        if matrix_id in seen:
            issues.append(_issue("G0_DUPLICATE_MATRIX_ID", "ERROR", path, "matrix_id 不得重复。"))
        seen.add(matrix_id)


def _cell_key(cell: dict[str, Any]) -> tuple[str, str, str, int, str] | None:
    values = (
        _text(cell.get("matrix_id")),
        _text(cell.get("task_id")),
        _text(cell.get("baseline_id")),
        cell.get("trial_id"),
        _text(cell.get("model_resource_id")),
    )
    if not all((values[0], values[1], values[2])) or not isinstance(values[3], int) or isinstance(values[3], bool):
        return None
    return values


def _check_planned_cells(manifest: dict[str, Any], issues: list[dict[str, str]]) -> int:
    cells = manifest.get("planned_cells")
    if not isinstance(cells, list) or not cells:
        issues.append(_issue("PREFLIGHT_PLANNED_CELLS_MISSING", "ERROR", "$.planned_cells", "必须存在至少一个 planned cell。"))
        return 0
    expected_trials = manifest.get("required_trial_ids", list(REQUIRED_TRIAL_IDS))
    if expected_trials != list(REQUIRED_TRIAL_IDS):
        issues.append(_issue("PREFLIGHT_TRIAL_POLICY_MISMATCH", "ERROR", "$.required_trial_ids", "主会预检必须要求 trial_id=0..4。"))
    grouped: dict[tuple[str, str, str, str], set[int]] = {}
    seen: set[tuple[str, str, str, int, str]] = set()
    registered_model_ids = {
        _text(model.get("model_resource_id"))
        for model in manifest.get("model_registry", [])
        if isinstance(model, dict) and _text(model.get("model_resource_id"))
    }
    for index, cell in enumerate(cells):
        path = f"$.planned_cells[{index}]"
        if not isinstance(cell, dict):
            issues.append(_issue("PREFLIGHT_INVALID_CELL", "ERROR", path, "planned cell 必须是 object。"))
            continue
        key = _cell_key(cell)
        if key is None:
            issues.append(_issue("PREFLIGHT_INCOMPLETE_CELL_IDENTITY", "ERROR", path, "planned cell 必须包含 matrix/task/baseline/trial identity。"))
            continue
        matrix_id, task_id, baseline_id, trial_id, model_resource_id = key
        if not _text(cell.get("episode_id")) or not _text(cell.get("source_run_id")):
            issues.append(_issue("G2_PLANNED_PAIRED_PROVENANCE_MISSING", "ERROR", path, "planned cell 缺少 episode_id 或 source_run_id。"))
        if registered_model_ids and not model_resource_id:
            issues.append(_issue("G0_PLANNED_MODEL_RESOURCE_MISSING", "ERROR", path, "model registry 已存在时，每个 planned cell 必须绑定 model_resource_id。"))
        elif registered_model_ids and model_resource_id not in registered_model_ids:
            issues.append(_issue("G0_PLANNED_MODEL_NOT_REGISTERED", "ERROR", path, "planned cell 的 model_resource_id 不在 model registry 中。"))
        if cell.get("strict_replay") is not True:
            issues.append(_issue("G3_PLANNED_NONSTRICT_REPLAY", "ERROR", path, "主比较 planned cell 必须预置 strict_replay=true。"))
        tier = cell.get("evaluation_tier")
        if tier not in {"pilot", "main"}:
            issues.append(_issue("G0_INVALID_EVALUATION_TIER", "ERROR", path, "planned cell 必须显式标为 pilot 或 main。"))
        if tier == "main":
            if cell.get("main_comparison") is not True:
                issues.append(_issue("G0_MAIN_CELL_NOT_COMPARABLE", "ERROR", path, "main tier planned cell 必须 main_comparison=true。"))
            if not _text(cell.get("baseline_registry_version")):
                issues.append(_issue("G0_MAIN_BASELINE_REGISTRY_MISSING", "ERROR", path, "main tier planned cell 必须引用 baseline registry version。"))
        elif cell.get("main_comparison") is not False:
            issues.append(_issue("G0_PILOT_CELL_MARKED_MAIN", "ERROR", path, "pilot tier planned cell 必须 main_comparison=false。"))
        if cell.get("status") != "planned":
            issues.append(_issue("PREFLIGHT_NONPLANNED_CELL", "ERROR", path, "预检 manifest 只能登记 status=planned 的 cell。"))
        if key in seen:
            issues.append(_issue("PREFLIGHT_DUPLICATE_PLANNED_CELL", "ERROR", path, "planned cell identity 重复。"))
        seen.add(key)
        grouped.setdefault((matrix_id, task_id, baseline_id, model_resource_id), set()).add(trial_id)
    for group, trials in sorted(grouped.items()):
        if trials != set(REQUIRED_TRIAL_IDS):
            issues.append(_issue("PREFLIGHT_INCOMPLETE_TRIAL_COVERAGE", "ERROR", "$.planned_cells", f"{group} 缺少主会要求的 5 个 trial。"))
    return len(cells)


def _check_model_registry(manifest: dict[str, Any], issues: list[dict[str, str]]) -> int:
    registry = manifest.get("model_registry")
    if not isinstance(registry, list) or not registry:
        issues.append(_issue("G0_MODEL_REGISTRY_MISSING", "ERROR", "$.model_registry", "尚未登记无密钥的 model_resource registry。"))
        return 0
    seen: set[str] = set()
    for index, model in enumerate(registry):
        path = f"$.model_registry[{index}]"
        if not isinstance(model, dict):
            issues.append(_issue("G0_INVALID_MODEL_RECORD", "ERROR", path, "model registry record 必须是 object。"))
            continue
        resource_id = _text(model.get("model_resource_id"))
        missing = [field for field in ("model_resource_id", "provider", "model_name", "model_version", "credential_source") if not _text(model.get(field))]
        if missing:
            issues.append(_issue("G0_INCOMPLETE_MODEL_RECORD", "ERROR", path, f"model registry 缺少: {', '.join(missing)}。"))
        if resource_id in seen:
            issues.append(_issue("G0_DUPLICATE_MODEL_RESOURCE", "ERROR", path, "model_resource_id 不得重复。"))
        seen.add(resource_id)
        for key in model:
            normalized = str(key).lower()
            if normalized in {"api_key", "authorization", "token", "auth_token", "secret", "password", "model_json"} or normalized.endswith("_token"):
                issues.append(_issue("G5_SECRET_IN_MODEL_REGISTRY", "ERROR", f"{path}.{key}", "model registry 不得携带凭据值。"))
    return len(registry)


def _check_executed_artifacts(manifest: dict[str, Any], issues: list[dict[str, str]]) -> int:
    artifacts = manifest.get("executed_artifacts")
    if not isinstance(artifacts, list):
        issues.append(_issue("G1_INVALID_EXECUTED_ARTIFACTS", "ERROR", "$.executed_artifacts", "executed_artifacts 必须是 list。"))
        return 0
    if not artifacts:
        issues.append(_issue("G8_EXECUTED_ARTIFACTS_MISSING", "ERROR", "$.executed_artifacts", "尚无 executed v2 artifact；预检必须保持 NO-GO。"))
        return 0

    planned = manifest.get("planned_cells")
    expected_keys = {
        key for cell in planned if isinstance(cell, dict)
        if (key := _cell_key(cell)) is not None and key[-1]
    } if isinstance(planned, list) else set()
    seen: set[tuple[str, str, str, int, str]] = set()
    for index, artifact in enumerate(artifacts):
        path = f"$.executed_artifacts[{index}]"
        if not isinstance(artifact, dict):
            issues.append(_issue("G1_INVALID_EXECUTED_ARTIFACT", "ERROR", path, "executed artifact record 必须是 object。"))
            continue
        key = _cell_key(artifact)
        if key is None or not key[-1]:
            issues.append(_issue("G1_INCOMPLETE_EXECUTED_IDENTITY", "ERROR", path, "executed artifact 必须包含 matrix/task/baseline/trial/model identity。"))
            continue
        if not _text(artifact.get("run_id")) or not _text(artifact.get("artifact_sha256")):
            issues.append(_issue("G1_INCOMPLETE_EXECUTED_PROVENANCE", "ERROR", path, "executed artifact 必须包含 run_id 与 artifact_sha256。"))
        if key not in expected_keys:
            issues.append(_issue("G8_UNPLANNED_EXECUTED_ARTIFACT", "ERROR", path, "executed artifact 不在冻结 planned cell 集合中。"))
        if key in seen:
            issues.append(_issue("G8_DUPLICATE_EXECUTED_ARTIFACT", "ERROR", path, "同一 planned cell 有多个 executed artifact。"))
        seen.add(key)
    if expected_keys and seen != expected_keys:
        missing_count = len(expected_keys - seen)
        if missing_count:
            issues.append(_issue("G8_EXECUTED_COVERAGE_INCOMPLETE", "ERROR", "$.executed_artifacts", f"缺少 {missing_count} 个冻结 planned cell 的 executed artifact。"))
    return len(artifacts)


def audit_manifest(manifest: Any) -> dict[str, Any]:
    """Return a machine-readable PASS/NO-GO preflight decision."""
    issues: list[dict[str, str]] = []
    if not isinstance(manifest, dict):
        issues.append(_issue("PREFLIGHT_INVALID_MANIFEST", "ERROR", "$", "preflight manifest 必须是 JSON object。"))
        manifest = {}
    missing_fields = [field for field in REQUIRED_MANIFEST_FIELDS if field not in manifest]
    for field in missing_fields:
        issues.append(_issue("PREFLIGHT_REQUIRED_FIELD_MISSING", "ERROR", f"$.{field}", "缺少 required preflight field。"))
    _check_protocol(manifest, issues)
    _check_matrices(manifest, issues)
    planned_cell_count = _check_planned_cells(manifest, issues)
    model_count = _check_model_registry(manifest, issues)
    executed_count = _check_executed_artifacts(manifest, issues)
    levels = Counter(issue["severity"] for issue in issues)
    verdict = "PASS" if not issues else "NO-GO"
    blockers = sorted({issue["code"] for issue in issues if issue["severity"] == "ERROR"})
    return {
        "schema_version": "racer-v2-preflight-audit-v1",
        "verdict": verdict,
        "return_code": 0 if verdict == "PASS" else 2,
        "input": {
            "protocol_id": manifest.get("protocol_id"),
            "manifest_sha256": manifest.get("manifest_sha256"),
        },
        "counts": {
            "planned_cells": planned_cell_count,
            "model_resources": model_count,
            "executed_artifacts": executed_count,
            "errors": levels.get("ERROR", 0),
            "warnings": levels.get("WARNING", 0),
        },
        "checks": {
            "G0_protocol_matrix_model_lock": "PASS" if not any(issue["code"].startswith("G0_") or issue["code"].startswith("PREFLIGHT_PROTOCOL") for issue in issues) else "FAIL",
            "G1_executed_provenance": "PASS" if not any(issue["code"].startswith("G1_") for issue in issues) else "FAIL",
            "G2_G3_planned_identity_and_replay": "PASS" if not any(issue["code"].startswith(("G2_", "G3_")) for issue in issues) else "FAIL",
            "G5_secret_isolation": "PASS" if not any(issue["code"].startswith("G5_") for issue in issues) else "FAIL",
            "G8_executed_evidence": "PASS" if not any(issue["code"].startswith("G8_") for issue in issues) else "FAIL",
        },
        "blockers": blockers,
        "issues": issues,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成或审计 RACER v2 benchmark preflight manifest（仅离线）")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--build", nargs="+", type=Path, metavar="MATRIX", help="从 matrix JSON 生成 planned-only manifest")
    modes.add_argument("--audit", type=Path, metavar="MANIFEST", help="审计已有 preflight manifest")
    parser.add_argument("--protocol", type=Path, help="冻结 protocol Markdown（--build 时必须提供）")
    parser.add_argument("--output", type=Path, help="输出 JSON 文件；省略时输出 stdout")
    return parser


def _write_result(result: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.build:
            if args.protocol is None:
                raise ValueError("--build 必须同时提供 --protocol")
            manifest = build_manifest(args.build, protocol_path=args.protocol)
            result = manifest
            return_code = 0
        else:
            result = audit_manifest(_read_json(args.audit))
            return_code = result["return_code"]
        _write_result(result, args.output)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        result = {
            "schema_version": "racer-v2-preflight-audit-v1",
            "verdict": "NO-GO",
            "return_code": 64,
            "issues": [_issue("PREFLIGHT_INVALID_INPUT", "ERROR", "$", str(error))],
        }
        _write_result(result, args.output)
        return 64
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
