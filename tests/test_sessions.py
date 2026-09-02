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
        spec = importlib.util.spec_from_file_location("test_task_env_sessions", source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


task_env = load_task_env()


class TaskEnvSessionTests(unittest.TestCase):
    def setUp(self):
        task_env.sessions.clear()
        task_env.sessions["default"] = task_env.TaskEnv()

    def test_run_ids_are_isolated(self):
        first = task_env._get_session("run-a", create=True)
        second = task_env._get_session("run-b", create=True)
        first.reset({"run_id": "run-a", "seed": 1})
        second.reset({"run_id": "run-b", "seed": 2})
        first.step({"tool": "select_flight", "arguments": {"flight_id": "F1"}})

        self.assertEqual(first.evaluate()["run_id"], "run-a")
        self.assertEqual(second.evaluate()["run_id"], "run-b")
        self.assertEqual(first.observe()["state"]["selected_flight"]["id"], "F1")
        self.assertIsNone(second.observe()["state"]["selected_flight"])
        self.assertNotEqual(first.observe()["state_hash"], second.observe()["state_hash"])

    def test_default_session_remains_legacy(self):
        default = task_env._get_session(None)
        default.step({"tool": "select_flight", "arguments": {"flight_id": "F3"}})
        self.assertEqual(default.observe()["state"]["selected_flight"]["id"], "F3")
        self.assertIsNone(default.run_id)


if __name__ == "__main__":
    unittest.main()
