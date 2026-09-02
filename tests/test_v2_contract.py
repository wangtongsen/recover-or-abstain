import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "services" / "common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))
from environment_contract import environment_contract, expected_clean_replay_contract


def load_module(name, path, block_server=False):
    if not block_server:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    import http.server

    class NoopServer:
        def __init__(self, *_args, **_kwargs):
            pass

        def serve_forever(self):
            pass

    with patch.object(http.server, "HTTPServer", NoopServer):
        return load_module(name, path)


counterfactual = load_module("test_v2_counterfactual", ROOT / "services" / "counterfactual" / "app.py", block_server=True)
evaluator = load_module("test_v2_evaluator", ROOT / "services" / "evaluator" / "app.py")
analyze = load_module("test_v2_analyze", ROOT / "scripts" / "analyze_results.py")
adapter = load_module("test_v2_adapter", ROOT / "adapters" / "tau2_airline_adapter.py")
task_env = load_module("test_v2_task_env", ROOT / "services" / "task_env" / "app.py", block_server=True)
agent_runner = load_module("test_v2_agent_runner", ROOT / "services" / "agent_runner" / "app.py")


class V2ContractTests(unittest.TestCase):
    def test_environment_contract_is_stable_and_fault_sensitive(self):
        config = {"budget": 123, "flights": [{"id": "A"}], "faults": [{"type": "force_error", "step_id": 1}]}
        first = environment_contract(env_config=config, seed=7, run_id="r", episode_id="ep")
        second = environment_contract(env_config=config, seed=7, run_id="r", episode_id="ep")
        changed = environment_contract(env_config={**config, "faults": []}, seed=7, run_id="r", episode_id="ep")
        self.assertEqual(first, second)
        self.assertNotEqual(first["fault_schedule_fingerprint"], changed["fault_schedule_fingerprint"])
        self.assertEqual(first["source_run_id"], "r")

    def test_strict_replay_fails_closed_without_matching_contract(self):
        source = environment_contract(env_config={"faults": []}, seed=3, run_id="source", episode_id="episode")
        result = counterfactual.replay([], {"tool": "search_flights", "arguments": {}}, run_id="source", source_seed=3, source_contract=source, replay_contract=None, strict_replay=True)
        self.assertFalse(result["evaluation"]["replay_valid"])
        self.assertEqual(result["evaluation"]["replay_failure_reason"], "missing_replay_contract")

    def test_strict_replay_passes_verified_provenance(self):
        source = environment_contract(env_config={"budget": 100, "faults": []}, seed=3, run_id="source", episode_id="episode")
        responses = [{"state": {}}, {"ok": True}, {"success": True, "side_effect": False}]
        with patch.object(counterfactual, "call", side_effect=responses) as mocked:
            result = counterfactual.replay([], {"tool": "search_flights", "arguments": {}}, run_id="source", source_seed=3, env_config={"budget": 100}, source_contract=source, replay_contract=expected_clean_replay_contract(source, "source:cf"), strict_replay=True)
        self.assertTrue(result["evaluation"]["replay_valid"])
        self.assertEqual(result["source_run_id"], "source")
        self.assertEqual(mocked.call_args_list[0].args[1]["env_config"]["faults"], [])

    def test_runner_sends_complete_strict_replay_provenance(self):
        calls = []
        patch_action = {"tool": "search_flights", "arguments": {}}

        def fake_post(base, path, payload):
            calls.append((base, path, payload))
            if path == "/reset":
                return {"state": {}}
            if path == "/step":
                return {"requested_action": patch_action, "action": patch_action, "result": {"ok": False}, "observation": {}}
            if path == "/diagnose":
                return {"candidates": [{"cause": "rate_limit", "confidence": 0.9, "step_id": 0, "evidence": patch_action}]}
            if path == "/choose":
                return {"baseline_id": "recovery", "decision": "retry", "step_id": 0, "patch": patch_action}
            if base == agent_runner.REPLAYER_URL and path == "/replay":
                return {"trace": [], "evaluation": {"success": True, "replay_valid": True}}
            raise AssertionError((base, path, payload))

        with patch.object(agent_runner, "post", side_effect=fake_post), patch.object(
            agent_runner, "get", return_value={"success": False}
        ):
            result = agent_runner.run_task({
                "protocol_id": "racer-v2-benchmark-protocol-0.1",
                "task_id": "strict",
                "run_id": "strict-run",
                "episode_id": "episode-1",
                "trial_id": 0,
                "model_resource_id": "offline-fixture",
                "strict_replay": True,
                "actions": [patch_action],
            })
        replay_payload = next(payload for base, path, payload in calls if base == agent_runner.REPLAYER_URL and path == "/replay")
        self.assertTrue(replay_payload["strict_replay"])
        self.assertEqual(replay_payload["episode_id"], "episode-1")
        self.assertEqual(replay_payload["source_contract"], result["environment_contract"])
        self.assertEqual(replay_payload["replay_contract"], expected_clean_replay_contract(result["environment_contract"], "strict-run:cf"))
        self.assertEqual(result["source_run_id"], "strict-run")
        self.assertEqual(result["protocol_id"], "racer-v2-benchmark-protocol-0.1")
        self.assertEqual(result["trial_id"], 0)
        self.assertEqual(result["model_resource_id"], "offline-fixture")

    def test_refund_response_loss_commits_once_and_retry_is_entity_idempotent(self):
        env = task_env.TaskEnv()
        env.reset({"enable_refund_ledger": True, "faults": [{"fault_id": "lost", "type": "response_loss", "step_id": 2, "tool": "refund_booking"}]})
        env.step({"tool": "select_flight", "arguments": {"flight_id": "F1"}})
        env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
        lost = env.step({"tool": "refund_booking", "arguments": {"refund_entity_id": "refund-A"}})
        retry = env.step({"tool": "refund_booking", "arguments": {"refund_entity_id": "refund-A"}})
        other = env.step({"tool": "refund_booking", "arguments": {"refund_entity_id": "refund-B"}})
        self.assertFalse(lost["result"]["ok"])
        self.assertEqual(lost["result"]["reconcile_with"], "get_refund_status")
        self.assertTrue(retry["result"]["idempotent_replay"])
        self.assertEqual(retry["result"]["ledger_entry_count"], 1)
        self.assertEqual(other["result"]["ledger_entry_count"], 2)
        self.assertTrue(adapter.validate_refund_witness(retry["result"], refund_entity="refund-A")["valid"])

    def test_adapter_rejects_unwitnessed_refund_success(self):
        class Fake:
            def observe(self):
                return {}

            def step(self, _action):
                return {"ok": True}

            def evaluate(self):
                return {}

        client = adapter.Tau2AirlineAdapter(environment_factory=lambda **kwargs: Fake(), task_loader=lambda _split: [{}])
        _, run_id = client.reset(0)
        with self.assertRaisesRegex(RuntimeError, "lacks verifiable witness"):
            client.step(run_id, "refund_booking", {"refund_entity_id": "r-1"})

    def test_shared_contract_is_copied_by_each_v2_service_image(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        expected = {
            "agent_runner": "services/agent_runner/Dockerfile",
            "counterfactual": "services/counterfactual/Dockerfile",
            "evaluator": "services/evaluator/Dockerfile",
        }
        for service, dockerfile in expected.items():
            self.assertIn(f"dockerfile: {dockerfile}", compose)
            contents = (ROOT / dockerfile).read_text(encoding="utf-8")
            self.assertIn("COPY services/common/environment_contract.py /app/common/environment_contract.py", contents)

    def test_canonical_results_deduplicates_only_complete_pairing(self):
        contract = environment_contract(env_config={"faults": []}, seed=1, run_id="source", episode_id="episode")
        item = {"task_id": "t", "run_id": "source", "source_run_id": "source", "episode_id": "episode", "environment_contract": contract, "original_evaluation": {"success": False}, "baselines": {"recovery": {"decision": {"decision": "abstain"}}}}
        row = evaluator.evaluate_file(self._write(item))
        row["baseline_id"] = "recovery"
        row["trial_id"] = 0
        row["model_resource_id"] = "offline-fixture"
        row["baselines"] = {}
        envelope = evaluator.canonical_results_envelope({"entries": [row, dict(row), {"run_id": "legacy"}]})
        self.assertEqual(envelope["count"], 2)
        self.assertEqual(envelope["deduplication"]["dropped_count"], 1)
        self.assertEqual(envelope["deduplication"]["legacy_rows_retained"], 1)
        self.assertEqual(envelope["deduplication"]["strategy"], "complete_paired_identity_plus_baseline_trial_model")
        analysis_row = dict(row)
        analysis_row["baselines"] = {"recovery": {"decision": "abstain", "original_success": False}}
        analyzed = analyze.analyze_payloads({"records": [analysis_row, dict(analysis_row)]}, {})
        self.assertEqual(analyzed["paired_deduplication"]["dropped_duplicate_rows"], 1)

    def _write(self, payload):
        import json
        import tempfile

        file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        self.addCleanup(lambda: Path(file.name).unlink(missing_ok=True))
        json.dump(payload, file)
        file.close()
        return file.name


if __name__ == "__main__":
    unittest.main()
