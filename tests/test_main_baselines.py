import importlib.util
import json
import sys
import unittest
from pathlib import Path

_SERVICE_DIR = Path(__file__).resolve().parents[1] / "services" / "recovery_policy"
_SPEC = importlib.util.spec_from_file_location("recovery_policy_app", _SERVICE_DIR / "app.py")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["recovery_policy_app"] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def _diagnosis(cause="injected force_error_confirm", confidence=0.71, step_id=1, tool="confirm_booking", arguments=None):
    return {
        "candidates": [
            {
                "step_id": step_id,
                "category": "action_error",
                "cause": cause,
                "confidence": confidence,
                "repair_options": ["retry", "abstain"],
                "evidence": {"error": "injected force_error_confirm", "tool": tool, "arguments": arguments or {"user_confirmed": True}},
                "source": "tool_result",
            }
        ],
        "diagnosis_confidence": confidence,
    }


FORCE_ERROR_DIAGNOSIS = _diagnosis()
WEAK_DIAGNOSIS = _diagnosis(confidence=0.30)
NO_CANDIDATES = {"candidates": [], "diagnosis_confidence": 0.0}
FAULT_TRUTH = [
    {
        "fault_id": "force-error-confirm",
        "type": "force_error",
        "step_id": 1,
        "tool": "confirm_booking",
        "error": "injected force_error_confirm",
        "patch": {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
    }
]


class MainBaselineContractTest(unittest.TestCase):
    """Every main baseline returns the shared decision contract shape."""

    MAIN_IDS = [
        "raw_react", "fixed_retry", "exponential_backoff", "generic_reflection",
        "full_trace_judge", "step_by_step_diagnosis", "binary_search_diagnosis",
        "agentdebug_targeted_feedback", "always_recover", "racer",
        "racer_no_abstain", "racer_no_counterfactual",
        "oracle_root_cause", "oracle_recovery",
    ]

    def test_all_fourteen_ids_dispatch(self):
        for baseline_id in self.MAIN_IDS:
            payload = {"diagnosis": FORCE_ERROR_DIAGNOSIS, "fault_truth": FAULT_TRUTH}
            decision = _MODULE.baseline_dispatch(baseline_id, payload)
            self.assertIsNotNone(decision, f"{baseline_id} must dispatch")
            self.assertEqual(decision["baseline_id"], baseline_id)
            for field in ("decision", "patch", "reason"):
                self.assertIn(field, decision, f"{baseline_id} decision must carry {field}")

    def test_unknown_baseline_id_fails_closed(self):
        self.assertIsNone(_MODULE.baseline_dispatch("nonexistent_baseline", {"diagnosis": FORCE_ERROR_DIAGNOSIS}))
        self.assertIsNone(_MODULE.baseline_dispatch("racer_typo", {"diagnosis": FORCE_ERROR_DIAGNOSIS}))

    def test_pilot_ids_still_supported(self):
        for pilot_id in ("raw", "recovery", "oracle"):
            decision = _MODULE.baseline_dispatch(pilot_id, {"diagnosis": FORCE_ERROR_DIAGNOSIS, "fault_truth": FAULT_TRUTH})
            self.assertIsNotNone(decision)


class RetryFamilyTest(unittest.TestCase):

    def test_fixed_retry_blind_retry_with_policy_fields(self):
        decision = _MODULE.fixed_retry_decision(FORCE_ERROR_DIAGNOSIS)
        self.assertEqual(decision["decision"], "retry")
        self.assertEqual(decision["patch"], {"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
        self.assertEqual(decision["retry_policy"], "fixed")
        self.assertEqual(decision["max_retries"], 1)

    def test_exponential_backoff_carries_schedule(self):
        decision = _MODULE.exponential_backoff_decision(FORCE_ERROR_DIAGNOSIS)
        self.assertEqual(decision["decision"], "retry")
        self.assertEqual(decision["retry_policy"], "exponential_backoff")
        self.assertEqual(decision["backoff_schedule_s"], [1, 2])

    def test_fixed_retry_abstains_without_evidence(self):
        decision = _MODULE.fixed_retry_decision(NO_CANDIDATES)
        self.assertEqual(decision["decision"], "abstain")
        self.assertIsNone(decision["patch"])


class ReflectionFamilyTest(unittest.TestCase):

    def test_generic_reflection_acts_on_confident_diagnosis(self):
        decision = _MODULE.generic_reflection_decision(FORCE_ERROR_DIAGNOSIS)
        self.assertEqual(decision["decision"], "retry")
        self.assertIsNotNone(decision["patch"])

    def test_generic_reflection_abstains_on_weak_confidence(self):
        decision = _MODULE.generic_reflection_decision(WEAK_DIAGNOSIS)
        self.assertEqual(decision["decision"], "abstain")
        self.assertIsNone(decision["patch"])

    def test_full_trace_judge_needs_corroboration(self):
        decision = _MODULE.full_trace_judge_decision(FORCE_ERROR_DIAGNOSIS)
        # Single candidate at 0.71 lacks corroboration (<2 candidates, <0.85).
        self.assertEqual(decision["decision"], "abstain")

    def test_full_trace_judge_acts_with_corroboration(self):
        diagnosis = _diagnosis()
        diagnosis["candidates"].append({
            "step_id": 1, "category": "action_error", "cause": "duplicate_signal",
            "confidence": 0.6, "repair_options": ["retry"], "evidence": {"error": "x"},
        })
        decision = _MODULE.full_trace_judge_decision(diagnosis)
        self.assertEqual(decision["decision"], "retry")

    def test_full_trace_judge_acts_on_single_high_confidence(self):
        diagnosis = _diagnosis(confidence=0.9)
        decision = _MODULE.full_trace_judge_decision(diagnosis)
        self.assertEqual(decision["decision"], "retry")


class ScanFamilyTest(unittest.TestCase):

    def test_step_by_step_prefers_earliest_step(self):
        diagnosis = _diagnosis(step_id=2)
        diagnosis["candidates"].insert(0, {
            "step_id": 0, "category": "action_error", "cause": "early_failure",
            "confidence": 0.6, "repair_options": ["retry"],
            "evidence": {"tool": "search_flights", "arguments": {}},
        })
        decision = _MODULE.step_by_step_diagnosis_decision(diagnosis)
        self.assertEqual(decision["decision"], "retry")
        self.assertEqual(decision["step_id"], 0)
        self.assertEqual(decision["patch"]["tool"], "search_flights")

    def test_binary_search_picks_midpoint(self):
        diagnosis = {"candidates": [], "diagnosis_confidence": 0}
        for step in range(3):
            diagnosis["candidates"].append({
                "step_id": step, "category": "action_error", "cause": f"cause_{step}",
                "confidence": 0.7, "repair_options": ["retry"],
                "evidence": {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
            })
        decision = _MODULE.binary_search_diagnosis_decision(diagnosis)
        # ordered [0,1,2]; midpoint index 1 -> step 1
        self.assertEqual(decision["step_id"], 1)
        self.assertEqual(decision["scan"], "binary_search")

    def test_agentdebug_uses_targeted_feedback(self):
        decision = _MODULE.agentdebug_targeted_feedback_decision(FORCE_ERROR_DIAGNOSIS)
        self.assertEqual(decision["decision"], "retry")
        self.assertTrue(decision["targeted"])
        self.assertEqual(decision["feedback_source"], "top_candidate_evidence")


class AblationFamilyTest(unittest.TestCase):

    def test_always_recover_ignores_confidence_gate(self):
        decision = _MODULE.always_recover_decision(WEAK_DIAGNOSIS)
        # Forced recovery: weak confidence still retries when evidence exists.
        self.assertEqual(decision["decision"], "retry")
        self.assertIs(decision.get("allow_abstain"), False)

    def test_racer_full_method_acts_on_confident_diagnosis(self):
        decision = _MODULE.racer_decision(FORCE_ERROR_DIAGNOSIS)
        self.assertEqual(decision["decision"], "retry")
        self.assertIsNotNone(decision["patch"])
        self.assertTrue(decision["use_counterfactual"])
        self.assertIsNotNone(decision["expected_utility"])

    def test_racer_abstains_on_weak_confidence(self):
        decision = _MODULE.racer_decision(WEAK_DIAGNOSIS)
        self.assertEqual(decision["decision"], "abstain")

    def test_racer_no_abstain_acts_despite_weak_confidence(self):
        decision = _MODULE.racer_no_abstain_decision(WEAK_DIAGNOSIS)
        self.assertEqual(decision["decision"], "retry")
        self.assertEqual(decision["ablation"], "no_abstain")

    def test_racer_no_counterfactual_sets_skip_flag(self):
        decision = _MODULE.racer_no_counterfactual_decision(FORCE_ERROR_DIAGNOSIS)
        self.assertEqual(decision["decision"], "retry")
        self.assertIs(decision["skip_counterfactual"], True)
        self.assertEqual(decision["ablation"], "no_counterfactual")
        self.assertFalse(decision["use_counterfactual"])


class OracleFamilyTest(unittest.TestCase):

    def test_oracle_root_cause_uses_truth_step_with_public_patch(self):
        decision = _MODULE.oracle_root_cause_decision(FORCE_ERROR_DIAGNOSIS, FAULT_TRUTH)
        self.assertEqual(decision["decision"], "oracle_repair")
        self.assertEqual(decision["step_id"], 1)
        self.assertEqual(decision["patch"]["tool"], "confirm_booking")
        self.assertEqual(decision["confidence"], 1.0)

    def test_oracle_root_cause_abstains_without_truth(self):
        decision = _MODULE.oracle_root_cause_decision(FORCE_ERROR_DIAGNOSIS, [])
        self.assertEqual(decision["decision"], "abstain")

    def test_oracle_recovery_uses_explicit_patch(self):
        decision = _MODULE.oracle_recovery_decision(FORCE_ERROR_DIAGNOSIS, FAULT_TRUTH)
        self.assertEqual(decision["baseline_id"], "oracle_recovery")
        self.assertEqual(decision["decision"], "oracle_repair")
        self.assertEqual(decision["patch"]["arguments"], {"user_confirmed": True})

    def test_raw_react_never_repairs(self):
        decision = _MODULE.raw_react_decision(FORCE_ERROR_DIAGNOSIS)
        self.assertEqual(decision["decision"], "abstain")
        self.assertIsNone(decision["patch"])


class BatchEndpointTest(unittest.TestCase):

    def test_baselines_endpoint_returns_all_decisions(self):
        # Simulated handler logic without HTTP.
        payload = {"baselines": [
            {"baseline_id": bid, "diagnosis": FORCE_ERROR_DIAGNOSIS, "fault_truth": FAULT_TRUTH}
            for bid in MainBaselineContractTest.MAIN_IDS
        ]}
        results = {}
        for entry in payload["baselines"]:
            decision = _MODULE.baseline_dispatch(entry["baseline_id"], entry)
            if decision is not None:
                results[entry["baseline_id"]] = decision
        self.assertEqual(len(results), 14)


if __name__ == "__main__":
    unittest.main()
