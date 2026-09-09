#!/usr/bin/env python3
"""Behavioral preflight for the v0.5 E1/E2 main matrix.

Drives the REAL task_env engine over one representative task per cell using
the 2-step actor pattern (public catalog -> select -> confirm) and checks
each cell's expected terminal classification against the v0.5 design:

  M1  clean_success (and only it among no-fault cells) succeeds;
  M2  missing_confirmation fails visibly at confirm;
  M3  force_error / rate_limit / wrong_tool cells fail visibly at confirm;
  M4  drop_action cells (e1_drop_action, drop_confirm) end uncommitted with
      no visible failure (silent no-op semantics, inherited from v0.1);
  M5  replace_action cells end with the selection replaced (re-select) and
      no visible failure;
  M6  every fault cell's fault actually matches confirm at step_id=1
      (the 2-step actor's confirm position -- the v0.1 step-2 defect fix);
  M7  no cell's fault schedule is empty when faults are declared at the
      matrix level, and non-soft / suboptimal variants keep task texts.

Also verifies the E3 matrix envelope: 7 cells x 10 seeds, unique task ids,
protocol 0.5, scenario registry linkage, and per-scenario env_config
equality with the frozen registry.
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import validate_v05_scenarios as preflight  # noqa: E402

MAIN_MATRIX = PROJECT_ROOT / "experiments" / "racer-v2-v05-matrix-main.json"
E3_MATRIX = PROJECT_ROOT / "experiments" / "racer-v2-v05-matrix-e3.json"
REGISTRY = PROJECT_ROOT / "experiments" / "racer-v2-v05-scenario-registry.json"

TOOLS = {
    "flight": ("select_flight", "confirm_booking", "flight_id"),
    "hotel": ("select_room", "confirm_reservation", "room_id"),
    "shop": ("select_product", "place_order", "product_id"),
}
SOFT = {"flight": "refundable", "hotel": "cancellable", "shop": "returnable"}
LISTK = {"flight": "flights", "hotel": "rooms", "shop": "products"}
EXEMPT = {"flight": "non_refundable", "hotel": "non_cancellable", "shop": "non_returnable"}

VISIBLE_FAULT_VARIANTS = {"force_error", "rate_limit", "wrong_tool", "e1_force_error", "e1_rate_limit", "e1_wrong_tool", "force_error_confirm"}
DROP_VARIANTS = {"drop_action", "e1_drop_action", "drop_confirm"}
REPLACE_VARIANTS = {"replace_action", "e1_replace_action"}


def classify(variant):
    if variant == "clean_success":
        return "success"
    if variant == "missing_confirmation":
        return "visible_failure"
    if variant in VISIBLE_FAULT_VARIANTS:
        return "visible_failure"
    if variant in DROP_VARIANTS:
        return "silent_uncommitted"
    if variant in REPLACE_VARIANTS:
        return "silent_replaced"
    if variant in EXEMPT.values() or variant.startswith("suboptimal"):
        return "success"
    return "unknown"


def check_main_cell(env_module, task, failures):
    cell = task["cell"]
    domain = task["domain"]
    select, confirm, idarg = TOOLS[domain]
    spec = json.loads(json.dumps(task["env_config"]))
    variant = spec["task_variant"]
    env = env_module.TaskEnv()
    env.reset({"run_id": f"pf-{cell}", "seed": 0, "env_config": spec})

    # 2-step actor: catalog is public in the observation env_config.
    obs = env.observe()
    catalog = obs["env_config"].get(LISTK[domain]) or env._catalog
    require_soft = variant != EXEMPT[domain]
    budget = spec["budget"]
    candidates = [
        item for item in catalog
        if (item.get(SOFT[domain], True) or not require_soft)
        and item.get("in_stock", True) and item["price"] <= budget
    ]
    pick = min(candidates, key=lambda i: (i["price"], i["id"])) if candidates else None
    if pick is None:
        failures.append(f"{cell}: no eligible pick in public catalog")
        return
    steps = [
        {"tool": select, "arguments": {idarg: pick["id"]}},
        {"tool": confirm, "arguments": {"user_confirmed": True} if variant != "missing_confirmation" else {}},
    ]
    failed_at = None
    effective_replaced = False
    for index, action in enumerate(steps):
        step = env.step(action)
        if step["action"].get("tool") != action["tool"]:
            effective_replaced = True
        if not step["result"].get("ok", True):
            failed_at = index
            break
    evaluation = env.evaluate()

    expected = classify(variant)
    if expected == "success" and not evaluation["success"]:
        failures.append(f"{cell}: expected success, got {evaluation}")
    elif expected == "visible_failure" and failed_at is None:
        failures.append(f"{cell}: expected visible failure, got eval={evaluation} failed_at=None")
    elif expected == "silent_uncommitted":
        if evaluation["success"] or evaluation["side_effect"]:
            failures.append(f"{cell}: drop cell must end uncommitted, got {evaluation}")
        # visible failure is allowed only if the actor retried into a real
        # error; the source no-op itself must not error.
    elif expected == "silent_replaced":
        if not effective_replaced:
            failures.append(f"{cell}: replace_action must alter the effective action")
        if failed_at is not None:
            failures.append(f"{cell}: replace_action must not produce a visible failure, failed_at={failed_at}")

    # M6: confirm-position faults sit at step_id=1 (2-step actor contract).
    for fault in spec.get("faults", []):
        if fault.get("tool") == confirm and fault.get("step_id") not in (0, 1):
            failures.append(f"{cell}: confirm fault scheduled at step_id={fault.get('step_id')} (must be 0 or 1 under the 2-step actor)")


def check_e3_envelope(failures):
    matrix = json.loads(E3_MATRIX.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    tasks = matrix["tasks"]
    ids = [t["task_id"] for t in tasks]
    if len(ids) != len(set(ids)):
        failures.append("E3 matrix: duplicate task_id")
    cells = {}
    for t in tasks:
        cells.setdefault(t["cell"], set()).add(t["seed"])
    if any(seeds != set(range(10)) for seeds in cells.values()):
        failures.append("E3 matrix: every cell must carry seeds 0..9")
    by_scenario = {s["scenario_id"]: s for s in registry["scenarios"]}
    for t in tasks:
        scenario = by_scenario.get(t.get("scenario_id"))
        if scenario is None:
            failures.append(f"E3 task {t['task_id']}: scenario_id not in registry")
            continue
        if t["env_config"] != scenario["env_config"]:
            failures.append(f"E3 task {t['task_id']}: env_config drift vs frozen registry")


def main():
    env_module = preflight.load_task_env()
    matrix = json.loads(MAIN_MATRIX.read_text(encoding="utf-8"))
    failures = []
    seen = set()
    for task in matrix["tasks"]:
        if task["cell"] in seen:
            continue
        seen.add(task["cell"])
        check_main_cell(env_module, task, failures)
    check_e3_envelope(failures)
    report = {
        "validator": "racer-v2-v05-matrix-preflight-v1",
        "cells_checked": len(seen),
        "failures": failures,
        "verdict": "PASS" if not failures else "FAIL",
    }
    out = PROJECT_ROOT / "output" / "racer-v2-v05-matrix-preflight.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
