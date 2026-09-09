#!/usr/bin/env python3
"""Build the v0.5 P0 smoke batch spec (one trial per new-domain scenario).

Smoke purpose: verify the END-TO-END chain (relay actor domain dispatch ->
task-env domain engine -> diagnoser -> recovery -> counterfactual -> receipts)
on hotel and shop E3 scenarios plus one flight scenario, 14 baselines each,
before committing to the full 980-record-per-model run.

Deliverable: output/racer-v2-v05-p0-smoke/batch-spec.json (task list format
consumed by agent-runner BATCH_SPEC).
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = PROJECT_ROOT / "experiments" / "racer-v2-v05-scenario-registry.json"
OUT_DIR = PROJECT_ROOT / "output" / "racer-v2-v05-p0-smoke"
OUT = OUT_DIR / "batch-spec.json"

BASELINES = [
    "raw_react", "fixed_retry", "exponential_backoff", "generic_reflection",
    "full_trace_judge", "step_by_step_diagnosis", "binary_search_diagnosis",
    "agentdebug_targeted_feedback", "always_recover", "racer",
    "racer_no_abstain", "racer_no_counterfactual", "oracle_root_cause",
    "oracle_recovery",
]


def main():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    tasks = []
    for scenario in registry["scenarios"]:
        sid = scenario["scenario_id"]
        env_config = json.loads(json.dumps(scenario["env_config"]))
        task_id = f"p0-v05-{sid}-trial-0"
        tasks.append({
            "task_id": task_id,
            "run_id": f"p0-v05-{sid}-20260910T000000Z-trial-0",
            "seed": 0,
            "episode_id": task_id,
            "protocol_id": "racer-v2-benchmark-protocol-0.5",
            "trial_id": 0,
            "model_resource_id": "oneapi-relay-glm-5.3-flash",
            "strict_replay": True,
            "evaluation_tier": "main",
            "baseline_registry_version": "racer-v2-main-baselines-v1",
            "main_comparison": True,
            "task_variant": scenario["task_variant"],
            "variant": scenario["task_variant"],
            "cell": f"p0:{sid}",
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
        })
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"tasks": tasks}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(tasks)} smoke tasks)")


if __name__ == "__main__":
    main()
