"""v0.5 execution matrix regression tests (protocol v0.5 Task #41).

Pins the structural invariants of both frozen matrices plus the behavioral
preflight (real engine, one representative task per cell).
"""
import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_MATRIX = PROJECT_ROOT / "experiments" / "racer-v2-v05-matrix-main.json"
E3_MATRIX = PROJECT_ROOT / "experiments" / "racer-v2-v05-matrix-e3.json"

import sys  # noqa: E402
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import validate_v05_matrices as matrix_preflight  # noqa: E402
import validate_v05_scenarios as scenario_preflight  # noqa: E402


class MatrixStructureTest(unittest.TestCase):

    def test_e3_matrix_shape(self):
        m = json.loads(E3_MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(m["protocol_id"], "racer-v2-benchmark-protocol-0.5")
        self.assertEqual(len(m["tasks"]), 70)
        self.assertEqual(len({t["cell"] for t in m["tasks"]}), 7)
        self.assertTrue(all(len(t["baselines"]) == 14 for t in m["tasks"]))
        self.assertTrue(all(t["strict_replay"] is True for t in m["tasks"]))

    def test_main_matrix_shape(self):
        m = json.loads(MAIN_MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(m["protocol_id"], "racer-v2-benchmark-protocol-0.5")
        self.assertEqual(len(m["tasks"]), 330)
        self.assertEqual(len({t["cell"] for t in m["tasks"]}), 33)
        domains = {t["domain"] for t in m["tasks"]}
        self.assertEqual(domains, {"flight", "hotel", "shop"})

    def test_confirm_faults_at_two_step_position(self):
        # The v0.1 defect (confirm faults scheduled at step_id=2 under a
        # 2-step actor) must not regress.
        m = json.loads(MAIN_MATRIX.read_text(encoding="utf-8"))
        for t in m["tasks"]:
            for fault in t["env_config"]["faults"]:
                self.assertIn(fault.get("step_id"), (0, 1), f"{t['task_id']}: {fault['fault_id']}")

    def test_task_ids_unique_and_seeds_complete(self):
        for path in (E3_MATRIX, MAIN_MATRIX):
            m = json.loads(path.read_text(encoding="utf-8"))
            ids = [t["task_id"] for t in m["tasks"]]
            self.assertEqual(len(ids), len(set(ids)), path.name)
            cells = {}
            for t in m["tasks"]:
                cells.setdefault(t["cell"], set()).add(t["seed"])
            for cell, seeds in cells.items():
                self.assertEqual(seeds, set(range(10)), f"{path.name}:{cell}")


class MatrixBehaviorTest(unittest.TestCase):

    def test_main_matrix_cell_preflight(self):
        env_module = scenario_preflight.load_task_env()
        matrix = json.loads(MAIN_MATRIX.read_text(encoding="utf-8"))
        failures = []
        seen = set()
        for task in matrix["tasks"]:
            if task["cell"] in seen:
                continue
            seen.add(task["cell"])
            matrix_preflight.check_main_cell(env_module, task, failures)
        self.assertEqual(failures, [], "; ".join(failures))

    def test_e3_envelope_registry_linkage(self):
        failures = []
        matrix_preflight.check_e3_envelope(failures)
        self.assertEqual(failures, [], "; ".join(failures))


if __name__ == "__main__":
    unittest.main()
