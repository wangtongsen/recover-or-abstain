import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit_v2_artifacts", ROOT / "scripts" / "audit_v2_artifacts.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


CONTRACT = {
    "contract_version": "racer-v2-environment-contract",
    "episode_id": "episode",
    "source_run_id": "source",
    "run_id": "source",
    "env_seed": 0,
    "initial_state_fingerprint": "initial",
    "fault_schedule_fingerprint": "faults",
    "environment_fingerprint": "environment",
}
PAIR = ["episode", "source", "task", "0", "initial", "faults"]
SOURCE_MANIFEST_SHA256 = "a" * 64


def valid_row(**updates):
    row = {
        "protocol_id": "racer-v2-benchmark-protocol-0.1",
        "task_id": "task",
        "run_id": "source",
        "source_run_id": "source",
        "episode_id": "episode",
        "trial_id": 0,
        "model_resource_id": "offline-fixture",
        "main_comparison": True,
        "legacy": False,
        "evaluation_tier": "main",
        "baseline_registry_version": "racer-v2-main-baselines-v1",
        "oracle_manifest_valid": True,
        "seed": 0,
        "environment_contract": dict(CONTRACT),
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "replay_provenance": {
            "valid": True,
            "strict": True,
            "source_contract": dict(CONTRACT),
        },
        "expected_replay_contract": {
            "contract_version": "racer-v2-environment-contract",
            "episode_id": "episode",
            "source_run_id": "source",
            "source_environment_fingerprint": "environment",
            "initial_state_fingerprint": "initial",
            "fault_schedule_fingerprint": "faults",
            "replay_run_id": "source:cf",
        },
        "replay_run_id": "source:cf",
        "paired_identity": list(PAIR),
        "paired_identity_complete": True,
        "baseline_id": "racer",
        "strict_replay": True,
        "counterfactual_supported": True,
        "replay_valid": True,
        "original_success": False,
        "recovered_success": True,
        "harmful_repair": False,
        "abstained": False,
    }
    row.update(updates)
    return row


def valid_envelope(*rows, **updates):
    envelope = {
        "schema_version": audit.CANONICAL_SCHEMA,
        "experiment": "synthetic",
        "count": len(rows),
        "records": list(rows),
        "deduplication": {
            "strategy": audit.DEDUP_STRATEGY,
            "dropped_count": 0,
            "dropped": [],
            "legacy_rows_retained": 0,
        },
    }
    envelope.update(updates)
    return envelope


