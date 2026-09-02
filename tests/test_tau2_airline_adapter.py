import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "adapters" / "tau2_airline_adapter.py"
SPEC = importlib.util.spec_from_file_location("tau2_airline_adapter", MODULE_PATH)
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


class FakeEnvironment:
    def __init__(self, task, seed):
        self.task = task
        self.seed = seed
        self.actions = []

    def observe(self):
        return {"task": self.task, "seed": self.seed, "tools": ["search_flights"]}

    def step(self, action):
        self.actions.append(action)
        return {"action": action, "ok": True}

    def evaluate(self):
        return {"reward": None, "success": None}


class Tau2AirlineAdapterTests(unittest.TestCase):
    def test_import_smoke_reports_locked_metadata_without_live_run(self):
        status = adapter.tau2_import_status()
        self.assertEqual(status["package"], "tau2")
        self.assertEqual(status["required_version"], "1.0.1")
        self.assertEqual(status["benchmark_commit"], "fc0055dc4e0a316c3f83133267fbd6faaa770992")
        self.assertFalse(status["live_benchmark_executed"])

    def test_stable_task_id_uses_split_and_index(self):
        self.assertEqual(adapter.stable_task_id("base", "7"), "airline-base-7")
        with self.assertRaises(ValueError):
            adapter.stable_task_id("base", -1)

    def test_live_hooks_are_explicit_and_narrow(self):
        tasks = [{"id": "official-task-0"}]
        client = adapter.Tau2AirlineAdapter(
            environment_factory=lambda **kwargs: FakeEnvironment(**kwargs),
            task_loader=lambda split: tasks,
        )
        observation, run_id = client.reset(0, seed=13)
        self.assertEqual(run_id, "airline-base-0")
        self.assertEqual(observation["seed"], 13)
        self.assertEqual(client.step(run_id, "search_flights", {"origin": "A"})["ok"], True)
        self.assertEqual(client.evaluate(run_id), {"reward": None, "success": None})

    def test_offline_conversion_preserves_unknowns_as_none(self):
        converted = adapter.convert_offline_record(
            {
                "run_id": "offline-1",
                "seed": 4,
                "trace": [
                    {
                        "requested_action": {"tool": "search_flights", "arguments": {}},
                        "result": {"flights": []},
                        "state_before": {"turn": 0},
                        "state_after": {"turn": 1},
                    }
                ],
            },
            task_split="test",
            task_index=2,
        )
        self.assertEqual(converted["task_id"], "airline-test-2")
        self.assertEqual(converted["trace"][0]["state_hash_before"], adapter._state_hash({"turn": 0}))
        self.assertIsNone(converted["reward"])
        self.assertIsNone(converted["original_evaluation"])
        self.assertTrue(converted["offline"])
        self.assertFalse(converted["live_benchmark_executed"])

    def test_live_use_without_hooks_is_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "explicit environment_factory"):
            adapter.Tau2AirlineAdapter().reset(0)


if __name__ == "__main__":
    unittest.main()
