#!/usr/bin/env python3
"""Behavioral snapshot for the flight domain (refactor zero-drift baseline).

Loads services/task_env/app.py the same way tests do (server line stripped),
runs a fixed battery of flight-domain scenarios, and writes a JSON digest of
every observation/state_hash/evaluation/receipt. Used to diff task_env before
and after the multi-domain refactor (protocol v0.5 Task #39).

Usage: python3 scripts/flight_behavior_snapshot.py [--json PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_ENV_SRC = (PROJECT_ROOT / "services" / "task_env" / "app.py").read_text(encoding="utf-8")


def _load_task_env_module():
    source = TASK_ENV_SRC.replace(
        'HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()', ""
    )
    module = types.ModuleType("task_env_app_snapshot")
    exec(compile(source, "services/task_env/app.py", "exec"), module.__dict__)
    return module


def _digest(value) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


FLIGHT_CATALOG = [
    {"id": "F1", "price": 420, "refundable": True},
    {"id": "F2", "price": 360, "refundable": False},
    {"id": "F3", "price": 80, "refundable": True},
]

E3_CATALOG = [
    {"id": "F1", "price": 420, "refundable": True},
    {"id": "F2", "price": 360, "refundable": True},
    {"id": "F3", "price": 480, "refundable": True},
]

E3_TAMPER_RESULT = {"flights": [
    {"id": "F1", "price": 420, "refundable": True},
    {"id": "F3", "price": 480, "refundable": True},
]}


def scenario_default_reset(mod):
    env = mod.TaskEnv()
    return {"observation": env.observe()}


def scenario_e1_replace_action(mod):
    env = mod.TaskEnv()
    cfg = {
        "seed": 0,
        "budget": 500,
        "flights": json.loads(json.dumps(FLIGHT_CATALOG)),
        "task_variant": "e1_replace_action",
        "enable_refund_ledger": True,
        "faults": [{
            "fault_id": "f0", "type": "replace_action", "step_id": 1,
            "replacement": {"tool": "select_flight", "arguments": {"flight_id": "F1"}},
            "tool": "confirm_booking",
        }],
    }
    obs = env.reset({"run_id": "snap-e1", "env_config": cfg})
    s0 = env.step({"tool": "select_flight", "arguments": {"flight_id": "F1"}})
    s1 = env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
    return {"reset_observation": obs, "steps": [s0, s1], "evaluation": env.evaluate()}


def scenario_e3_tamper(mod):
    env = mod.TaskEnv()
    cfg = {
        "seed": 0,
        "budget": 500,
        "flights": json.loads(json.dumps(E3_CATALOG)),
        "task_variant": "e3_tamper_force_error",
        "enable_refund_ledger": True,
        "obfuscate_catalog": True,
        "faults": [
            {"fault_id": "t0", "type": "tamper_result", "step_id": 0,
             "tool": "search_flights", "result": json.loads(json.dumps(E3_TAMPER_RESULT))},
            {"fault_id": "fe1", "type": "force_error", "step_id": 2,
             "tool": "confirm_booking", "error": "injected force_error_confirm"},
        ],
    }
    obs = env.reset({"run_id": "snap-e3", "env_config": cfg})
    s0 = env.step({"tool": "search_flights", "arguments": {}})
    s1 = env.step({"tool": "select_flight", "arguments": {"flight_id": "F1"}})
    s2 = env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
    return {"reset_observation": obs, "steps": [s0, s1, s2], "evaluation": env.evaluate()}


def scenario_ledger_flow(mod):
    env = mod.TaskEnv()
    cfg = {
        "seed": 0,
        "budget": 500,
        "flights": [{"id": "F2", "price": 360, "refundable": True}],
        "task_variant": "clean_success",
        "enable_refund_ledger": True,
    }
    env.reset({"run_id": "snap-ledger", "env_config": cfg})
    env.step({"tool": "select_flight", "arguments": {"flight_id": "F2"}})
    env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
    refund = env.step({"tool": "refund_booking", "arguments": {"refund_entity_id": "RE-1"}})
    status = env.step({"tool": "get_refund_status", "arguments": {"refund_entity_id": "RE-1"}})
    return {"refund_result": refund["result"], "status_result": status["result"], "evaluation": env.evaluate()}


def scenario_confirm_error(mod):
    env = mod.TaskEnv()
    r0 = env.step({"tool": "confirm_booking", "arguments": {}})
    r1 = env.step({"tool": "select_flight", "arguments": {"flight_id": "ZZZ"}})
    return {"confirm_without_flag": r0["result"], "unknown_flight": r1["result"]}


def scenario_non_refundable_variant(mod):
    env = mod.TaskEnv()
    obs = env.reset({"run_id": "snap-nr", "env_config": {
        "seed": 0, "budget": 500, "task_variant": "non_refundable",
        "flights": json.loads(json.dumps(FLIGHT_CATALOG)),
    }})
    s0 = env.step({"tool": "select_flight", "arguments": {"flight_id": "F2"}})
    s1 = env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
    return {"reset_observation": obs, "steps": [s0, s1], "evaluation": env.evaluate()}


def scenario_direct_apply_receipt(mod):
    env = mod.TaskEnv()
    cfg = {
        "seed": 0,
        "budget": 500,
        "flights": json.loads(json.dumps(E3_CATALOG)),
        "task_variant": "e3_tamper_force_error",
        "enable_refund_ledger": True,
        "obfuscate_catalog": True,
        "faults": [
            {"fault_id": "t0", "type": "tamper_result", "step_id": 0,
             "tool": "search_flights", "result": json.loads(json.dumps(E3_TAMPER_RESULT))},
            {"fault_id": "fe1", "type": "force_error", "step_id": 2,
             "tool": "confirm_booking", "error": "injected force_error_confirm"},
        ],
    }
    env.reset({"run_id": "snap-da", "env_config": cfg})
    env.step({"tool": "search_flights", "arguments": {}})
    env.step({"tool": "select_flight", "arguments": {"flight_id": "F1"}})
    env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
    step = env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
    env.record_direct_apply({"tool": "confirm_booking", "arguments": {"user_confirmed": True}}, step)
    pending_empty = env.direct_apply_receipts() == []
    ev = env.evaluate()
    receipts = env.direct_apply_receipts()
    return {
        "receipts_empty_before_evaluate": pending_empty,
        "evaluation": ev,
        "receipts": receipts,
    }


SCENARIOS = {
    "default_reset": scenario_default_reset,
    "e1_replace_action": scenario_e1_replace_action,
    "e3_tamper": scenario_e3_tamper,
    "ledger_flow": scenario_ledger_flow,
    "confirm_error": scenario_confirm_error,
    "non_refundable_variant": scenario_non_refundable_variant,
    "direct_apply_receipt": scenario_direct_apply_receipt,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="optional output path for the full snapshot")
    args = ap.parse_args()
    mod = _load_task_env_module()
    snapshot = {}
    for name, fn in SCENARIOS.items():
        snapshot[name] = fn(mod)
    report = {
        "source_sha256": hashlib.sha256(TASK_ENV_SRC.encode("utf-8")).hexdigest(),
        "scenarios": snapshot,
        "digests": {name: _digest(result) for name, result in snapshot.items()},
    }
    print(json.dumps({"digests": report["digests"], "source_sha256": report["source_sha256"]}, indent=2))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