class ArtifactAdmissionAuditTests(unittest.TestCase):
    def test_valid_canonical_artifact_passes(self):
        result = audit.audit_payload(valid_envelope(valid_row()))
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["return_code"], 0)
        self.assertTrue(all(status == "PASS" for status in result["checks"].values()))

    def test_recovery_without_valid_replay_fails_closed(self):
        result = audit.audit_payload(valid_envelope(valid_row(replay_valid=False)))
        self.assertEqual(result["verdict"], "NO-GO")
        self.assertIn("G3_RECOVERY_WITHOUT_VALID_REPLAY", {issue["code"] for issue in result["issues"]})

    def test_recovery_requires_exact_replay_provenance(self):
        row = valid_row(replay_provenance={"valid": True, "strict": True, "source_contract": {"bad": True}})
        result = audit.audit_payload(valid_envelope(row))
        self.assertEqual(result["verdict"], "NO-GO")
        self.assertIn("G3_REPLAY_SOURCE_CONTRACT_MISMATCH", {issue["code"] for issue in result["issues"]})

    def test_refund_response_loss_requires_witness_and_reconciliation(self):
        row = valid_row(response_loss=True, refund_entity_id="refund-1")
        result = audit.audit_payload(valid_envelope(row))
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("G4_INCOMPLETE_REFUND_WITNESS", codes)
        self.assertIn("G4_UNVERIFIED_REFUND_WITNESS", codes)
        self.assertIn("G4_UNRECONCILED_RESPONSE_LOSS", codes)

    def test_truth_or_secret_leakage_is_rejected_at_top_level_and_row(self):
        result = audit.audit_payload(valid_envelope(
            valid_row(metadata={"fault_truth": {"id": "hidden"}}),
            authorization="Bearer secret",
        ))
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("G5_ORACLE_TRUTH_EXPOSED", codes)
        self.assertIn("G5_SECRET_FIELD_EXPOSED", codes)
        self.assertIn("G5_SECRET_VALUE_PATTERN", codes)

    def test_multiple_alias_containers_are_rejected(self):
        payload = valid_envelope(valid_row(), entries=[])
        result = audit.audit_payload(payload)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("G7_MULTIPLE_CONTAINERS", codes)
        self.assertIn("G7_CANONICAL_RECORDS_REQUIRED", codes)

    def test_schema_with_entries_instead_of_records_is_rejected(self):
        payload = {"schema_version": audit.CANONICAL_SCHEMA, "entries": [valid_row()]}
        result = audit.audit_payload(payload)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("G7_CANONICAL_RECORDS_REQUIRED", codes)

    def test_contract_or_paired_identity_mismatch_is_rejected(self):
        wrong_pair = valid_row(paired_identity=["episode", "source", "other-task", "0", "initial", "faults"])
        result = audit.audit_payload(valid_envelope(wrong_pair))
        self.assertIn("G2_PAIRED_IDENTITY_CONTRACT_MISMATCH", {issue["code"] for issue in result["issues"]})

    def test_hidden_serializer_duplicate_is_rejected(self):
        result = audit.audit_payload(valid_envelope(
            valid_row(),
            deduplication={
                "strategy": audit.DEDUP_STRATEGY,
                "dropped_count": 1,
                "dropped": [{"paired_identity": PAIR}],
                "legacy_rows_retained": 0,
            },
        ))
        self.assertIn("G7_DEDUPLICATION_NOT_CLEAN", {issue["code"] for issue in result["issues"]})

    def test_duplicate_paired_baseline_is_rejected(self):
        result = audit.audit_payload(valid_envelope(valid_row(), valid_row(), count=2))
        self.assertIn("G7_DUPLICATE_PAIRED_BASELINE", {issue["code"] for issue in result["issues"]})

    def test_legacy_row_is_not_main_table_admissible(self):
        legacy = valid_row(main_comparison=False, legacy=True)
        result = audit.audit_payload(valid_envelope(legacy))
        self.assertEqual(result["verdict"], "NO-GO")
        self.assertIn("G2_NON_MAIN_RECORD", {issue["code"] for issue in result["issues"]})


class V04HarmLabelGatingTests(unittest.TestCase):
    """Protocol v0.4: harm rows must carry independent-oracle labels."""

    def v04_row(self, **updates):
        row = valid_row(
            protocol_id="racer-v2-benchmark-protocol-0.4",
            harmful_repair=False,
            harm_label_source="independent_oracle_v04",
            harm_recomputed=False,
            cf_outcome_harm=False,
        )
        row.update(updates)
        return row

    def test_v04_row_with_oracle_labels_passes(self):
        result = audit.audit_payload(valid_envelope(self.v04_row()))
        self.assertEqual(result["verdict"], "PASS")

    def test_v04_harm_row_missing_label_source_fails(self):
        row = self.v04_row(harmful_repair=True, harm_recomputed=True, cf_outcome_harm=True)
        row.pop("harm_label_source")
        result = audit.audit_payload(valid_envelope(row))
        self.assertEqual(result["verdict"], "NO-GO")
        self.assertIn("G4_HARM_LABEL_NOT_ORACLE_SOURCED", {issue["code"] for issue in result["issues"]})

    def test_v04_harm_label_disagreeing_with_repair_fails(self):
        # harmful_repair=True but oracle recomputed=False -> label mismatch.
        row = self.v04_row(harmful_repair=True, harm_recomputed=False, cf_outcome_harm=False)
        result = audit.audit_payload(valid_envelope(row))
        self.assertIn("G4_HARM_LABEL_NOT_ORACLE_SOURCED", {issue["code"] for issue in result["issues"]})

    def test_v04_nonboolean_recomputed_fails(self):
        row = self.v04_row(harm_recomputed=None)
        result = audit.audit_payload(valid_envelope(row))
        self.assertIn("G4_HARM_LABEL_NOT_ORACLE_SOURCED", {issue["code"] for issue in result["issues"]})

    def test_v01_row_without_v04_fields_still_passes(self):
        # v0.1/v0.3 rows carry no v0.4 fields: the gate is version-scoped.
        result = audit.audit_payload(valid_envelope(valid_row()))
        self.assertEqual(result["verdict"], "PASS")


