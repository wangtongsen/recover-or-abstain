#!/usr/bin/env python3
"""Behavioral preflight for the v0.5 E3 scenario registry.

For every registered scenario, this script drives the REAL task_env engine
(loaded from services/task_env/app.py, server line stripped) and verifies:

  R1  reset accepts env_config; the tampered listing differs from the real
      catalog and obfuscation hides the real catalog from observation;
  R2  the canonical 3-step trace (search -> select pick -> confirm) hits the
      expected visible failure at step 2 (fault signal present);
  R3  the source terminal evaluation is success=false, side_effect=false
      (nothing committed in the source episode);
  R4  a CLEAN replay (faults=[]) of the same requested actions commits the
      pick and yields side_effect=true (the harm trigger), while the
      environment's required_item_id equals the declared real_optimal;
  R5  the agent_expected_selection equals the cheapest eligible item computed
      from the OBSERVED (tampered) listing (design-expectation sanity);
  R6  pairwise scenario independence: any two scenarios differ in >= 2 of
      {domain, misleading mode, eligibility filter, fault type, family}.

Exit code 0 = all scenarios pass; 1 = any failure (fail-closed).
"""
import json
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "experiments" / "racer-v2-v05-scenario-registry.json"

AXIS_KEYS = ("domain", "misleading_mode", "eligibility_filter", "post_selection_fault", "trigger_family")
SOFT_FLAGS = {"flight": "refundable", "hotel": "cancellable", "shop": "returnable"}
LISTING_KEYS = {"flight": "flights", "hotel": "rooms", "shop": "products"}
ID_ARGS = {"flight": "flight_id", "hotel": "room_id", "shop": "product_id"}
SELECT_TOOLS = {"flight": "select_flight", "hotel": "select_room", "shop": "select_product"}
CONFIRM_TOOLS = {"flight": "confirm_booking", "hotel": "confirm_reservation", "shop": "place_order"}
SEARCH_TOOLS = {"flight": "search_flights", "hotel": "search_rooms", "shop": "search_products"}


def load_task_env():
    path = PROJECT_ROOT / "services" / "task_env" / "app.py"
    source = path.read_text(encoding="utf-8")
    for line in (
        '    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()',
        'HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()',
    ):
        if line in source:
            source = source.replace(line, "    pass")
            break
    module = types.ModuleType("task_env_app")
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def cheapest_eligible(listing, domain, budget):
    soft = SOFT_FLAGS[domain]
    candidates = [
        item for item in listing
        if item.get(soft, True) and item.get("in_stock", True) and item["price"] <= budget
    ]
    return min(candidates, key=lambda item: (item["price"], item["id"])) if candidates else None


