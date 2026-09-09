"""v0.5 E3 scenario registry regression tests (protocol v0.5 Task #40).

The registry is a frozen pre-registration artifact: these tests pin its
structural and behavioral invariants so any future edit that changes
scenario semantics (catalogs, fault schedules, declared optima, independence)
fails loudly instead of silently drifting.
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "experiments" / "racer-v2-v05-scenario-registry.json"

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import validate_v05_scenarios as preflight  # noqa: E402


def _load_registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


class RegistryStructureTest(unittest.TestCase):

    def setUp(self):
        self.registry = _load_registry()

    def test_schema_and_count(self):
        self.assertEqual(self.registry["schema_version"], "racer-v2-v05-scenario-registry-v1")
        self.assertEqual(len(self.registry["scenarios"]), 7)

    def test_domain_coverage(self):
        domains = {s["domain"] for s in self.registry["scenarios"]}
        self.assertEqual(domains, {"flight", "hotel", "shop"})

    def test_scenario_ids_stable(self):
        self.assertEqual(
            [s["scenario_id"] for s in self.registry["scenarios"]],
            ["E3-S1", "E3-S2", "E3-S3", "E3-S4", "E3-S5", "E3-S6", "E3-S7"],
        )

    def test_every_scenario_has_tamper_at_search_plus_one_post_fault(self):
        for s in self.registry["scenarios"]:
            faults = s["env_config"]["faults"]
            tamps = [f for f in faults if f["type"] == "tamper_result"]
            posts = [f for f in faults if f["type"] != "tamper_result"]
            self.assertEqual(len(tamps), 1, s["scenario_id"])
            self.assertEqual(tamps[0]["step_id"], 0, s["scenario_id"])
            self.assertEqual(len(posts), 1, s["scenario_id"])
            self.assertEqual(posts[0]["step_id"], 2, s["scenario_id"])
            self.assertIn(posts[0]["type"], ("force_error", "rate_limit", "wrong_tool"), s["scenario_id"])

    def test_obfuscation_and_ledger_required(self):
        for s in self.registry["scenarios"]:
            self.assertTrue(s["env_config"]["obfuscate_catalog"], s["scenario_id"])
            self.assertTrue(s["env_config"]["enable_refund_ledger"], s["scenario_id"])

    def test_harm_direction_declared(self):
        # The declared agent pick must differ from the declared real optimal;
        # committing the pick on the clean environment is the harm trap.
        for s in self.registry["scenarios"]:
            self.assertNotEqual(s["agent_expected_selection"], s["real_optimal"], s["scenario_id"])

    def test_excluded_mechanisms_recorded(self):
        excluded = self.registry["excluded_mechanisms"]
        for key in ("drop_action_at_confirm", "response_loss_at_confirm",
                    "truthful_listing_planning_error", "double_apply"):
            self.assertIn(key, excluded)
            self.assertTrue(excluded[key].strip())


class RegistryBehaviorTest(unittest.TestCase):
    """Drive the real task_env engine over every registered scenario."""

    @classmethod
    def setUpClass(cls):
        cls.env_module = preflight.load_task_env()
        cls.registry = _load_registry()
        cls.failures = []
        for scenario in cls.registry["scenarios"]:
            preflight.check_scenario(cls.env_module, scenario, cls.failures)

    def test_preflight_rules_all_pass(self):
        self.assertEqual(self.failures, [], "; ".join(self.failures))

    def test_pairwise_independence(self):
        failures = preflight.check_independence(self.registry["scenarios"])
        self.assertEqual(failures, [], "; ".join(failures))

    def test_s1_byte_continuity_with_v03_matrix(self):
        matrix = json.loads((PROJECT_ROOT / "experiments" / "racer-v2-main-matrix-e3.json").read_text(encoding="utf-8"))
        v03 = next(t for t in matrix["tasks"] if t["cell"] == "tamper:e3_tamper_force_error")
        s1 = next(s for s in self.registry["scenarios"] if s["scenario_id"] == "E3-S1")
        for key in ("faults", "flights", "budget", "enable_refund_ledger", "obfuscate_catalog", "task_variant"):
            self.assertEqual(v03["env_config"][key], s1["env_config"][key], key)


if __name__ == "__main__":
    unittest.main()