class V05DomainScenarioGatingTests(unittest.TestCase):
    """Protocol v0.5: domain/scenario identity + independent_oracle_v05 labels."""

    def v05_row(self, **updates):
        row = valid_row(
            protocol_id="racer-v2-benchmark-protocol-0.5",
            task_id="v05-e3-E3-S1-trial-0",
            paired_identity=["episode", "source", "v05-e3-E3-S1-trial-0", "0", "initial", "faults"],
            harmful_repair=False,
            harm_label_source="independent_oracle_v05",
            harm_recomputed=False,
            domain="flight",
            scenario_id="E3-S1",
        )
        row.update(updates)
        return row

    def test_v05_row_with_domain_scenario_and_v05_labels_passes(self):
        result = audit.audit_payload(valid_envelope(self.v05_row()))
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["checks"]["G6_v05_domain_scenario_and_oracle_labels"], "PASS")

    def test_v05_row_missing_domain_fails(self):
        row = self.v05_row()
        row.pop("domain")
        result = audit.audit_payload(valid_envelope(row))
        self.assertIn("G6_V05_DOMAIN_MISSING_OR_INVALID", {issue["code"] for issue in result["issues"]})

    def test_v05_row_unknown_domain_fails(self):
        result = audit.audit_payload(valid_envelope(self.v05_row(domain="train")))
        self.assertIn("G6_V05_DOMAIN_MISSING_OR_INVALID", {issue["code"] for issue in result["issues"]})

    def test_v05_e3_row_missing_scenario_id_fails(self):
        row = self.v05_row()
        row.pop("scenario_id")
        result = audit.audit_payload(valid_envelope(row))
        self.assertIn("G6_V05_SCENARIO_ID_MISSING", {issue["code"] for issue in result["issues"]})

    def test_v05_e3_row_unregistered_scenario_id_fails(self):
        result = audit.audit_payload(valid_envelope(self.v05_row(scenario_id="E3-S9")))
        self.assertIn("G6_V05_SCENARIO_ID_UNREGISTERED", {issue["code"] for issue in result["issues"]})

    def test_v05_main_row_does_not_require_scenario_id(self):
        # Main-track v0.5 rows (v05-main-...) only require domain, not scenario_id.
        row = self.v05_row(task_id="v05-main-flight-clean_success-trial-0")
        row.pop("scenario_id")
        result = audit.audit_payload(valid_envelope(row))
        codes = {issue["code"] for issue in result["issues"]}
        self.assertNotIn("G6_V05_SCENARIO_ID_MISSING", codes)
        self.assertNotIn("G6_V05_SCENARIO_ID_UNREGISTERED", codes)

    def test_v05_row_with_v04_label_source_fails(self):
        result = audit.audit_payload(valid_envelope(self.v05_row(harm_label_source="independent_oracle_v04")))
        self.assertIn("G6_V05_HARM_LABEL_NOT_ORACLE_V05", {issue["code"] for issue in result["issues"]})

    def test_v05_harm_label_disagreeing_with_repair_fails(self):
        row = self.v05_row(harmful_repair=True, harm_recomputed=False)
        result = audit.audit_payload(valid_envelope(row))
        self.assertIn("G6_V05_HARM_LABEL_DISAGREES", {issue["code"] for issue in result["issues"]})

    def test_v05_nonboolean_recomputed_fails(self):
        result = audit.audit_payload(valid_envelope(self.v05_row(harm_recomputed=None)))
        self.assertIn("G6_V05_HARM_LABEL_MISSING_RECOMPUTED", {issue["code"] for issue in result["issues"]})


if __name__ == "__main__":
    unittest.main()
