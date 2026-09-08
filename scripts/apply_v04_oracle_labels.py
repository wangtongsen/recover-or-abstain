#!/usr/bin/env python3
"""协议 v0.4：独立 oracle 重标注（对冻结轨迹，不重执行）。

读取冻结的执行证据（v0.1 主表 55 轨迹 + v0.3 E3 10 轨迹），对每条
baseline 用 services/common/harm_oracle.py 的独立真值 oracle 复算
harm 标签，产出 harm-oracle-annotation.json：

- 真值绑定：spec env_config -> initial_state_fingerprint 重算核对；
- 哈希链：cf trace / direct-apply step 逐哈希验证；
- oracle 判定：三证据形态 + veto 预测路径；
- 一致性：oracle 标签 vs 旧标签（env evaluate）逐行 diff；
- veto_accuracy：racer/racer_no_abstain 的否决触发 vs oracle 预测。

重执行语义为零：只读轨迹与 spec，不触碰任何环境或模型。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "common"))

from environment_contract import fingerprint as contract_fingerprint  # noqa: E402
from harm_oracle import (  # noqa: E402
    ORACLE_LABEL_VERSION,
    label_baseline,
    truth_binding_fingerprint,
    truth_from_env_config,
    verify_initial_state,
)

ANNOTATION_SCHEMA = "racer-v2-harm-oracle-annotation-v1"


def _load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _spec_runs(spec_path: Path):
    spec = _load(spec_path)
    if isinstance(spec, list):
        return {run.get("run_id"): run for run in spec}
    tasks = spec.get("tasks")
    if isinstance(tasks, list):
        return {run.get("run_id"): run for run in tasks}
    raise ValueError(f"unsupported spec shape: {spec_path}")


def _label_run(trajectory: dict, spec_run: dict) -> dict:
    run_id = trajectory.get("run_id")
    env_config = spec_run.get("env_config") or {}
    truth = truth_from_env_config(env_config)
    # 真值绑定：重算 initial_state_fingerprint 并核对轨迹契约。
    initial = dict(env_config)
    initial.pop("faults", None)
    expected_fp = contract_fingerprint({"seed": spec_run.get("seed"), "environment": initial})
    contract = trajectory.get("environment_contract") or {}
    binding_ok = expected_fp == contract.get("initial_state_fingerprint")
    # 源末态：主 trace 末步（veto 行为终局 / source-only 终局）。
    trace = trajectory.get("trace") or []
    source_final = (trace[-1].get("observation") or {}).get("state") if trace else None
    source_chain = None
    if trace:
        from harm_oracle import verify_trace_state_chain

        source_chain = verify_trace_state_chain(trace)
    source_initial = verify_initial_state(trace, truth)
    baselines_out = {}
    agreement = {"agree": 0, "disagree": 0, "details": []}
    veto_audit = []
    for baseline_id, baseline in (trajectory.get("baselines") or {}).items():
        if not isinstance(baseline, dict):
            continue
        label = label_baseline(baseline, truth, source_final)
        old_harm = None
        decision = baseline.get("decision") or {}
        cf_eval = (baseline.get("counterfactual") or {}).get("evaluation") or {}
        if decision.get("direct_applied") is True:
            dar = decision.get("direct_apply_result") or {}
            old_harm = bool((dar.get("evaluation") or {}).get("side_effect", False))
        elif decision.get("replay_veto") is True:
            old_harm = False
        elif cf_eval:
            old_harm = bool(cf_eval.get("side_effect", False))
        else:
            old_harm = False
        if label.get("oracle_harm") is None:
            entry = {
                "baseline_id": baseline_id,
                "oracle_harm": None,
                "old_harm": old_harm,
                "status": "unlabeled",
                "evidence_error": label.get("evidence_error"),
            }
            baselines_out[baseline_id] = entry
            continue
        agree = label["oracle_harm"] == old_harm
        agreement["agree" if agree else "disagree"] += 1
        if not agree:
            agreement["details"].append({
                "baseline_id": baseline_id,
                "old_harm": old_harm,
                "oracle_harm": label["oracle_harm"],
                "evidence_form": label["evidence_form"],
            })
        entry = {
            "baseline_id": baseline_id,
            "evidence_form": label["evidence_form"],
            "oracle_harm": label["oracle_harm"],
            "oracle_success": label["oracle_success"],
            "old_harm": old_harm,
            "agree_with_old_label": agree,
            "chain_verification": label.get("chain_verification"),
        }
        if label.get("veto_prediction_harm") is not None:
            entry["veto_prediction_harm"] = label["veto_prediction_harm"]
        baselines_out[baseline_id] = entry
        if decision.get("replay_veto") is True:
            veto_audit.append({
                "baseline_id": baseline_id,
                "veto_reason": decision.get("replay_veto_reason"),
                "veto_prediction_harm": label.get("veto_prediction_harm"),
                "final_outcome_harm": label.get("oracle_harm"),
                "veto_correct": label.get("veto_prediction_harm") is True,
            })
    return {
        "run_id": run_id,
        "task_variant": trajectory.get("task_variant"),
        "protocol_id": trajectory.get("protocol_id"),
        "truth_binding": {
            "expected_initial_state_fingerprint": expected_fp,
            "trajectory_initial_state_fingerprint": contract.get("initial_state_fingerprint"),
            "valid": binding_ok,
        },
        "truth_binding_fingerprint": truth_binding_fingerprint(truth),
        "source_trace_chain": source_chain,
        "source_initial_state": source_initial,
        "harm_label_source": ORACLE_LABEL_VERSION,
        "baselines": baselines_out,
        "label_agreement": agreement,
        "veto_audit": veto_audit,
    }


def relabel_matrix(
    trajectories_dir: Path,
    spec_path: Path,
    label: str,
) -> dict:
    spec_runs = _spec_runs(spec_path)
    runs = []
    agree_total = {"agree": 0, "disagree": 0}
    for path in sorted(trajectories_dir.glob("*.json")):
        trajectory = _load(path)
        spec_run = spec_runs.get(trajectory.get("run_id"))
        if spec_run is None:
            raise ValueError(f"spec missing run_id {trajectory.get('run_id')}")
        entry = _label_run(trajectory, spec_run)
        runs.append(entry)
        agree_total["agree"] += entry["label_agreement"]["agree"]
        agree_total["disagree"] += entry["label_agreement"]["disagree"]
    return {
        "schema_version": ANNOTATION_SCHEMA,
        "matrix": label,
        "run_count": len(runs),
        "harm_label_source": ORACLE_LABEL_VERSION,
        "label_agreement": agree_total,
        "runs": runs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="协议 v0.4 独立 oracle 重标注（只读冻结轨迹）")
    parser.add_argument("--v01-main", nargs=2, metavar=("TRAJ_DIR", "SPEC"), required=True)
    parser.add_argument("--v03-e3", nargs=2, metavar=("TRAJ_DIR", "SPEC"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    matrices = []
    v01_dir, v01_spec = (Path(value) for value in args.v01_main)
    v03_dir, v03_spec = (Path(value) for value in args.v03_e3)
    matrices.append(relabel_matrix(v01_dir, v01_spec, "racer-v2-main-matrix-20260906"))
    matrices.append(relabel_matrix(v03_dir, v03_spec, "racer-v2-main-matrix-e3-v03-20260909"))

    veto_rows = [row for matrix in matrices for run in matrix["runs"] for row in run["veto_audit"]]
    veto_summary = {
        "veto_count": len(veto_rows),
        "veto_correct": sum(1 for row in veto_rows if row["veto_correct"]),
        "baseline_ids": sorted({row["baseline_id"] for row in veto_rows}),
    }
    output = {
        "schema_version": ANNOTATION_SCHEMA,
        "harm_label_source": ORACLE_LABEL_VERSION,
        "matrices": matrices,
        "label_agreement_total": {
            "agree": sum(m["label_agreement"]["agree"] for m in matrices),
            "disagree": sum(m["label_agreement"]["disagree"] for m in matrices),
        },
        "veto_accuracy": veto_summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "matrices": [m["matrix"] for m in matrices],
        "runs": [m["run_count"] for m in matrices],
        "label_agreement_total": output["label_agreement_total"],
        "veto_accuracy": veto_summary,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
