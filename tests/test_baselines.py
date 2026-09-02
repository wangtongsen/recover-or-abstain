import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "services" / "recovery_policy" / "app.py"
SPEC = importlib.util.spec_from_file_location("test_recovery_policy_baselines", SOURCE)
recovery_policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = recovery_policy
SPEC.loader.exec_module(recovery_policy)


class RecoveryBaselineTests(unittest.TestCase):
    def test_raw_decision_always_abstains_without_patch(self):
        diagnosis = {
            "candidates": [{"cause": "selected_non_refundable_flight", "confidence": 0.99}]
        }

        decision = recovery_policy.raw_decision(diagnosis)

        self.assertEqual(decision["baseline_id"], "raw")
        self.assertEqual(decision["decision"], "abstain")
        self.assertIsNone(decision["patch"])
        self.assertIn("reason", decision)

    def test_oracle_decision_uses_explicit_fault_replacement(self):
        patch = {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
        fault_truth = [{"fault_id": "replace-select", "type": "replace_action", "step_id": 1, "replacement": patch}]

        decision = recovery_policy.oracle_decision({}, fault_truth)

        self.assertEqual(decision["baseline_id"], "oracle")
        self.assertEqual(decision["decision"], "oracle_repair")
        self.assertEqual(decision["patch"], patch)
        self.assertEqual(decision["step_id"], 1)
        self.assertIsNot(decision["patch"], patch)

    def test_oracle_decision_abstains_without_usable_patch(self):
        fault_truth = [
            {"fault_id": "rate-limit", "type": "rate_limit", "step_id": 0},
            {"fault_id": "bad-patch", "patch": {"arguments": {"flight_id": "F1"}}},
        ]

        decision = recovery_policy.oracle_decision({}, fault_truth)

        self.assertEqual(decision["baseline_id"], "oracle")
        self.assertEqual(decision["decision"], "abstain")
        self.assertIsNone(decision["patch"])

    def test_recovery_decision_reuses_choose(self):
        diagnosis = {
            "candidates": [{
                "cause": "selected_non_refundable_flight",
                "confidence": 0.89,
                "step_id": 1,
                "repair_options": ["replace_argument", "replan"],
            }]
        }

        decision = recovery_policy.recovery_decision(diagnosis)
        expected = recovery_policy.choose(diagnosis)
        expected["baseline_id"] = "recovery"
        self.assertEqual(decision, expected)
        self.assertEqual(decision["baseline_id"], "recovery")

        decision = recovery_policy.recovery_decision(diagnosis, allow_abstain=False)
        expected = recovery_policy.choose(diagnosis, allow_abstain=False)
        expected["baseline_id"] = "recovery"
        self.assertEqual(decision, expected)


if __name__ == "__main__":
    unittest.main()
