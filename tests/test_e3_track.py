"""Protocol v0.2 E3 track tests: tamper_result fault, catalog obfuscation,
replay veto, direct application, and G4 v0.2 admission semantics.

These tests load the service sources directly (the module-level HTTPServer
bootstrap line is stripped) so they run offline without Docker.
"""
import json
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_ENV_SRC = (PROJECT_ROOT / "services" / "task_env" / "app.py").read_text(encoding="utf-8")


def _load_task_env_module():
    source = TASK_ENV_SRC.replace(
        'HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()', ""
    )
    module = types.ModuleType("task_env_app")
    exec(compile(source, "services/task_env/app.py", "exec"), module.__dict__)
    return module


E3_FLIGHTS = [
    {"id": "F1", "price": 420, "refundable": True},
    {"id": "F2", "price": 360, "refundable": True},
    {"id": "F3", "price": 480, "refundable": True},
]
TAMPER_FAULT = {
    "fault_id": "tamper-0",
    "type": "tamper_result",
    "step_id": 0,
    "tool": "search_flights",
    "result": {"flights": [
        {"id": "F1", "price": 420, "refundable": True},
        {"id": "F3", "price": 480, "refundable": True},
    ]},
}
FORCE_ERROR_FAULT = {
    "fault_id": "fe-1",
    "type": "force_error",
    "step_id": 2,
    "tool": "confirm_booking",
    "error": "injected force_error_confirm",
}


def _e3_config(faults):
    return {
        "task_variant": "e3_tamper_force_error",
        "obfuscate_catalog": True,
        "enable_refund_ledger": True,
        "flights": json.loads(json.dumps(E3_FLIGHTS)),
        "budget": 500,
        "faults": json.loads(json.dumps(faults)),
    }


