#!/usr/bin/env python3
"""协议 v0.4：用 oracle 标注重建 canonical envelope。

输入：v0.3 E3 envelope（140 行，含旧 harm 标签）+ harm-oracle-annotation。
动作：
- protocol_id 升级 racer-v2-benchmark-protocol-0.4；
- harmful_repair 改由 oracle 标签覆写（与旧行为一致的验证断言）；
- 新增 3 字段：harm_label_source / harm_recomputed / cf_outcome_harm；
- 实验 id 重命名 racer-v2-main-matrix-e3-v04。

一致性断言（fail-closed）：
1. oracle 标签与旧 harmful_repair 必须逐行一致（本轮实证为零翻转；
   出现翻转时脚本拒绝产出，须人工裁决后走 v0.5）；
2. 行为字段（recovered_success/abstained/decision 等）零漂移。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "common"))

from harm_oracle import ORACLE_LABEL_VERSION  # noqa: E402

BEHAVIOR_FIELDS = (
    "recovered_success", "abstained", "decision", "original_success",
    "repair_steps", "latency_ms", "diagnosis_top1", "step_exact",
)


def _load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def rebuild(e3_v03_envelope: dict, annotation: dict) -> dict:
    # annotation lookup: run_id -> baseline_id -> oracle label
    runs = {}
    for matrix in annotation.get("matrices", []):
        for run in matrix.get("runs", []):
            baselines = {}
            for baseline_id, entry in (run.get("baselines") or {}).items():
                baselines[baseline_id] = entry
            runs[run["run_id"]] = baselines

    records = e3_v03_envelope.get("records", [])
    rebuilt = []
    mismatches = []
    for row in records:
        run_id = row.get("run_id")
        baseline_id = row.get("baseline_id")
        oracle_entry = runs.get(run_id, {}).get(baseline_id)
        if oracle_entry is None:
            raise ValueError(f"annotation missing run/baseline: {run_id}/{baseline_id}")
        oracle_harm = oracle_entry.get("oracle_harm")
        if oracle_harm is None:
            raise ValueError(f"oracle label unavailable: {run_id}/{baseline_id}: {oracle_entry.get('evidence_error')}")
        old_harm = row.get("harmful_repair")
        if oracle_harm != old_harm:
            mismatches.append({
                "run_id": run_id,
                "baseline_id": baseline_id,
                "old_harm": old_harm,
                "oracle_harm": oracle_harm,
                "evidence_form": oracle_entry.get("evidence_form"),
            })
        new_row = dict(row)
        new_row["protocol_id"] = "racer-v2-benchmark-protocol-0.4"
        new_row["harmful_repair"] = bool(oracle_harm)
        new_row["harm_label_source"] = ORACLE_LABEL_VERSION
        new_row["harm_recomputed"] = bool(oracle_harm)
        new_row["cf_outcome_harm"] = bool(oracle_entry.get("veto_prediction_harm")) if oracle_entry.get("veto_prediction_harm") is not None else (
            bool(old_harm) if old_harm is not None else False
        )
        rebuilt.append(new_row)
    if mismatches:
        raise SystemExit(
            "ORACLE_LABEL_FLIP_DETECTED: "
            + json.dumps(mismatches[:5], ensure_ascii=False)
            + f" ({len(mismatches)} rows) — 人工裁决后再定协议处置"
        )
    return {
        "schema_version": e3_v03_envelope.get("schema_version"),
        "experiment": "racer-v2-main-matrix-e3-v04",
        "count": len(rebuilt),
        "records": rebuilt,
        "deduplication": e3_v03_envelope.get("deduplication"),
    }


def verify_zero_drift(before: dict, after: dict) -> list[dict]:
    """行为字段必须零漂移（同一 run/baseline 键值逐一比对）。"""
    before_rows = {(r["run_id"], r["baseline_id"]): r for r in before.get("records", [])}
    drift = []
    for row in after.get("records", []):
        key = (row.get("run_id"), row.get("baseline_id"))
        old = before_rows.get(key)
        if old is None:
            drift.append({"key": key, "issue": "new_row_absent_in_v03"})
            continue
        for field in BEHAVIOR_FIELDS:
            if old.get(field) != row.get(field):
                drift.append({"key": key, "field": field, "v03": old.get(field), "v04": row.get(field)})
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v0.4 oracle 标注重建 E3 envelope")
    parser.add_argument("--v03-envelope", type=Path, required=True)
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    v03 = _load(args.v03_envelope)
    annotation = _load(args.annotation)
    rebuilt = rebuild(v03, annotation)
    drift = verify_zero_drift(v03, rebuilt)
    if drift:
        raise SystemExit("BEHAVIOR_DRIFT_DETECTED: " + json.dumps(drift[:5], ensure_ascii=False))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {rebuilt['count']} records to {args.output}; zero label flip; zero behavior drift")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
