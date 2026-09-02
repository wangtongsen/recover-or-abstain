import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "test_evaluator_app", ROOT / "services" / "evaluator" / "app.py"
)
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


class EvaluatorTests(unittest.TestCase):
    def write_trajectory(self, payload):
        file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False)
        self.addCleanup(lambda: Path(file.name).unlink(missing_ok=True))
        json.dump(payload, file)
        file.close()
        return file.name

    def test_evaluate_file_extracts_extended_metrics(self):
        path = self.write_trajectory(
            {
                "task_id": "task-1",
                "run_id": "run-1",
                "seed": 7,
                "fault_truth": [{"cause": "selected_non_refundable_flight", "step_id": 1}],
                "trace": [{"latency_ms": 12}, {"timing": {"duration_ms": 8}}],
                "original_evaluation": {"success": False},
                "diagnosis": {
                    "diagnosis_confidence": 0.89,
                    "candidates": [
                        {"cause": "selected_non_refundable_flight", "step_id": 1, "confidence": 0.89},
                        {"cause": "other", "step_id": 0, "confidence": 0.2},
                    ],
                },
                "decision": {
                    "decision": "replace_argument",
                    "patch": {"tool": "select_flight", "arguments": {"flight_id": "F1"}},
                },
                "counterfactual": {"evaluation": {"success": True, "side_effect": False}},
            }
        )

        row = evaluator.evaluate_file(path)

        self.assertEqual(row["run_id"], "run-1")
        self.assertEqual(row["seed"], 7)
        self.assertFalse(row["abstained"])
        self.assertEqual(row["diagnosis_top1"], "selected_non_refundable_flight")
        self.assertTrue(row["step_exact"])
        self.assertEqual(row["repair_steps"], 1)
        self.assertEqual(row["latency_ms"], 20)
        self.assertEqual(row["decision"], "replace_argument")
        self.assertEqual(row["diagnosis_confidence"], 0.89)
        self.assertFalse(row["original_success"])
        self.assertTrue(row["recovered_success"])
        self.assertFalse(row["harmful_repair"])

    def test_evaluate_file_supports_legacy_shape_and_defaults(self):
        path = self.write_trajectory(
            {
                "task_id": "legacy",
                "original_evaluation": {"success": True},
                "diagnosis": {"candidates": []},
                "decision": {"decision": "abstain"},
                "counterfactual": None,
            }
        )

        row = evaluator.evaluate_file(path)

        self.assertEqual(row["task_id"], "legacy")
        self.assertIsNone(row["run_id"])
        self.assertIsNone(row["seed"])
        self.assertTrue(row["abstained"])
        self.assertIsNone(row["diagnosis_top1"])
        self.assertIsNone(row["step_exact"])
        self.assertEqual(row["repair_steps"], 0)
        self.assertEqual(row["latency_ms"], 0)
        self.assertFalse(row["recovered_success"])

    def test_evaluate_file_expands_baselines_without_overwriting_legacy_metrics(self):
        path = self.write_trajectory(
            {
                "task_id": "multi",
                "run_id": "run-multi",
                "fault_truth": [{"cause": "x", "step_id": 0}],
                "trace": [],
                "original_evaluation": {"success": False},
                "diagnosis": {"candidates": [{"cause": "x", "step_id": 0, "confidence": 0.8}]},
                "decision": {"baseline_id": "recovery", "decision": "replace_argument", "patch": {"tool": "x"}},
                "counterfactual": {"evaluation": {"success": True}},
                "baselines": {
                    "raw": {"decision": {"baseline_id": "raw", "decision": "abstain", "patch": None}, "counterfactual": None},
                    "recovery": {"decision": {"baseline_id": "recovery", "decision": "replace_argument", "patch": {"tool": "x"}}, "counterfactual": {"evaluation": {"success": True}}},
                    "oracle": {"decision": {"baseline_id": "oracle", "decision": "oracle_repair", "patch": {"tool": "x"}}, "counterfactual": {"evaluation": {"success": False, "side_effect": True}}},
                },
            }
        )
        row = evaluator.evaluate_file(path)
        self.assertEqual(row["decision"], "replace_argument")
        self.assertTrue(row["recovered_success"])
        self.assertEqual(set(row["baselines"]), {"raw", "recovery", "oracle"})
        self.assertFalse(row["baselines"]["raw"]["recovered_success"])
        self.assertTrue(row["baselines"]["recovery"]["recovered_success"])
        self.assertTrue(row["baselines"]["oracle"]["harmful_repair"])
        self.assertEqual(row["baselines"]["oracle"]["baseline_id"], "oracle")

    def test_evaluate_file_propagates_admission_metadata_and_public_refund_evidence(self):
        contract = {
            "episode_id": "episode-1",
            "source_run_id": "source-1",
            "env_seed": 3,
            "initial_state_fingerprint": "initial",
            "fault_schedule_fingerprint": "faults",
        }
        path = self.write_trajectory({
            "protocol_id": "racer-v2-benchmark-protocol-0.1",
            "task_id": "refund-task",
            "run_id": "source-1",
            "source_run_id": "source-1",
            "episode_id": "episode-1",
            "trial_id": 0,
            "model_resource_id": "offline-fixture",
            "source_manifest_sha256": "a" * 64,
            "strict_replay": True,
            "environment_contract": contract,
            "original_evaluation": {"success": False},
            "trace": [{"result": {"response_loss": True, "refund_entity_id": "refund-1"}}],
            "baselines": {
                "racer": {
                    "decision": {"decision": "retry"},
                    "counterfactual": {
                        "replay_provenance": {"strict": True},
                        "evaluation": {"success": True, "counterfactual_supported": True, "replay_valid": True},
                        "trace": [{"result": {
                            "refund_entity_id": "refund-1",
                            "ledger_witness": "witness",
                            "ledger_entry_count": 1,
                            "refund_witness_valid": True,
                            "reconciled": True,
                        }}],
                    },
                }
            },
        })
        row = evaluator.evaluate_file(path)
        baseline = row["baselines"]["racer"]
        self.assertEqual(baseline["protocol_id"], "racer-v2-benchmark-protocol-0.1")
        self.assertEqual(baseline["trial_id"], 0)
        self.assertEqual(baseline["model_resource_id"], "offline-fixture")
        self.assertTrue(baseline["strict_replay"])
        self.assertTrue(baseline["counterfactual_supported"])
        self.assertTrue(baseline["replay_valid"])
        self.assertTrue(baseline["response_loss"])
        self.assertTrue(baseline["reconciled"])
        self.assertEqual(baseline["ledger_witness"], "witness")

    def test_canonical_envelope_rejects_ambiguous_alias_containers(self):
        with self.assertRaisesRegex(ValueError, "ambiguous_results_containers"):
            evaluator.canonical_results_envelope({"records": [], "entries": []})

    def test_canonical_envelope_expands_baselines_and_preserves_trials(self):
        source = {
            "paired_identity": ["episode", "source", "task", "0", "initial", "faults"],
            "paired_identity_complete": True,
            "trial_id": 0,
            "model_resource_id": "offline-fixture",
            "baselines": {
                "raw": {"recovered_success": False},
                "racer": {"recovered_success": True, "strict_replay": True},
            },
        }
        envelope = evaluator.canonical_results_envelope({"results": [source]})
        self.assertEqual(envelope["count"], 2)
        self.assertEqual({row["baseline_id"] for row in envelope["records"]}, {"raw", "racer"})
        self.assertTrue(all(row["trial_id"] == 0 for row in envelope["records"]))

    def test_summarize_baselines_groups_rows_by_baseline_id(self):
        rows = [
            {"original_success": False, "recovered_success": True, "harmful_repair": False, "abstained": False,
             "baselines": {"raw": {"original_success": False, "recovered_success": False, "harmful_repair": False, "abstained": True}}},
            {"original_success": True, "recovered_success": False, "harmful_repair": False, "abstained": True,
             "baselines": {"raw": {"original_success": True, "recovered_success": False, "harmful_repair": False, "abstained": True}}},
        ]
        summary = evaluator.summarize_baselines(rows)
        self.assertEqual(summary["raw"]["failure_count"], 1)
        self.assertEqual(summary["raw"]["abstention_rate"], 1.0)

    def test_evaluate_file_loads_truth_from_exact_v2_oracle_manifest(self):
        contract = {
            "contract_version": "racer-v2-environment-contract",
            "episode_id": "manifest-episode",
            "source_run_id": "manifest-run",
            "run_id": "manifest-run",
            "env_seed": 2,
            "initial_state_fingerprint": "initial",
            "fault_schedule_fingerprint": "faults",
            "environment_fingerprint": "environment",
        }
        trajectory = {
            "task_id": "manifest",
            "run_id": "manifest-run",
            "source_run_id": "manifest-run",
            "episode_id": "manifest-episode",
            "env_seed": 2,
            "environment_contract": contract,
            "diagnosis": {"candidates": [{"cause": "x", "step_id": 2, "confidence": 0.9}]},
        }
        path = self.write_trajectory(trajectory)
        oracle = self.write_trajectory({
            **trajectory,
            "fault_truth": [{"cause": "x", "step_id": 2}],
        })
        row = evaluator.evaluate_file(path, oracle_path=oracle)
        self.assertTrue(row["oracle_manifest_valid"])
        self.assertTrue(row["step_exact"])

    def test_evaluate_file_rejects_oracle_none_run_id_and_trajectory_truth(self):
        path = self.write_trajectory({
            "task_id": "legacy-looking",
            "fault_truth": [{"cause": "x", "step_id": 0}],
            "diagnosis": {"candidates": [{"cause": "x", "step_id": 0, "confidence": 1.0}]},
        })
        oracle = self.write_trajectory({"fault_truth": [{"cause": "x", "step_id": 0}]})
        row = evaluator.evaluate_file(path, oracle_path=oracle)
        self.assertFalse(row["oracle_manifest_valid"])
        self.assertIsNone(row["step_exact"])

    def test_evaluate_file_rejects_oracle_task_or_contract_mismatch(self):
        contract = {
            "contract_version": "racer-v2-environment-contract",
            "episode_id": "episode",
            "source_run_id": "source",
            "run_id": "source",
            "env_seed": 1,
            "initial_state_fingerprint": "initial",
            "fault_schedule_fingerprint": "faults",
            "environment_fingerprint": "environment",
        }
        trajectory = {
            "task_id": "task-a",
            "run_id": "source",
            "source_run_id": "source",
            "episode_id": "episode",
            "env_seed": 1,
            "environment_contract": contract,
            "diagnosis": {"candidates": [{"cause": "x", "step_id": 0, "confidence": 1.0}]},
        }
        path = self.write_trajectory(trajectory)
        oracle = self.write_trajectory({
            **trajectory,
            "task_id": "task-b",
            "environment_contract": {**contract, "environment_fingerprint": "other"},
            "fault_truth": [{"cause": "x", "step_id": 0}],
        })
        row = evaluator.evaluate_file(path, oracle_path=oracle)
        self.assertFalse(row["oracle_manifest_valid"])
        self.assertIsNone(row["step_exact"])

    def test_step_exact_is_none_without_complete_fault_truth(self):
        path = self.write_trajectory(
            {
                "fault_truth": [{"cause": "x"}],
                "diagnosis": {"candidates": [{"cause": "x", "step_id": 0, "confidence": 1}]},
            }
        )
        self.assertIsNone(evaluator.evaluate_file(path)["step_exact"])


if __name__ == "__main__":
    unittest.main()
