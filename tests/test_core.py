import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import call as mock_call, patch as mock_patch


ROOT = Path(__file__).resolve().parents[1]


class _NoopHTTPServer:
    def __init__(self, *_args, **_kwargs):
        pass

    def serve_forever(self):
        pass


def load_service_module(module_name, service_name):
    """加载服务模块，同时屏蔽其导入时启动 HTTP server 的副作用。"""
    import http.server

    source = ROOT / "services" / service_name / "app.py"
    original_server = http.server.HTTPServer
    http.server.HTTPServer = _NoopHTTPServer
    try:
        spec = importlib.util.spec_from_file_location(module_name, source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        http.server.HTTPServer = original_server


task_env = load_service_module("test_task_env_app", "task_env")
diagnoser = load_service_module("test_diagnoser_app", "diagnoser")
recovery_policy = load_service_module("test_recovery_policy_app", "recovery_policy")
counterfactual = load_service_module("test_counterfactual_app", "counterfactual")


class CoreBehaviorTests(unittest.TestCase):
    def test_task_env_f1_is_successful_and_optimal(self):
        env = task_env.TaskEnv()
        env.step({"tool": "select_flight", "arguments": {"flight_id": "F1"}})
        env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})

        evaluation = env.evaluate()
        self.assertTrue(evaluation["success"])
        self.assertTrue(evaluation["optimal_selection"])

    def test_task_env_f3_is_not_successful_or_optimal(self):
        env = task_env.TaskEnv()
        env.step({"tool": "select_flight", "arguments": {"flight_id": "F3"}})
        env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})

        evaluation = env.evaluate()
        self.assertFalse(evaluation["success"])
        self.assertFalse(evaluation["optimal_selection"])

    def test_task_env_replace_action_fault_is_reproducible(self):
        fault = {
            "fault_id": "replace-select",
            "type": "replace_action",
            "step_id": 0,
            "replacement": {"tool": "select_flight", "arguments": {"flight_id": "F1"}},
        }
        env = task_env.TaskEnv()
        reset = env.reset({"seed": 7, "faults": [fault]})
        self.assertEqual(reset["seed"], 7)
        step = env.step({"tool": "search_flights", "arguments": {}})
        self.assertEqual(step["action"]["tool"], "select_flight")
        self.assertEqual(step["result"]["selected"]["id"], "F1")
        self.assertEqual(env.evaluate(include_truth=True)["faults_applied"][0]["fault_id"], "replace-select")

    def test_task_env_force_error_fault(self):
        env = task_env.TaskEnv()
        env.reset({"faults": [{"type": "force_error", "step_id": 0, "error": "boom"}]})
        step = env.step({"tool": "search_flights", "arguments": {}})
        self.assertFalse(step["result"]["ok"])
        self.assertEqual(step["result"]["error"], "boom")

    def test_diagnoser_deduplicates_f2_failure_and_keeps_selection_step(self):
        trace = [
            {
                "action": {"tool": "search_flights", "arguments": {}},
                "result": {"ok": True},
            },
            {
                "action": {"tool": "select_flight", "arguments": {"flight_id": "F2"}},
                "result": {"ok": True},
            },
            {
                "action": {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
                "result": {"ok": False, "error": "selected flight violates task constraints"},
            },
        ]

        diagnosis = diagnoser.diagnose(trace)
        self.assertEqual(len(diagnosis["candidates"]), 1)
        candidate = diagnosis["candidates"][0]
        self.assertEqual(candidate["cause"], "selected_non_refundable_flight")
        self.assertEqual(candidate["step_id"], 1)

    def test_diagnoser_detects_effective_tool_mismatch_without_fault_truth(self):
        trace = [{
            "requested_action": {"tool": "search_flights", "arguments": {"query": "A-B"}},
            "action": {"tool": "unknown_tool", "arguments": {}},
            "result": {"ok": False, "error": "unknown tool"},
        }]

        diagnosis = diagnoser.diagnose(trace)

        self.assertEqual(diagnosis["candidates"][0]["cause"], "effective_tool_mismatch")
        candidate = diagnosis["candidates"][0]
        self.assertEqual(candidate["evidence"]["tool"], "search_flights")
        self.assertEqual(candidate["evidence"]["arguments"], {"query": "A-B"})
        self.assertNotIn("fault_truth", candidate["evidence"])

    def test_recovery_policy_retries_requested_action_from_tool_error_evidence(self):
        diagnosis = {
            "candidates": [{
                "cause": "rate_limit",
                "confidence": 0.71,
                "step_id": 0,
                "repair_options": ["retry", "abstain"],
                "evidence": {
                    "error": "rate limit",
                    "tool": "search_flights",
                    "arguments": {"query": "A-B"},
                },
            }]
        }

        decision = recovery_policy.choose(diagnosis)

        self.assertEqual(decision["decision"], "retry")
        self.assertEqual(decision["patch"], {
            "tool": "search_flights",
            "arguments": {"query": "A-B"},
        })

    def test_force_error_and_rate_limit_patches_are_derived_from_public_requested_action(self):
        for fault in (
            {"type": "force_error", "error": "boom"},
            {"type": "rate_limit", "error": "rate limit"},
        ):
            env = task_env.TaskEnv()
            env.reset({"faults": [fault]})
            requested = {"tool": "search_flights", "arguments": {"query": "A-B"}}
            step = env.step(requested)
            self.assertFalse(step["result"]["ok"])
            self.assertNotIn("fault_truth", step)
            self.assertNotIn("faults_applied", step)

            diagnosis = diagnoser.diagnose([step])
            decision = recovery_policy.choose(diagnosis)
            self.assertEqual(decision["decision"], "retry")
            self.assertEqual(decision["patch"], requested)

    def test_public_trace_keeps_requested_and_effective_actions_without_truth(self):
        env = task_env.TaskEnv()
        env.reset({"faults": [{"type": "wrong_tool", "step_id": 0}]})
        requested = {"tool": "search_flights", "arguments": {}}
        step = env.step(requested)

        self.assertEqual(step["requested_action"], requested)
        self.assertNotEqual(step["action"], requested)
        self.assertEqual(step["action"]["tool"], "unknown_tool")
        self.assertNotIn("fault_truth", step)
        self.assertNotIn("faults_applied", step)

    def test_recovery_policy_does_not_patch_tool_error_without_action_evidence(self):
        diagnosis = {
            "candidates": [{
                "cause": "tool_execution_failed",
                "confidence": 0.71,
                "repair_options": ["retry", "abstain"],
            }]
        }

        decision = recovery_policy.choose(diagnosis)

        self.assertEqual(decision["decision"], "retry")
        self.assertIsNone(decision["patch"])

    def test_recovery_policy_abstains_on_low_confidence(self):
        diagnosis = {
            "candidates": [
                {
                    "cause": "selected_non_refundable_flight",
                    "confidence": 0.4,
                    "repair_options": ["replace_argument"],
                }
            ]
        }

        decision = recovery_policy.choose(diagnosis)
        self.assertEqual(decision["decision"], "abstain")

    def test_task_env_sessions_isolate_runs_and_counterfactual_replay(self):
        source_id = "core-source-session"
        other_id = "core-other-session"
        replay_id = f"{source_id}:cf"
        for run_id in (source_id, other_id, replay_id):
            task_env.sessions.pop(run_id, None)
        try:
            source = task_env._get_session(source_id, create=True)
            source.reset(
                {
                    "run_id": source_id,
                    "seed": 41,
                    "faults": [{"fault_id": "source-fault", "type": "force_error", "step_id": 0}],
                }
            )
            source_step = source.step({"tool": "search_flights", "arguments": {}})
            self.assertFalse(source_step["result"]["ok"])

            other = task_env._get_session(other_id, create=True)
            other.reset({"run_id": other_id, "seed": 99, "faults": []})
            other_step = other.step({"tool": "search_flights", "arguments": {}})
            self.assertTrue(other_step["result"].get("flights"))
            self.assertEqual(other.evaluate()["seed"], 99)
            self.assertNotIn("faults_applied", other.evaluate())
            self.assertEqual(other.evaluate(include_truth=True)["faults_applied"], [])

            replay = task_env._get_session(replay_id, create=True)
            replay.reset({"run_id": replay_id, "seed": 41, "faults": []})
            replay_step = replay.step({"tool": "search_flights", "arguments": {}})
            self.assertTrue(replay_step["result"].get("flights"))
            self.assertEqual(replay.evaluate()["run_id"], replay_id)
            self.assertEqual(replay.evaluate()["seed"], 41)
            self.assertNotIn("faults_applied", replay.evaluate())
            self.assertEqual(replay.evaluate(include_truth=True)["faults_applied"], [])

            # Resetting/stepping the replay session must not overwrite source state.
            self.assertEqual(source.evaluate()["run_id"], source_id)
            self.assertEqual(source.evaluate(include_truth=True)["faults_applied"][0]["fault_id"], "source-fault")
            self.assertFalse(source.evaluate()["success"])
        finally:
            for run_id in (source_id, other_id, replay_id):
                task_env.sessions.pop(run_id, None)

    def test_counterfactual_clean_replay_preserves_environment_configuration(self):
        with mock_patch.object(counterfactual, "call", return_value={}) as mocked_call:
            counterfactual.replay(
                [],
                None,
                [],
                run_id="source-config",
                source_seed=17,
                source_faults=[{"type": "force_error"}],
                env_config={
                    "budget": 123,
                    "flights": [{"id": "CUSTOM", "price": 99, "refundable": True}],
                    "task_variant": "clean_success",
                    "variant": "clean_success",
                    "actions": [{"tool": "search_flights", "arguments": {}}],
                    "invariants": ["custom invariant"],
                    "faults": [{"type": "force_error"}],
                },
            )
        reset = mocked_call.call_args_list[0].args[1]
        self.assertEqual(reset["budget"], 123)
        self.assertEqual(reset["flights"][0]["id"], "CUSTOM")
        self.assertEqual(reset["task_variant"], "clean_success")
        self.assertEqual(reset["actions"], [{"tool": "search_flights", "arguments": {}}])
        self.assertEqual(reset["invariants"], ["custom invariant"])
        self.assertEqual(reset["faults"], [])
        self.assertEqual(reset["env_config"]["faults"], [])

    def test_counterfactual_replay_orders_prefix_patch_suffix(self):
        prefix = [
            {"action": {"tool": "search_flights", "arguments": {}}},
            {"action": {"tool": "select_flight", "arguments": {"flight_id": "F2"}}},
        ]
        patch = {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
        suffix = [
            {"action": {"tool": "confirm_booking", "arguments": {"user_confirmed": True}}}
        ]

        with mock_patch.object(counterfactual, "call", return_value={}) as mocked_call:
            counterfactual.replay(
                prefix,
                patch,
                suffix,
                run_id="source",
                source_seed=17,
                source_faults=[{"type": "force_error", "step_id": 0}],
            )

        replay_run_id = "source:cf"
        self.assertEqual(
            mocked_call.call_args_list,
            [
                mock_call("/reset", {"run_id": replay_run_id, "seed": 17, "faults": [], "env_config": {"faults": []}}),
                mock_call("/step", {"run_id": replay_run_id, **prefix[0]["action"]}),
                mock_call("/step", {"run_id": replay_run_id, **prefix[1]["action"]}),
                mock_call("/step", {"run_id": replay_run_id, **patch}),
                mock_call("/step", {"run_id": replay_run_id, **suffix[0]["action"]}),
                mock_call("/evaluate?run_id=source%3Acf"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