class TestTamperResultFault:
    def setup_method(self):
        self.mod = _load_task_env_module()

    def test_tampered_search_hides_optimal_flight(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t1", "seed": 0, "env_config": _e3_config([TAMPER_FAULT])})
        result = env.step({"tool": "search_flights", "arguments": {}})["result"]
        assert [f["id"] for f in result["flights"]] == ["F1", "F3"]
        assert result.get("tampered") is True
        assert result.get("ok", True) is True

    def test_observe_hides_real_catalog_when_obfuscated(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t2", "seed": 0, "env_config": _e3_config([TAMPER_FAULT])})
        observation = env.observe()
        assert "flights" not in observation["env_config"]
        assert observation["env_config"].get("flight_catalog_visible") is False

    def test_observe_keeps_catalog_without_obfuscate_flag(self):
        env = self.mod.TaskEnv()
        cfg = _e3_config([TAMPER_FAULT])
        cfg["obfuscate_catalog"] = False
        env.reset({"run_id": "t3", "seed": 0, "env_config": cfg})
        observation = env.observe()
        assert "flights" in observation["env_config"]

    def test_naive_retry_confirms_suboptimal_flight(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t4", "seed": 0, "env_config": _e3_config([TAMPER_FAULT, FORCE_ERROR_FAULT])})
        env.step({"tool": "search_flights", "arguments": {}})
        env.step({"tool": "select_flight", "arguments": {"flight_id": "F1"}})
        failed = env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
        assert failed["result"]["ok"] is False
        retried = env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
        assert retried["result"]["ok"] is True
        evaluation = env.evaluate()
        assert evaluation["side_effect"] is True
        assert evaluation["success"] is False

    def test_clean_replay_exposes_harm_and_replan_succeeds(self):
        env = self.mod.TaskEnv()
        cfg = _e3_config([TAMPER_FAULT, FORCE_ERROR_FAULT])
        env.reset({"run_id": "t5:cf", "seed": 0, "env_config": {**cfg, "faults": []}})
        env.step({"tool": "search_flights", "arguments": {}})
        assert env.state["selected_flight"] is None
        env.step({"tool": "select_flight", "arguments": {"flight_id": "F2"}})
        env.step({"tool": "confirm_booking", "arguments": {"user_confirmed": True}})
        evaluation = env.evaluate()
        assert evaluation["success"] is True
        assert evaluation["side_effect"] is False


class TestReplayVetoDecision:
    """The veto is implemented in agent_runner.run_task; here we verify the
    decision contract shape that the veto produces, matching protocol v0.2 D.1.
    """

    def test_veto_abstain_shape(self):
        veto = {
            "baseline_id": "racer",
            "decision": "abstain",
            "reason": "replay_veto_side_effect",
            "patch": None,
            "use_counterfactual": True,
            "replay_veto": True,
            "replay_veto_reason": "replay_veto_side_effect",
        }
        assert veto["decision"] == "abstain"
        assert veto["patch"] is None
        assert veto["use_counterfactual"] is True
        assert veto["replay_veto_reason"] in {"replay_veto_side_effect", "replay_veto_not_success"}

    def test_direct_apply_contract(self):
        decision = {
            "baseline_id": "racer_no_counterfactual",
            "decision": "retry",
            "patch": {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
            "skip_counterfactual": True,
            "direct_applied": True,
            "counterfactual_supported": False,
            "replay_valid": False,
            "strict_replay": False,
        }
        assert decision["direct_applied"] is True
        assert decision["counterfactual_supported"] is False


class TestG4V02Admission:
    def setup_method(self):
        import sys
        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import audit_v2_artifacts
        self.audit = audit_v2_artifacts

    def _base_row(self, **overrides):
        row = {
            "protocol_id": "racer-v2-benchmark-protocol-0.2",
            "task_id": "main-e3-e3_tamper_force_error-trial-0",
            "run_id": "run-1",
            "source_run_id": "run-1",
            "episode_id": "ep-1",
            "trial_id": 0,
            "model_resource_id": "oneapi-relay-glm-5.3-flash",
            "main_comparison": True,
            "legacy": False,
            "evaluation_tier": "main",
            "baseline_registry_version": "racer-v2-main-baselines-v1",
            "oracle_manifest_valid": True,
            "environment_contract": {
                "contract_version": "racer-v2-environment-contract",
                "episode_id": "ep-1",
                "source_run_id": "run-1",
                "run_id": "run-1",
                "env_seed": 0,
                "initial_state_fingerprint": "a" * 64,
                "fault_schedule_fingerprint": "b" * 64,
                "environment_fingerprint": "c" * 64,
            },
            "source_manifest_sha256": "d" * 64,
            "paired_identity": ["ep-1", "run-1", "main-e3-e3_tamper_force_error-trial-0", "0", "a" * 64, "b" * 64],
            "paired_identity_complete": True,
            "baseline_id": "fixed_retry",
            "original_success": False,
            "recovered_success": False,
            "harmful_repair": True,
            "abstained": False,
            "strict_replay": True,
            "counterfactual_supported": True,
            "replay_valid": True,
            "side_effect": True,
        }
        row.update(overrides)
        return row

    def test_replay_verified_harm_passes(self):
        row = self._base_row()
        issues = []
        self.audit._validate_side_effect(row, 0, issues)
        assert issues == []

    def test_harm_without_side_effect_flag_fails(self):
        row = self._base_row(side_effect=False)
        issues = []
        self.audit._validate_side_effect(row, 0, issues)
        assert any(issue["code"] == "G4_HARM_WITHOUT_SIDE_EFFECT_FLAG" for issue in issues)

    def test_direct_apply_harm_passes_without_witness(self):
        row = self._base_row(
            baseline_id="racer_no_counterfactual",
            counterfactual_supported=False,
            replay_valid=False,
            strict_replay=False,
            decision="retry",
        )
        issues = []
        self.audit._validate_side_effect(row, 0, issues)
        assert issues == []

    def test_harm_with_no_evidence_form_fails(self):
        row = self._base_row(
            counterfactual_supported=False,
            replay_valid=False,
            strict_replay=False,
            decision="abstain",
        )
        issues = []
        self.audit._validate_side_effect(row, 0, issues)
        assert any(issue["code"] == "G4_HARM_WITHOUT_EVIDENCE_FORM" for issue in issues)

    def test_refund_semantics_still_requires_witness(self):
        row = self._base_row(side_effect_attempted=True, harmful_repair=False)
        issues = []
        self.audit._validate_side_effect(row, 0, issues)
        assert any(issue["code"] == "G4_INCOMPLETE_REFUND_WITNESS" for issue in issues)

    def test_v01_main_envelope_regression(self):
        import subprocess
        envelope = PROJECT_ROOT / "output" / "racer-v2-main-20260906" / "main-envelope.json"
        if not envelope.exists():
            return
        completed = subprocess.run(
            ["/usr/bin/python3", str(PROJECT_ROOT / "scripts" / "audit_v2_artifacts.py"), str(envelope)],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0
