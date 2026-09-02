import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("analyze_results", ROOT / "scripts" / "analyze_results.py")
analyze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyze)


class AnalyzeResultsTests(unittest.TestCase):
    def test_wilson_interval_handles_empty_and_bounds(self):
        self.assertIsNone(analyze.wilson_interval(0, 0))
        interval = analyze.wilson_interval(3, 3)
        self.assertEqual(interval["successes"], 3)
        self.assertEqual(interval["n"], 3)
        self.assertEqual(interval["upper"], 1.0)
        self.assertGreater(interval["lower"], 0.0)

    def test_group_metrics_and_failure_conditioned_recovery(self):
        evaluator_payload = {
            "experiment": "local-flight",
            "rows": [
                {
                    "task_id": "local-flight-drop_action-seed-0",
                    "run_id": "r0",
                    "seed": 0,
                    "original_success": False,
                    "diagnosis_confidence": 0.9,
                    "step_exact": True,
                    "latency_ms": 12,
                    "baselines": {
                        "recovery": {
                            "abstained": False,
                            "original_success": False,
                            "recovered_success": True,
                            "harmful_repair": False,
                        }
                    },
                },
                {
                    "task_id": "local-flight-drop_action-seed-1",
                    "run_id": "r1",
                    "seed": 1,
                    "original_success": False,
                    "diagnosis_confidence": 0.1,
                    "step_exact": False,
                    "baselines": {
                        "recovery": {
                            "abstained": True,
                            "original_success": False,
                            "recovered_success": False,
                            "harmful_repair": True,
                        }
                    },
                },
                {
                    "task_id": "local-flight-drop_action-seed-2",
                    "run_id": "r2",
                    "seed": 2,
                    "original_success": True,
                    "diagnosis_confidence": None,
                    "baselines": {
                        "recovery": {
                            "abstained": True,
                            "original_success": True,
                            "recovered_success": False,
                            "harmful_repair": False,
                        }
                    },
                },
            ],
        }
        result = analyze.analyze_payloads(evaluator_payload, {"trajectory_count": 3})
        metrics = result["groups"]["drop_action"]["recovery"]
        self.assertEqual(metrics["n"], 3)
        self.assertEqual(metrics["failures"], 2)
        self.assertEqual(metrics["failure_count"], 2)
        self.assertEqual(metrics["attempted_count"], 1)
        self.assertEqual(metrics["repair_attempted"], 1)
        self.assertEqual(metrics["recovered_count"], 1)
        self.assertEqual(metrics["harmful_count"], 1)
        self.assertEqual(metrics["abstain_count"], 2)
        self.assertEqual(metrics["recovery_rate"], 0.5)
        self.assertEqual(result["groups"]["drop_action"]["recovery"]["recovery_rate"], 0.5)

        # Wilson denominator is the number of original failures.
        self.assertEqual(metrics["recovery_rate_ci95"]["n"], metrics["failure_count"])
        self.assertEqual(metrics["recovery_rate_ci95"]["n"], 2)
        self.assertEqual(metrics["latency"]["available_count"], 1)
        self.assertEqual(metrics["latency"]["missing_count"], 2)
        self.assertEqual(metrics["latency"]["summary"]["mean_ms"], 12)
        self.assertEqual(metrics["repair_attempted"], 1)
        self.assertEqual(metrics["recovered"], 1)
        self.assertEqual(metrics["harmful"], 1)
        self.assertEqual(metrics["abstain"], 2)

        buckets = {entry["bucket"]: entry for entry in metrics["confidence_reliability"]}
        self.assertEqual(buckets["[0.0, 0.2)"]["n"], 1)
        self.assertEqual(buckets["[0.8, 1.0]"]["n"], 1)
        self.assertEqual(buckets["missing"]["n"], 1)

    def test_v2_recovery_claim_without_verified_replay_is_not_counted(self):
        result = analyze.analyze_payloads(
            {"records": [{
                "task_id": "local-flight-force_error-seed-0",
                "run_id": "r",
                "original_success": False,
                "main_comparison": True,
                "legacy": False,
                "baselines": {"racer": {
                    "recovered_success": True,
                    "strict_replay": True,
                    "counterfactual_supported": True,
                    "replay_valid": False,
                }},
            }]},
            {},
        )
        metrics = result["groups"]["force_error"]["racer"]
        self.assertEqual(metrics["recovered_count"], 0)
        self.assertEqual(metrics["recovery_rate"], 0.0)

    def test_analyzer_rejects_ambiguous_alias_containers(self):
        with self.assertRaisesRegex(ValueError, "ambiguous_results_containers"):
            analyze.analyze_payloads({"records": [], "entries": []}, {})

    def test_zero_latency_is_missing_not_a_measurement(self):
        result = analyze.analyze_payloads(
            {"rows": [{"task_id": "local-flight-force_error-seed-0", "run_id": "r", "latency_ms": 0, "baselines": {"raw": {"original_success": False, "abstained": True, "latency_ms": 0}}}]},
            {},
        )
        latency = result["groups"]["force_error"]["raw"]["latency"]
        self.assertEqual(latency["available_count"], 0)
        self.assertEqual(latency["missing_count"], 1)
        self.assertEqual(latency["availability_rate"], 0.0)
        self.assertIsNone(latency["summary"])

    def test_baseline_merge_keeps_trajectory_original_outcome(self):
        result = analyze.analyze_payloads(
            {
                "rows": [{
                    "task_id": "local-flight-force_error-seed-0",
                    "run_id": "r",
                    "original_success": False,
                    "baselines": {"recovery": {
                        "original_success": True,
                        "decision": "replace_argument",
                        "recovered_success": True,
                    }},
                }]
            },
            {},
        )
        metrics = result["groups"]["force_error"]["recovery"]
        self.assertEqual(metrics["failure_count"], 1)
        self.assertEqual(metrics["recovered_count"], 1)
        self.assertEqual(metrics["recovery_rate"], 1.0)
        self.assertEqual(metrics["repair_attempted"], 1)

    def test_non_repair_decision_is_not_counted_as_repair_attempt(self):
        result = analyze.analyze_payloads(
            {"rows": [{"task_id": "local-flight-force_error-seed-0", "run_id": "r", "original_success": False, "baselines": {"recovery": {"decision": "observe", "abstained": False}}}]},
            {},
        )
        metrics = result["groups"]["force_error"]["recovery"]
        self.assertEqual(metrics["repair_attempted"], 0)
        self.assertEqual(metrics["attempted_count"], 0)

    def test_write_outputs_are_json_and_csv(self):
        result = analyze.analyze_payloads(
            {"rows": [{"task_id": "local-flight-force_error-seed-0", "run_id": "r", "baselines": {"raw": {"original_success": False, "abstained": True}}}]},
            {},
        )
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "stats.json"
            csv_path = Path(directory) / "stats.csv"
            analyze.write_json(result, json_path)
            analyze.write_csv(result, csv_path)
            first_json = json_path.read_bytes()
            first_csv = csv_path.read_bytes()
            analyze.write_json(result, json_path)
            analyze.write_csv(result, csv_path)
            self.assertEqual(json.loads(json_path.read_text())["groups"]["force_error"]["raw"]["n"], 1)
            self.assertIn("recovery_rate_ci95", csv_path.read_text())
            self.assertEqual(json_path.read_bytes(), first_json)
            self.assertEqual(csv_path.read_bytes(), first_csv)
            self.assertNotIn(b"\r\n", first_csv)

    def test_seed_is_explicitly_not_iid_claim(self):
        result = analyze.analyze_payloads({"rows": []}, {})
        self.assertIn("非 iid", result["seed_note"])


if __name__ == "__main__":
    unittest.main()
