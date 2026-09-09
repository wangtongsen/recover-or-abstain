#!/usr/bin/env python3
"""Build the pre-registered v0.5 execution matrices.

Produces TWO matrix files (both frozen BEFORE any v0.5 execution):

1. experiments/racer-v2-v05-matrix-e3.json
   E3 irreversible-side-effect track: 7 scenarios (from the frozen scenario
   registry) x 10 seeds x 14 baselines = 980 records per model; two models
   (GLM primary, DeepSeek secondary) -> 1960 records total at execution time.
   The matrix itself is model-agnostic: each task carries
   model_resource_id=None-by-default and the executor binds one model per
   pass (same pattern as v0.3 E3, which bound GLM at execution).

2. experiments/racer-v2-v05-matrix-main.json
   E1/E2 3-domain track: clean_success + non_refundable-style planning
   variants + E1 fault cells per domain (11 cells/domain x 10 seeds), used
   for the v0.5 main-table domain expansion.

Both matrices reference protocol racer-v2-benchmark-protocol-0.5 and the
frozen baseline registry racer-v2-main-baselines-v1 (14 baselines).
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "experiments" / "racer-v2-v05-scenario-registry.json"
E3_OUT = PROJECT_ROOT / "experiments" / "racer-v2-v05-matrix-e3.json"
MAIN_OUT = PROJECT_ROOT / "experiments" / "racer-v2-v05-matrix-main.json"

BASELINES = [
    "raw_react", "fixed_retry", "exponential_backoff", "generic_reflection",
    "full_trace_judge", "step_by_step_diagnosis", "binary_search_diagnosis",
    "agentdebug_targeted_feedback", "always_recover", "racer",
    "racer_no_abstain", "racer_no_counterfactual", "oracle_root_cause",
    "oracle_recovery",
]
SEEDS = list(range(10))

DOMAIN_CATALOGS = {
    "flight": {
        "key": "flights",
        "catalog": [
            {"id": "F1", "price": 420, "refundable": True},
            {"id": "F2", "price": 360, "refundable": False},
            {"id": "F3", "price": 480, "refundable": True},
        ],
        "non_soft_variant": "non_refundable",
        "suboptimal_variant": "suboptimal_refundable",
        "non_soft_catalog": [
            {"id": "F1", "price": 420, "refundable": False},
            {"id": "F2", "price": 360, "refundable": False},
            {"id": "F3", "price": 480, "refundable": False},
        ],
        "suboptimal_catalog": [
            {"id": "F1", "price": 420, "refundable": True},
            {"id": "F2", "price": 360, "refundable": True},
            {"id": "F3", "price": 480, "refundable": True},
        ],
    },
    "hotel": {
        "key": "rooms",
        "catalog": [
            {"id": "R1", "price": 420, "cancellable": True},
            {"id": "R2", "price": 360, "cancellable": False},
            {"id": "R3", "price": 480, "cancellable": True},
        ],
        "non_soft_variant": "non_cancellable",
        "suboptimal_variant": "suboptimal_cancellable",
        "non_soft_catalog": [
            {"id": "R1", "price": 420, "cancellable": False},
            {"id": "R2", "price": 360, "cancellable": False},
            {"id": "R3", "price": 480, "cancellable": False},
        ],
        "suboptimal_catalog": [
            {"id": "R1", "price": 420, "cancellable": True},
            {"id": "R2", "price": 360, "cancellable": True},
            {"id": "R3", "price": 480, "cancellable": True},
        ],
    },
    "shop": {
        "key": "products",
        "catalog": [
            {"id": "P1", "price": 420, "returnable": True, "in_stock": True},
            {"id": "P2", "price": 360, "returnable": False, "in_stock": True},
            {"id": "P3", "price": 480, "returnable": True, "in_stock": False},
        ],
        "non_soft_variant": "non_returnable",
        "suboptimal_variant": "suboptimal_returnable",
        "non_soft_catalog": [
            {"id": "P1", "price": 420, "returnable": False, "in_stock": True},
            {"id": "P2", "price": 360, "returnable": False, "in_stock": True},
            {"id": "P3", "price": 480, "returnable": False, "in_stock": True},
        ],
        "suboptimal_catalog": [
            {"id": "P1", "price": 420, "returnable": True, "in_stock": True},
            {"id": "P2", "price": 360, "returnable": True, "in_stock": True},
            {"id": "P3", "price": 480, "returnable": True, "in_stock": True},
        ],
    },
}

# E1 fault cells per domain (mirror the v0.1 flight cells, domain-adapted).
# STEP-POSITION CONTRACT (v0.5): on the E1/E2 track the catalog is public in
# the observation env_config, so the relay actor runs the 2-step pattern
# (select -> confirm; confirm is step_id=1). v0.1 scheduled the
# force_error_confirm/drop_confirm variant faults at step_id=2, which never
# fired under the 2-step actor (inherited defect discovered 2026-09-10 while
# preflighting v0.5; those two v0.1 cells effectively executed as
# clean_success). v0.5 fixes all confirm-position faults to step_id=1.
E1_FAULT_CELLS = {
    "replace_action": lambda dom: [
        {
            "fault_id": "replace_action-0", "type": "replace_action", "step_id": 1,
            "replacement": {"tool": f"select_{dom['item_noun']}", "arguments": {dom["id_arg"]: dom["suboptimal_id"]}},
            "tool": dom["confirm_tool"],
        }
    ],
    "force_error": lambda dom: [
        {"fault_id": "force_error-0", "type": "force_error", "step_id": 1, "tool": dom["confirm_tool"], "error": "injected force_error"}
    ],
    "rate_limit": lambda dom: [
        {"fault_id": "rate_limit-0", "type": "rate_limit", "step_id": 1, "tool": dom["confirm_tool"], "error": "injected rate_limit", "status_code": 429}
    ],
    "wrong_tool": lambda dom: [
        {"fault_id": "wrong_tool-0", "type": "wrong_tool", "step_id": 1, "tool": dom["confirm_tool"]}
    ],
    "drop_action": lambda dom: [
        {"fault_id": "drop_action-0", "type": "drop_action", "step_id": 1, "tool": dom["confirm_tool"]}
    ],
}

DOMAIN_TOOLING = {
    "flight": {"item_noun": "flight", "id_arg": "flight_id", "confirm_tool": "confirm_booking",
               "suboptimal_id": "F3", "legacy": True},
    "hotel": {"item_noun": "room", "id_arg": "room_id", "confirm_tool": "confirm_reservation",
              "suboptimal_id": "R3", "legacy": False},
    "shop": {"item_noun": "product", "id_arg": "product_id", "confirm_tool": "place_order",
             "suboptimal_id": "P2", "legacy": False},
}


def e3_tasks():
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    tasks = []
    for scenario in registry["scenarios"]:
        for seed in SEEDS:
            env_config = json.loads(json.dumps(scenario["env_config"]))
            sid = scenario["scenario_id"]
            task_id = f"v05-e3-{sid}-trial-{seed}"
            run_id = f"v05-e3-{sid}-20260906T000000Z-trial-{seed}"
            task = {
                "task_id": task_id,
                "run_id": run_id,
                "seed": seed,
                "episode_id": task_id,
                "protocol_id": "racer-v2-benchmark-protocol-0.5",
                "trial_id": seed,
                "model_resource_id": None,
                "strict_replay": True,
                "evaluation_tier": "main",
                "baseline_registry_version": "racer-v2-main-baselines-v1",
                "main_comparison": True,
                "task_variant": scenario["task_variant"],
                "variant": scenario["task_variant"],
                "cell": f"{scenario['domain']}:{sid}",
                "domain": scenario["domain"],
                "scenario_id": sid,
                "actor": {"type": "python", "path": "experiments/actors/remote-relay-actor.py",
                          "actor_id": "relay-llm-paired-pilot"},
                "baselines": list(BASELINES),
                "max_actor_steps": 6,
                "faults": env_config["faults"],
                "fault_truth": env_config["faults"],
                "env_config": env_config,
                "reset": json.loads(json.dumps(env_config)),
            }
            tasks.append(task)
    return tasks


def main_tasks():
    tasks = []
    for domain, spec in DOMAIN_CATALOGS.items():
        tooling = DOMAIN_TOOLING[domain]
        key = spec["key"]
        cells = []

        # clean_success + planning variants (no faults)
        cells.append(("clean_success", spec["catalog"], []))
        cells.append((spec["non_soft_variant"], spec["non_soft_catalog"], []))
        cells.append((spec["suboptimal_variant"], spec["suboptimal_catalog"], []))
        cells.append(("missing_confirmation", spec["catalog"], []))
        # Variant-driven confirm faults are written EXPLICITLY (v0.1 pattern)
        # but at the CORRECT step position for the 2-step actor: confirm is
        # step_id=1 (v0.1 scheduled step_id=2 which never fired -- see the
        # step-position contract note above). An explicit faults list is
        # authoritative and never auto-injected.
        cells.append(("force_error_confirm", spec["catalog"], [
            {"fault_id": "force-error-confirm", "type": "force_error", "step_id": 1,
             "tool": tooling["confirm_tool"], "error": "injected force_error_confirm"}
        ]))
        cells.append(("drop_confirm", spec["catalog"], [
            {"fault_id": "drop-confirm", "type": "drop_action", "step_id": 1,
             "tool": tooling["confirm_tool"]}
        ]))

        # E1 fault cells (explicit fault schedules)
        for fault_name, fault_builder in E1_FAULT_CELLS.items():
            dom = dict(tooling)
            dom.update({"item_noun": tooling["item_noun"], "id_arg": tooling["id_arg"],
                        "confirm_tool": tooling["confirm_tool"], "suboptimal_id": tooling["suboptimal_id"]})
            cells.append((f"e1_{fault_name}", spec["catalog"], fault_builder(dom)))

        for variant, catalog, faults in cells:
            for seed in SEEDS:
                env_config = {
                    "domain": domain,
                    "budget": 500,
                    key: json.loads(json.dumps(catalog)),
                    "task_variant": variant,
                    "faults": json.loads(json.dumps(faults)),
                    "enable_refund_ledger": True,
                }
                # E3-style obfuscation is NOT used on the E1/E2 track: the
                # catalog is public there (v0.1 semantics).
                task_id = f"v05-main-{domain}-{variant}-trial-{seed}"
                task = {
                    "task_id": task_id,
                    "run_id": f"v05-main-{domain}-{variant}-20260906T000000Z-trial-{seed}",
                    "seed": seed,
                    "episode_id": task_id,
                    "protocol_id": "racer-v2-benchmark-protocol-0.5",
                    "trial_id": seed,
                    "model_resource_id": None,
                    "strict_replay": True,
                    "evaluation_tier": "main",
                    "baseline_registry_version": "racer-v2-main-baselines-v1",
                    "main_comparison": True,
                    "task_variant": variant,
                    "variant": variant,
                    "cell": f"{domain}:{variant}",
                    "domain": domain,
                    "actor": {"type": "python", "path": "experiments/actors/remote-relay-actor.py",
                              "actor_id": "relay-llm-paired-pilot"},
                    "baselines": list(BASELINES),
                    "max_actor_steps": 6,
                    "faults": json.loads(json.dumps(faults)),
                    "fault_truth": json.loads(json.dumps(faults)),
                    "env_config": env_config,
                    "reset": json.loads(json.dumps(env_config)),
                }
                tasks.append(task)
    return tasks


def envelope(experiment, matrix_id, description, design, tasks):
    return {
        "schema_version": "racer-v2-v05-matrix-v1",
        "experiment": experiment,
        "matrix_id": matrix_id,
        "protocol_id": "racer-v2-benchmark-protocol-0.5",
        "model_resource_id": None,
        "baseline_registry_version": "racer-v2-main-baselines-v1",
        "evaluation_tier": "main",
        "main_comparison": True,
        "description": description,
        "design": design,
        "scenario_registry": "racer-v2-v05-scenario-registry-v1",
        "tasks": tasks,
    }


def main():
    e3 = e3_tasks()
    main_track = main_tasks()
    e3_envelope = envelope(
        experiment="racer-v2-v05-matrix-e3",
        matrix_id="racer-v2-v05-e3-irreversible-side-effect",
        description=(
            "E3 irreversible-side-effect track (protocol v0.5): 7 pre-registered scenarios "
            "x 10 seeds x 14 baselines = 980 records per model pass; executor binds one "
            "model per pass (GLM primary, DeepSeek secondary) for 1960 records total."
        ),
        design={
            "scenarios": 7,
            "seeds_per_scenario": 10,
            "baselines": 14,
            "expected_records_per_model": 980,
            "models": ["oneapi-relay-glm-5.3-flash", "oneapi-relay-deepseek-v4-flash"],
            "domains": ["flight", "hotel", "shop"],
        },
        tasks=e3,
    )
    main_envelope = envelope(
        experiment="racer-v2-v05-matrix-main",
        matrix_id="racer-v2-v05-main-3domain",
        description=(
            "E1/E2 3-domain track (protocol v0.5): 11 cells/domain (6 planning variants + "
            "5 E1 fault types) x 10 seeds x 14 baselines per domain; 330 episodes = 4620 "
            "records per model pass; catalogs public (v0.1 semantics, no obfuscation)."
        ),
        design={
            "domains": 3,
            "cells_per_domain": 11,
            "seeds_per_cell": 10,
            "baselines": 14,
            "expected_records_per_model": 4620,
            "expected_records_per_model_note": "3 domains x 11 cells x 10 seeds = 330 episodes; x 14 baselines = 4620 records",
            "models": ["oneapi-relay-glm-5.3-flash", "oneapi-relay-deepseek-v4-flash"],
        },
        tasks=main_track,
    )
    E3_OUT.write_text(json.dumps(e3_envelope, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    MAIN_OUT.write_text(json.dumps(main_envelope, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    cells_e3 = {t["cell"] for t in e3}
    cells_main = {t["cell"] for t in main_track}
    print(f"E3: {len(e3)} episodes, {len(cells_e3)} cells -> {E3_OUT.name}")
    print(f"main: {len(main_track)} episodes, {len(cells_main)} cells -> {MAIN_OUT.name}")
    print(f"E3 records per model: {len(e3) * 14}; main records per model: {len(main_track) * 14}")


if __name__ == "__main__":
    main()
