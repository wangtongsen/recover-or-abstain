import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class _NoopHTTPServer:
    def __init__(self, *_args, **_kwargs):
        pass

    def serve_forever(self):
        pass


def load_task_env():
    import http.server

    source = ROOT / "services" / "task_env" / "app.py"
    with patch.object(http.server, "HTTPServer", _NoopHTTPServer):
        spec = importlib.util.spec_from_file_location("test_task_env_faults", source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


task_env = load_task_env()


class TaskEnvFaultTests(unittest.TestCase):
    def test_seed_is_exposed_and_state_is_reproducible(self):
        first = task_env.TaskEnv(seed=7)
        second = task_env.TaskEnv(seed=7)
        self.assertEqual(first.observe()["seed"], 7)
        self.assertEqual(first.observe()["state_hash"], second.observe()["state_hash"])

    def test_public_observation_hides_truth_but_internal_access_keeps_it(self):
        env = task_env.TaskEnv(seed=3)
        env.reset({"seed": 3, "faults": [{"type": "force_error", "fault_id": "hidden", "step_id": 0}]})
        public_observation = env.observe()
        self.assertNotIn("fault_truth", public_observation)
        self.assertNotIn("faults_applied", public_observation)
        self.assertNotIn("run_id", public_observation)
        self.assertNotIn("env_seed", public_observation)
        self.assertIn("fault_truth", env.observe(include_truth=True))
        self.assertIn("faults_applied", env.observe(include_truth=True))
        public_evaluation = env.evaluate()
        self.assertNotIn("fault_truth", public_evaluation)
        self.assertNotIn("required_flight_id", public_evaluation)
        self.assertNotIn("fault_id", public_evaluation)
        self.assertIn("fault_truth", env.evaluate(include_truth=True))
        self.assertIn("faults_applied", env.evaluate(include_truth=True))

    def test_fault_injection_records_fault_metadata(self):
        env = task_env.TaskEnv(seed=11)
        env.reset({"seed": 11, "faults": [{"type": "force_error", "fault_id": "rate_limit", "step_id": 0, "error": "rate limit", "status_code": 429}]})
        step = env.step({"tool": "search_flights", "arguments": {}})
        self.assertFalse(step["result"]["ok"])
        self.assertNotIn("fault", step)
        self.assertNotIn("fault_truth", step["observation"])
        self.assertEqual(env.evaluate(include_truth=True)["faults_applied"][0]["fault_id"], "rate_limit")

    def test_reset_applies_custom_environment_configuration(self):
        env = task_env.TaskEnv()
        flights = [
            {"id": "CUSTOM", "price": 123, "refundable": True},
            {"id": "OVER", "price": 999, "refundable": True},
        ]
        invariants = ["custom invariant"]
        observation = env.reset({
            "seed": 9,
            "env_config": {
                "budget": 200,
                "flights": flights,
                "task_variant": "clean_success",
                "variant": "clean_success",
                "actions": [{"tool": "search_flights", "arguments": {}}],
                "invariants": invariants,
                "faults": [],
            },
        })
        self.assertEqual(observation["state"]["budget"], 200)
        self.assertEqual(observation["env_config"]["flights"], flights)
        self.assertEqual(observation["actions"], [{"tool": "search_flights", "arguments": {}}])
        self.assertEqual(observation["invariants"], invariants)
        self.assertEqual(env.search_flights({})["flights"], flights)

    def test_fault_step_limits_injection_location(self):
        env = task_env.TaskEnv(seed=3)
        env.reset({"seed": 3, "faults": [{"type": "force_error", "fault_id": "wrong_tool", "step_id": 1, "error": "wrong tool"}]})
        first = env.step({"tool": "search_flights", "arguments": {}})
        second = env.step({"tool": "search_flights", "arguments": {}})
        self.assertTrue(first["result"].get("flights"))
        self.assertFalse(second["result"]["ok"])
        self.assertNotIn("fault", second)
        self.assertEqual(env.evaluate(include_truth=True)["faults_applied"][0]["fault_id"], "wrong_tool")


if __name__ == "__main__":
    unittest.main()
