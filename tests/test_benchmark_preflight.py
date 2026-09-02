import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "benchmark_preflight", ROOT / "scripts" / "benchmark_preflight.py"
)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class BenchmarkPreflightTests(unittest.TestCase):
    def _matrix(self, *, experiment="fixture", tasks=None, baselines=None):
        return {
            "experiment": experiment,
            "version": 1,
            "baselines": baselines or ["raw", "racer"],
            "seeds": [0],
            "tasks": tasks or [{
                "task_id": "fixture-task",
                "run_id": "fixture-run",
                "episode_id": "fixture-episode",
                "seed": 0,
                "strict_replay": True,
                "evaluation_tier": "main",
                "baseline_registry_version": "fixture-main-v1",
                "main_comparison": True,
                "baselines": baselines or ["raw", "racer"],
            }],
        }

    def _write_json(self, payload, name="matrix.json"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _protocol(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "protocol.md"
        path.write_text("# Frozen protocol\n", encoding="utf-8")
        return path

    def _model_registry(self):
        return [{
            "model_resource_id": "model-a",
            "provider": "local",
            "model_name": "fixture",
            "model_version": "v1",
            "credential_source": "TEST_MODEL_KEY",
        }]

    def test_build_expands_every_task_baseline_and_five_trials(self):
        matrix = self._write_json(self._matrix(baselines=["raw", "racer"]))
        manifest = preflight.build_manifest([matrix], protocol_path=self._protocol())
        self.assertEqual(manifest["schema_version"], preflight.SCHEMA_VERSION)
        self.assertEqual(manifest["required_trial_ids"], [0, 1, 2, 3, 4])
        self.assertEqual(len(manifest["planned_cells"]), 10)
        self.assertTrue(all(cell["strict_replay"] for cell in manifest["planned_cells"]))
        self.assertTrue(all(cell["status"] == "planned" for cell in manifest["planned_cells"]))
        self.assertTrue(all(cell["model_resource_id"] is None for cell in manifest["planned_cells"]))
        self.assertTrue(all(cell["evaluation_tier"] == "main" for cell in manifest["planned_cells"]))

    def test_registered_models_are_bound_into_every_planned_cell(self):
        manifest = preflight.build_manifest(
            [self._write_json(self._matrix())],
            protocol_path=self._protocol(),
            model_registry=self._model_registry(),
        )
        self.assertEqual(len(manifest["planned_cells"]), 10)
        self.assertEqual(
            {cell["model_resource_id"] for cell in manifest["planned_cells"]},
            {"model-a"},
        )

    def test_planned_only_manifest_is_no_go_without_models_and_execution(self):
        manifest = preflight.build_manifest(
            [self._write_json(self._matrix())], protocol_path=self._protocol()
        )
        result = preflight.audit_manifest(manifest)
        self.assertEqual(result["verdict"], "NO-GO")
        self.assertEqual(result["return_code"], 2)
        self.assertIn("G0_MODEL_REGISTRY_MISSING", result["blockers"])
        self.assertIn("G8_EXECUTED_ARTIFACTS_MISSING", result["blockers"])
        self.assertEqual(result["counts"]["planned_cells"], 10)

    def test_rejects_pilot_cell_marked_as_main_comparison(self):
        matrix = self._matrix()
        matrix["tasks"][0].update({
            "evaluation_tier": "pilot",
            "baseline_registry_version": "local-flight-pilot-v1",
            "main_comparison": False,
        })
        manifest = preflight.build_manifest(
            [self._write_json(matrix)], protocol_path=self._protocol()
        )
        manifest["planned_cells"][0]["main_comparison"] = True
        result = preflight.audit_manifest(manifest)
        self.assertIn(
            "G0_PILOT_CELL_MARKED_MAIN",
            {issue["code"] for issue in result["issues"]},
        )

    def test_rejects_incomplete_trial_coverage(self):
        manifest = preflight.build_manifest(
            [self._write_json(self._matrix())], protocol_path=self._protocol()
        )
        manifest["planned_cells"] = manifest["planned_cells"][:-1]
        result = preflight.audit_manifest(manifest)
        self.assertIn(
            "PREFLIGHT_INCOMPLETE_TRIAL_COVERAGE",
            {issue["code"] for issue in result["issues"]},
        )

    def test_rejects_secret_bearing_model_registry(self):
        registry = self._model_registry()
        registry[0]["api_key"] = "must-not-appear"
        manifest = preflight.build_manifest(
            [self._write_json(self._matrix())], protocol_path=self._protocol(),
            model_registry=registry,
        )
        result = preflight.audit_manifest(manifest)
        self.assertEqual(result["verdict"], "NO-GO")
        self.assertIn(
            "G5_SECRET_IN_MODEL_REGISTRY",
            {issue["code"] for issue in result["issues"]},
        )

    def test_partial_executed_registry_fails_coverage_gate(self):
        manifest = preflight.build_manifest(
            [self._write_json(self._matrix())], protocol_path=self._protocol(),
            model_registry=self._model_registry(),
        )
        cell = manifest["planned_cells"][0]
        manifest["executed_artifacts"] = [{
            "matrix_id": cell["matrix_id"],
            "task_id": cell["task_id"],
            "baseline_id": cell["baseline_id"],
            "trial_id": cell["trial_id"],
            "model_resource_id": cell["model_resource_id"],
            "run_id": "fixture-executed",
            "artifact_sha256": "abc",
        }]
        result = preflight.audit_manifest(manifest)
        self.assertIn(
            "G8_EXECUTED_COVERAGE_INCOMPLETE",
            {issue["code"] for issue in result["issues"]},
        )

    def test_complete_synthetic_registry_and_provenance_passes_structure_checks(self):
        manifest = preflight.build_manifest(
            [self._write_json(self._matrix())], protocol_path=self._protocol(),
            model_registry=self._model_registry(),
        )
        manifest["executed_artifacts"] = [
            {
                "matrix_id": cell["matrix_id"],
                "task_id": cell["task_id"],
                "baseline_id": cell["baseline_id"],
                "trial_id": cell["trial_id"],
                "model_resource_id": cell["model_resource_id"],
                "run_id": f"fixture-{index}",
                "artifact_sha256": f"sha-{index}",
            }
            for index, cell in enumerate(manifest["planned_cells"])
        ]
        result = preflight.audit_manifest(manifest)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["return_code"], 0)

    def test_build_rejects_task_without_paired_provenance(self):
        broken = self._matrix(tasks=[{
            "task_id": "fixture-task",
            "run_id": "fixture-run",
            "strict_replay": True,
            "baselines": ["raw"],
        }])
        with self.assertRaisesRegex(ValueError, "episode_id"):
            preflight.build_manifest([self._write_json(broken)], protocol_path=self._protocol())


if __name__ == "__main__":
    unittest.main()
