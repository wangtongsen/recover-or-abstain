import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "services" / "agent_runner" / "app.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("test_local_experiment", ROOT / "scripts" / "local_experiment.py")
local_experiment = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(local_experiment)
SPEC = importlib.util.spec_from_file_location("test_agent_runner_app", SOURCE)
agent_runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = agent_runner
SPEC.loader.exec_module(agent_runner)


class RunnerBaselineTests(unittest.TestCase):
    def test_extended_spec_is_frozen_and_reproducible(self):
        first = local_experiment.build_extended_spec()
        second = local_experiment.build_extended_spec()
        self.assertEqual(first, second)
        self.assertEqual(len(first["tasks"]), 18)
        self.assertEqual(set(first["task_variants"]), set(local_experiment.TASK_VARIANTS))
        self.assertEqual(first["seeds"], [0, 1, 2])
        self.assertEqual({task["task_variant"] for task in first["tasks"]}, set(local_experiment.TASK_VARIANTS))
        self.assertEqual({task["seed"] for task in first["tasks"]}, {0, 1, 2})
        self.assertTrue(all(task["strict_replay"] is True for task in first["tasks"]))
        self.assertTrue(all(task["episode_id"] == task["task_id"] for task in first["tasks"]))
        self.assertTrue(all(task["reset"] == task["env_config"] for task in first["tasks"]))
        self.assertTrue(all("fault_truth" not in task for task in first["tasks"]))
        self.assertTrue(all(task["evaluation_tier"] == "pilot" for task in first["tasks"]))
        self.assertTrue(all(task["baseline_registry_version"] == "local-flight-pilot-v1" for task in first["tasks"]))
        self.assertTrue(all(task["main_comparison"] is False for task in first["tasks"]))
        self.assertEqual(first["experiment_role"], "pilot")
        self.assertFalse(first["main_comparison"])
        self.assertEqual(set(first["baseline_catalog"]), set(local_experiment.BASELINES))
        self.assertTrue(all(not entry["eligible_for_main"] for entry in first["baseline_catalog"].values()))
        self.assertEqual(
            json.loads((ROOT / "experiments" / "local-flight-extended-matrix.json").read_text(encoding="utf-8")),
            first,
        )
        self.assertEqual(
            (ROOT / "experiments" / "local-flight-extended-matrix.json").read_bytes(),
            (ROOT / "experiments" / "local-flight-extended.json").read_bytes(),
        )

    def test_base_spec_marks_paired_cells_for_strict_replay(self):
        spec = local_experiment.build_spec()
        self.assertTrue(all(task["strict_replay"] is True for task in spec["tasks"]))
        self.assertTrue(all(task["episode_id"] == task["task_id"] for task in spec["tasks"]))
        self.assertTrue(all("fault_truth" not in task for task in spec["tasks"]))
        self.assertTrue(all(task["evaluation_tier"] == "pilot" for task in spec["tasks"]))
        self.assertTrue(all(task["baseline_registry_version"] == "local-flight-pilot-v1" for task in spec["tasks"]))
        self.assertTrue(all(task["main_comparison"] is False for task in spec["tasks"]))
        self.assertEqual(spec["experiment_role"], "pilot")
        self.assertFalse(spec["main_comparison"])
        self.assertTrue(all(not entry["eligible_for_main"] for entry in spec["baseline_catalog"].values()))

    def test_run_task_forwards_complete_environment_configuration(self):
        calls = []

        def fake_post(base, path, payload):
            calls.append((base, path, payload))
            if path == "/reset":
                return {"state": {}}
            if path == "/step":
                return {"result": {"ok": False}, "observation": {}}
            if path == "/diagnose":
                return {"candidates": []}
            if path == "/choose":
                return {"decision": "abstain", "patch": None}
            raise AssertionError((base, path, payload))

        config = {
            "budget": 123,
            "flights": [{"id": "CUSTOM", "price": 99, "refundable": True}],
            "task_variant": "clean_success",
            "variant": "clean_success",
            "actions": [{"tool": "search_flights", "arguments": {}}],
            "invariants": ["custom invariant"],
        }
        with patch.object(agent_runner, "post", side_effect=fake_post), patch.object(
            agent_runner, "get", return_value={"success": False, "faults_applied": []}
        ):
            agent_runner.run_task({"task_id": "demo", "run_id": "config-run", "env_config": config})

        reset = next(payload for _base, path, payload in calls if path == "/reset")
        self.assertEqual(reset["env_config"], {**config, "faults": []})
        self.assertEqual(reset["budget"], 123)
        self.assertEqual(reset["flights"], config["flights"])
        self.assertEqual(reset["actions"], config["actions"])
        self.assertEqual(reset["invariants"], config["invariants"])

    def test_run_task_supports_requested_baselines_and_keeps_legacy_fields(self):
        calls = []
        patch_action = {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
        fault_truth = [{"fault_id": "replace-select", "step_id": 1, "replacement": patch_action}]
        trace = [{"action": {"tool": "search_flights", "arguments": {}}, "result": {"ok": True}}]
        diagnosis = {"candidates": [{"cause": "selected_non_refundable_flight", "confidence": 0.9}]}

        def fake_post(base, path, payload):
            calls.append((base, path, payload))
            if base == agent_runner.TASK_ENV_URL and path == "/reset":
                return {"fault_truth": fault_truth}
            if base == agent_runner.TASK_ENV_URL and path == "/step":
                return trace[0]
            if base == agent_runner.DIAGNOSER_URL:
                return diagnosis
            if base == agent_runner.RECOVERY_URL and path == "/choose":
                return {"baseline_id": "recovery", "decision": "abstain", "patch": None}
            if base == agent_runner.RECOVERY_URL and path == "/baseline":
                if payload["baseline_id"] == "raw":
                    return {"baseline_id": "raw", "decision": "abstain", "patch": None}
                return {"baseline_id": "oracle", "decision": "oracle_repair", "step_id": 0, "patch": patch_action}
            if base == agent_runner.REPLAYER_URL:
                return {"trace": [], "evaluation": {"success": True}}
            raise AssertionError((base, path, payload))

        with patch.object(agent_runner, "post", side_effect=fake_post), patch.object(
            agent_runner, "get", return_value={"success": False, "faults_applied": []}
        ):
            result = agent_runner.run_task(
                {
                    "task_id": "demo",
                    "run_id": "run-1",
                    "evaluation_tier": "pilot",
                    "baseline_registry_version": "local-flight-pilot-v1",
                    "main_comparison": False,
                    "actions": [{"tool": "search_flights", "arguments": {}}],
                    "baselines": ["raw", "recovery", "oracle"],
                    "fault_truth": fault_truth,
                }
            )

        self.assertEqual(result["trace"], trace)
        self.assertFalse(result["original_evaluation"]["success"])
        self.assertEqual(result["decision"]["baseline_id"], "recovery")
        self.assertIsNone(result["counterfactual"])
        self.assertEqual(set(result["baselines"]), {"raw", "recovery", "oracle"})
        self.assertEqual(result["baselines"]["raw"]["decision"]["baseline_id"], "raw")
        self.assertIsNone(result["baselines"]["raw"]["counterfactual"])
        self.assertEqual(result["baselines"]["oracle"]["counterfactual"]["patched_step_id"], 0)
        baseline_calls = [payload for base, path, payload in calls if base == agent_runner.RECOVERY_URL and path == "/baseline"]
        raw_payload = next(payload for payload in baseline_calls if payload["baseline_id"] == "raw")
        oracle_payload = next(payload for payload in baseline_calls if payload["baseline_id"] == "oracle")
        self.assertNotIn("fault_truth", raw_payload)
        self.assertEqual(oracle_payload["fault_truth"], fault_truth)

    def test_runner_rejects_unknown_or_unregistered_baseline(self):
        def fake_post(base, path, payload):
            if path == "/reset":
                return {"state": {}}
            if path == "/step":
                return {"result": {"ok": False}, "observation": {}}
            if path == "/diagnose":
                return {"candidates": []}
            raise AssertionError((base, path, payload))

        task = {
            "task_id": "unknown-baseline",
            "run_id": "unknown-baseline-run",
            "evaluation_tier": "pilot",
            "baseline_registry_version": "local-flight-pilot-v1",
            "main_comparison": False,
            "actions": [{"tool": "search_flights", "arguments": {}}],
            "baselines": ["raw", "racer"],
        }
        with patch.object(agent_runner, "post", side_effect=fake_post), patch.object(
            agent_runner, "get", return_value={"success": False}
        ):
            with self.assertRaisesRegex(ValueError, "not registered"):
                agent_runner.run_task(task)

    def test_default_actor_metadata_and_actions_are_stable(self):
        actions, metadata = agent_runner.load_actor({})
        self.assertEqual(actions, agent_runner.DEFAULT_ACTIONS)
        self.assertEqual(metadata["actor_id"], "deterministic")
        self.assertEqual(metadata["config_hash"], agent_runner._config_hash(agent_runner.DEFAULT_ACTIONS))

    def test_run_task_uses_project_json_actor_and_records_metadata(self):
        calls = []
        policy_path = ROOT / "experiments" / "actors" / "basic-recovery-actions.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))

        def fake_post(base, path, payload):
            calls.append((base, path, payload))
            if path == "/reset":
                return {"state": {}}
            if path == "/step":
                return {"requested_action": {k: payload[k] for k in ("tool", "arguments")}, "action": {k: payload[k] for k in ("tool", "arguments")}, "result": {"ok": True}, "observation": {}}
            if path == "/diagnose":
                return {"candidates": []}
            if path == "/choose":
                return {"decision": "abstain", "patch": None}
            raise AssertionError((base, path, payload))

        with patch.object(agent_runner, "post", side_effect=fake_post), patch.object(
            agent_runner, "get", return_value={"success": False, "faults_applied": []}
        ):
            result = agent_runner.run_task({"task_id": "demo", "run_id": "actor-json", "actor": {"type": "json", "path": str(policy_path), "actor_id": "json-demo"}})

        self.assertEqual(result["actor_id"], "json-demo")
        self.assertEqual(result["actor_config_hash"], agent_runner._config_hash({"type": "json", "config": policy}))
        self.assertEqual(len(result["trace"]), len(policy["actions"]))
        self.assertTrue(all(item["actor_id"] == "json-demo" for item in result["trace"]))
        self.assertTrue(all(item["actor_config_hash"] == result["actor_config_hash"] for item in result["trace"]))
        self.assertEqual([call[2]["tool"] for call in calls if call[1] == "/step"], [item["tool"] for item in policy["actions"]])

    def test_python_actor_receives_public_observation_and_context(self):
        seen = []
        source = (
            "def act(observation, context):\n"
            "    seen = context.get('step_id')\n"
            "    return {'tool': 'search_flights', 'arguments': {}} if seen == 0 else None\n"
        )
        def fake_post(base, path, payload):
            if path == "/reset":
                return {"state": {}, "public": True}
            if path == "/step":
                return {"result": {"ok": False}, "observation": {"public": True}}
            if path == "/diagnose":
                return {"candidates": []}
            if path == "/choose":
                return {"decision": "abstain", "patch": None}
            raise AssertionError((base, path, payload))
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            actor_path = Path(directory) / "actor.py"
            actor_path.write_text(source, encoding="utf-8")
            with patch.object(agent_runner, "post", side_effect=fake_post), patch.object(
                agent_runner, "get", return_value={"success": False, "faults_applied": []}
            ):
                result = agent_runner.run_task({"task_id": "demo", "run_id": "actor-python", "actor": {"type": "python", "path": str(actor_path), "actor_id": "py-demo"}})
        self.assertEqual(result["actor_id"], "py-demo")
        self.assertEqual(result["actor_config_hash"], agent_runner.hashlib.sha256(source.encode("utf-8")).hexdigest())
        self.assertEqual(result["trace"][0]["actor_id"], "py-demo")

    def test_actor_paths_must_stay_inside_project_directory(self):
        with self.assertRaisesRegex(ValueError, "inside project directory"):
            agent_runner.load_actor({"actor": {"type": "json", "path": "/tmp/actor.json"}})

    def test_summarize_accepts_project_output_result_directory(self):
        output_dir = ROOT / "output" / "task74-trajectories"
        self.assertEqual(local_experiment._allowed_path(output_dir), output_dir.resolve())
        self.assertEqual(
            local_experiment._allowed_path("output/task74-trajectories"),
            output_dir.resolve(),
        )

    def test_summarize_rejects_broad_or_external_input_paths(self):
        for path in (ROOT, ROOT / "output", "/tmp", "/"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                local_experiment._allowed_path(path)

    def test_output_writes_cannot_escape_reports_and_experiments(self):
        with self.assertRaises(ValueError):
            local_experiment._allowed_path(ROOT / "output" / "summary.json", output=True)

    def test_run_task_defaults_to_recovery_baseline(self):
        calls = []

        def fake_post(base, path, payload):
            calls.append((base, path))
            if path == "/reset":
                return {"fault_truth": []}
            if path == "/step":
                return {"result": {"ok": False}}
            if path == "/diagnose":
                return {"candidates": []}
            if path == "/choose":
                return {"decision": "abstain", "patch": None}
            raise AssertionError((base, path, payload))

        with patch.object(agent_runner, "post", side_effect=fake_post), patch.object(
            agent_runner, "get", return_value={"success": False, "faults_applied": []}
        ):
            result = agent_runner.run_task({"task_id": "demo", "run_id": "run-2"}, index=0)

        self.assertEqual(list(result["baselines"]), ["recovery"])
        self.assertNotIn((agent_runner.RECOVERY_URL, "/baseline"), calls)


if __name__ == "__main__":
    unittest.main()