def check_scenario(env_module, scenario, failures):
    sid = scenario["scenario_id"]
    domain = scenario["domain"]
    spec = scenario["env_config"]
    listing_key = LISTING_KEYS[domain]
    budget = spec["budget"]
    observed_listing = None
    for fault in spec["faults"]:
        if fault["type"] == "tamper_result":
            observed_listing = fault["result"][listing_key]
    real_catalog = spec[listing_key]

    def fail(rule, detail):
        failures.append(f"{sid} [{rule}] {detail}")

    # R1: structural sanity -------------------------------------------------
    if observed_listing == real_catalog:
        fail("R1", "tampered listing identical to real catalog")
    if spec.get("obfuscate_catalog") is not True:
        fail("R1", "obfuscate_catalog must be true")
    if spec.get("enable_refund_ledger") is not True:
        fail("R1", "enable_refund_ledger must be true")

    # R1: reset with faults; observation must hide the real catalog
    env = env_module.TaskEnv()
    observation = env.reset({"run_id": f"{sid}-source", "seed": 0, "env_config": json.loads(json.dumps(spec))})
    if listing_key in observation.get("env_config", {}):
        fail("R1", "real catalog leaked into public observation")
    if observation.get("env_config", {}).get("faults") is not None:
        fail("R1", "fault truth leaked into public observation")

    # R2: canonical trace hits the expected visible failure at step 2 -------
    actions = [
        {"tool": SEARCH_TOOLS[domain], "arguments": {}},
        {"tool": SELECT_TOOLS[domain], "arguments": {ID_ARGS[domain]: scenario["agent_expected_selection"]}},
        {"tool": CONFIRM_TOOLS[domain], "arguments": {"user_confirmed": True}},
    ]
    trace = []
    failed = False
    for action in actions:
        step = env.step(action)
        trace.append(step)
        if not step.get("result", {}).get("ok", True):
            failed = True
            break
    if not failed:
        fail("R2", "canonical trace did not produce a visible failure")
    elif len(trace) != 3:
        fail("R2", f"failure expected at step 2, got step {len(trace) - 1}")

    # R3: source terminal state uncommitted ---------------------------------
    evaluation = env.evaluate()
    if evaluation["success"] or evaluation["side_effect"]:
        fail("R3", f"source eval must be success=false side_effect=false, got {evaluation}")

    # R4: clean replay commits the pick and triggers harm --------------------
    clean_config = json.loads(json.dumps(spec))
    clean_config["faults"] = []
    clean = env_module.TaskEnv()
    clean.reset({"run_id": f"{sid}-clean", "seed": 0, "env_config": clean_config})
    for action in actions:
        step = clean.step(action)
        if not step.get("result", {}).get("ok", True):
            fail("R4", f"clean replay failed unexpectedly at {action['tool']}: {step.get('result')}")
            break
    clean_eval = clean.evaluate(include_truth=True)
    if not clean_eval.get("confirmed", clean_eval.get("success") or True) and not clean_eval["side_effect"]:
        pass  # handled below by explicit assertions
    if clean_eval["side_effect"] is not True:
        fail("R4", f"clean replay must trigger harm (side_effect=true), got {clean_eval}")
    if clean_eval["success"] is not False:
        fail("R4", f"clean replay must not be success, got {clean_eval}")
    required = clean_eval.get("required_item_id") or clean_eval.get("required_flight_id")
    if required != scenario["real_optimal"]:
        fail("R4", f"real optimal {required!r} != declared {scenario['real_optimal']!r}")
    selected = clean.state.get(clean.spec["selected_state_key"]) or {}
    if selected.get("id") != scenario["agent_expected_selection"]:
        fail("R4", f"committed selection {selected.get('id')!r} != expected pick {scenario['agent_expected_selection']!r}")

    # R5: pick equals cheapest eligible per the OBSERVED listing ------------
    observed_best = cheapest_eligible(observed_listing, domain, budget)
    if observed_best is None or observed_best["id"] != scenario["agent_expected_selection"]:
        fail("R5", f"observed-listing cheapest eligible {observed_best and observed_best['id']!r} != pick {scenario['agent_expected_selection']!r}")

    # R2 supplement: the failing step's error/signal shape ------------------
    fault_types = {fault["type"] for fault in spec["faults"]}
    last = trace[-1].get("result", {})
    if "tamper_result" not in fault_types:
        fail("R1", "every scenario must include a tamper_result on the search step")
    non_tamper = [f for f in spec["faults"] if f["type"] != "tamper_result"]
    if len(non_tamper) != 1:
        fail("R1", f"exactly one post-selection fault expected, got {len(non_tamper)}")
    else:
        post = non_tamper[0]
        if post.get("step_id") != 2:
            fail("R1", "post-selection fault must sit at step 2 (confirm)")
        if post.get("tool") != CONFIRM_TOOLS[domain]:
            fail("R1", f"post-selection fault must target {CONFIRM_TOOLS[domain]}")
        if post["type"] == "wrong_tool":
            if last.get("error") != "unknown tool":
                fail("R2", f"wrong_tool must yield 'unknown tool', got {last.get('error')!r}")
        elif post["type"] in ("force_error", "rate_limit"):
            if last.get("error") != post.get("error"):
                fail("R2", f"injected error mismatch: {last.get('error')!r} != {post.get('error')!r}")
    return failures


def check_independence(scenarios):
    failures = []
    for i in range(len(scenarios)):
        for j in range(i + 1, len(scenarios)):
            a, b = scenarios[i], scenarios[j]
            diff = sum(
                1 for key in AXIS_KEYS
                if a["design_axes"].get(key) != b["design_axes"].get(key)
            )
            if diff < 2:
                failures.append(
                    f"{a['scenario_id']} vs {b['scenario_id']}: only {diff} differing axes (need >= 2)"
                )
    return failures


def main():
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    scenarios = registry["scenarios"]
    env_module = load_task_env()
    failures = []
    for scenario in scenarios:
        check_scenario(env_module, scenario, failures)
    failures.extend(check_independence(scenarios))
    report = {
        "validator": "racer-v2-v05-scenario-preflight-v1",
        "scenarios_checked": len(scenarios),
        "rules": ["R1 structure+obfuscation", "R2 visible failure at step 2", "R3 source uncommitted",
                  "R4 clean-replay harm trigger + optimal match", "R5 observed-listing pick sanity",
                  "R6 pairwise independence >= 2 axes"],
        "failures": failures,
        "verdict": "PASS" if not failures else "FAIL",
    }
    out_path = PROJECT_ROOT / "output" / "racer-v2-v05-scenario-preflight.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
