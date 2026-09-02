import copy
import hashlib
import importlib.util
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import quote
import sys
from urllib.request import Request, urlopen

TASK_ENV_URL = os.environ.get("TASK_ENV_URL", "http://task-env:8080")
DIAGNOSER_URL = os.environ.get("DIAGNOSER_URL", "http://diagnoser:8080")
RECOVERY_URL = os.environ.get("RECOVERY_URL", "http://recovery-policy:8080")
REPLAYER_URL = os.environ.get("REPLAYER_URL", "http://counterfactual:8080")
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "5"))
STARTUP_RETRIES = int(os.environ.get("STARTUP_RETRIES", "10"))
STARTUP_RETRY_DELAY = float(os.environ.get("STARTUP_RETRY_DELAY", "0.5"))
BATCH_SPEC = os.environ.get("BATCH_SPEC")
TRAJECTORY_DIR = os.environ.get("TRAJECTORY_DIR", "/data/trajectories")
ORACLE_DIR = os.environ.get("ORACLE_DIR", "/data/oracle")
# Callable actors are bounded by default so a malformed or looping model cannot
# consume unbounded LLM calls. MAX_DYNAMIC_STEPS remains a patchable alias.
DEFAULT_MAX_ACTOR_STEPS = 3
try:
    MAX_DYNAMIC_STEPS = max(1, int(os.environ.get("MAX_DYNAMIC_STEPS", DEFAULT_MAX_ACTOR_STEPS)))
except (TypeError, ValueError):
    MAX_DYNAMIC_STEPS = DEFAULT_MAX_ACTOR_STEPS
DEPENDENCIES = {
    "task-env": TASK_ENV_URL,
    "diagnoser": DIAGNOSER_URL,
    "recovery-policy": RECOVERY_URL,
    "counterfactual": REPLAYER_URL,
}
DEFAULT_ACTIONS = [
    {"tool": "search_flights", "arguments": {}},
    {"tool": "select_flight", "arguments": {"flight_id": "F2"}},
    {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
]
PILOT_BASELINE_CATALOG = frozenset({"raw", "recovery", "oracle"})
PILOT_ORACLE_BASELINES = frozenset({"oracle"})
MAIN_BASELINE_CATALOG = frozenset({
    "raw_react", "fixed_retry", "exponential_backoff", "generic_reflection",
    "full_trace_judge", "step_by_step_diagnosis", "binary_search_diagnosis",
    "agentdebug_targeted_feedback", "always_recover", "racer", "racer_no_abstain",
    "racer_no_counterfactual", "oracle_root_cause", "oracle_recovery",
})
MAIN_ORACLE_BASELINES = frozenset({"oracle_root_cause", "oracle_recovery"})
_SERVICE_DIR = Path(__file__).resolve().parent
_DEFAULT_PROJECT_ROOT = _SERVICE_DIR.parents[1] if _SERVICE_DIR.name == "agent_runner" and _SERVICE_DIR.parent.name == "services" else _SERVICE_DIR
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", _DEFAULT_PROJECT_ROOT)).resolve()
_COMMON_DIR = next(
    candidate
    for candidate in (Path(__file__).resolve().parent / "common", PROJECT_ROOT / "services" / "common")
    if candidate.is_dir()
)
if str(_COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMON_DIR))
from environment_contract import environment_contract, expected_clean_replay_contract


def _config_hash(value):
    """Return a stable hash for a JSON-compatible actor configuration."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_manifest_anchor(result):
    """Hash only immutable source provenance, excluding evaluator-only truth."""
    fields = (
        "protocol_id", "task_id", "run_id", "source_run_id", "episode_id", "seed",
        "trial_id", "model_resource_id", "environment_contract", "actor_id", "actor_config_hash",
        "evaluation_tier", "baseline_registry_version", "main_comparison", "legacy",
    )
    return _config_hash({field: result.get(field) for field in fields})


def _actor_meta(actor_id, config):
    return {"actor_id": str(actor_id), "config_hash": _config_hash(config)}


def _resolve_local_path(path):
    """Resolve an actor file and reject paths outside the project tree."""
    if not isinstance(path, (str, os.PathLike)) or not str(path).strip():
        raise ValueError("actor actions path must be a non-empty local path")
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise ValueError(f"actor actions path must be inside project directory: {resolved}") from error
    if not resolved.is_file():
        raise ValueError(f"actor actions path must be a file: {resolved}")
    return resolved


def _load_json_actor(path, payload=None):
    if payload is None:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    if isinstance(payload, list):
        actions = payload
    elif isinstance(payload, dict):
        actions = payload.get("actions", payload.get("policy"))
    else:
        actions = None
    if not isinstance(actions, list):
        raise ValueError("JSON actor policy must contain an actions array")
    if not all(isinstance(action, dict) for action in actions):
        raise ValueError("JSON actor actions must be objects")
    return copy.deepcopy(actions), payload


def _actor_spec(task):
    """Read actor config from a task, including the optional task envelope."""
    if not isinstance(task, dict):
        return None
    for key in ("actor", "actor_config"):
        if key in task:
            return task[key]
    nested = task.get("task")
    if isinstance(nested, dict):
        for key in ("actor", "actor_config"):
            if key in nested:
                return nested[key]
        if any(key in nested for key in ("actor_id", "actions_file", "actions_path")):
            return nested
    if any(key in task for key in ("actor_id", "actions_file", "actions_path")):
        return task
    return None


def _deterministic_actions(task):
    actions = task.get("actions")
    return copy.deepcopy(actions) if isinstance(actions, list) else copy.deepcopy(DEFAULT_ACTIONS)


def _load_python_actor(path, entrypoint="act"):
    source = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location("local_actor_" + hashlib.sha256(source).hexdigest()[:16], path)
    if spec is None or spec.loader is None:
        raise ValueError(f"unable to load Python actor: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actor = getattr(module, entrypoint, None) or getattr(module, "actions", None)
    if actor is None:
        raise ValueError(f"Python actor must define {entrypoint}() or actions")
    # Preserve optional redacted usage metrics exposed by an actor module while
    # keeping the callable contract backward compatible.
    usage_snapshot = getattr(module, "usage_snapshot", None)
    if callable(usage_snapshot):
        try:
            setattr(actor, "usage_snapshot", usage_snapshot)
        except (AttributeError, TypeError):
            pass
    return actor, source.decode("utf-8")


def _actor_actions(actor, observation, context):
    return actor(copy.deepcopy(observation), copy.deepcopy(context))


def _actor_usage(actor):
    """Return optional redacted actor usage metrics without changing legacy actors."""
    snapshot = getattr(actor, "usage_snapshot", None)
    if not callable(snapshot):
        return None
    try:
        usage = snapshot()
    except Exception:
        return None
    return copy.deepcopy(usage) if isinstance(usage, dict) else None


def load_actor(task):
    """Resolve the configured deterministic actor or a local JSON actor."""
    spec = _actor_spec(task)
    if spec is None:
        return _deterministic_actions(task), {"actor_id": "deterministic", "config_hash": _config_hash(_deterministic_actions(task))}
    if isinstance(spec, str):
        spec = {"actions_file": spec}
    if not isinstance(spec, dict):
        raise ValueError("actor configuration must be an object or local path")
    actor_id = spec.get("actor_id", spec.get("id"))
    path = spec.get("actions_file", spec.get("actions_path", spec.get("path")))
    actor_type = str(spec.get("type", spec.get("kind", "json" if path else "deterministic"))).lower()
    if actor_type in {"deterministic", "default", "default-deterministic"}:
        actions = spec.get("actions", _deterministic_actions(task))
        if not isinstance(actions, list):
            raise ValueError("deterministic actor actions must be an array")
        return copy.deepcopy(actions), {"actor_id": str(actor_id or "deterministic"), "config_hash": _config_hash(actions)}
    if actor_type in {"python", "py", "stdlib"}:
        if not path:
            raise ValueError("Python actor configuration requires a local path")
        resolved = _resolve_local_path(path)
        actor, source = _load_python_actor(resolved, spec.get("entrypoint", "act"))
        return actor, {"actor_id": str(actor_id or resolved.stem), "config_hash": hashlib.sha256(source.encode("utf-8")).hexdigest()}
    if actor_type not in {"json", "policy", "action_policy"}:
        raise ValueError(f"unsupported actor type: {actor_type}")
    if not path:
        raise ValueError("JSON actor configuration requires an actions_file path")
    resolved = _resolve_local_path(path)
    actions, loaded = _load_json_actor(resolved)
    actor_id = actor_id or "local-json"
    return actions, _actor_meta(actor_id, {"type": "json", "config": loaded})


def request(base, path, payload=None):
    if payload is None:
        req = Request(base + path)
    else:
        data = json.dumps(payload).encode()
        req = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def get(path):
    return request(TASK_ENV_URL, path)


def post(base, path, payload):
    return request(base, path, payload)


def wait_for_dependencies():
    last_failures = []
    for attempt in range(1, STARTUP_RETRIES + 1):
        failures = []
        for name, base in DEPENDENCIES.items():
            try:
                request(base, "/health")
            except Exception as error:
                failures.append(f"{name}: {error}")
        if not failures:
            return
        last_failures = failures
        if attempt < STARTUP_RETRIES:
            time.sleep(STARTUP_RETRY_DELAY)
    details = "; ".join(last_failures)
    raise RuntimeError(
        f"runner startup failed: dependencies unavailable after {STARTUP_RETRIES} attempts: {details}"
    )


def load_batch_spec(path=None):
    """加载批量任务 JSON；支持数组或 {tasks: [...]} 两种格式。"""
    path = path or BATCH_SPEC
    if not path:
        return [{"task_id": "flight-refundable-cheapest", "seed": 0}]
    with open(path, encoding="utf-8") as file:
        payload = json.load(file)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        tasks = payload.get("tasks", payload.get("batch", payload.get("items")))
        if isinstance(tasks, list):
            return tasks
        return [payload]
    raise ValueError("batch spec must be a JSON array or object")


def _run_id(task, index):
    return str(task.get("run_id") or f"{task.get('task_id', 'task')}-{index}-{uuid.uuid4().hex[:8]}")


def _baseline_catalog(task):
    """Resolve the sole allowed catalog for the task's declared evaluation tier."""
    tier = task.get("evaluation_tier")
    if tier is None:
        # Historical local tests can remain executable, but are always tagged as
        # legacy/non-main and cannot pass v2 admission or main-table preflight.
        return PILOT_BASELINE_CATALOG, PILOT_ORACLE_BASELINES
    if tier == "pilot":
        if task.get("baseline_registry_version") != "local-flight-pilot-v1" or task.get("main_comparison") is not False:
            raise ValueError("pilot tasks require local-flight-pilot-v1 and main_comparison=false")
        return PILOT_BASELINE_CATALOG, PILOT_ORACLE_BASELINES
    if tier == "main":
        if not isinstance(task.get("baseline_registry_version"), str) or not task["baseline_registry_version"].strip() or task.get("main_comparison") is not True:
            raise ValueError("main tasks require a frozen baseline registry version and main_comparison=true")
        return MAIN_BASELINE_CATALOG, MAIN_ORACLE_BASELINES
    raise ValueError("evaluation_tier must be pilot or main before requesting baselines")


def run_task(task, index=0):
    task = task if isinstance(task, dict) else {}
    run_id = _run_id(task, index)
    seed = task.get("seed", task.get("env_seed", 0))
    faults = task.get("faults", [])
    reset_payload = dict(task.get("reset", {})) if isinstance(task.get("reset"), dict) else {}
    nested_env_config = task.get("env_config") if isinstance(task.get("env_config"), dict) else {}
    canonical_config = copy.deepcopy(nested_env_config)
    canonical_config.update(copy.deepcopy(reset_payload))
    # Task-level environment settings are sent verbatim to task-env. The
    # evaluator-only fault_truth remains separate from this reset config.
    for key in (
        "task", "origin", "destination", "budget", "flights", "task_variant",
        "variant", "actions", "invariants",
    ):
        if key in task:
            canonical_config[key] = copy.deepcopy(task[key])
    canonical_faults = canonical_config.get("faults", faults)
    canonical_config["faults"] = copy.deepcopy(canonical_faults)
    episode_id = str(task.get("episode_id") or run_id)
    source_contract = environment_contract(
        env_config=canonical_config,
        seed=seed,
        run_id=run_id,
        episode_id=episode_id,
        source_run_id=run_id,
    )
    strict_replay = task.get("strict_replay") is True
    protocol_id = task.get("protocol_id")
    trial_id = task.get("trial_id")
    model_resource_id = task.get("model_resource_id")
    reset_payload = {"run_id": run_id, "seed": seed, "env_config": canonical_config}
    reset_payload.update(copy.deepcopy(canonical_config))
    reset_payload["run_id"] = run_id
    reset_payload["seed"] = seed
    reset_observation = post(TASK_ENV_URL, "/reset", reset_payload)
    trace = []
    actor, actor_meta = load_actor(task)
    if actor is None:
        action_source = iter(_legacy_actions(task))
        dynamic_actor = False
    elif isinstance(actor, list):
        action_source = iter(copy.deepcopy(actor))
        dynamic_actor = False
    elif callable(actor):
        action_source = None
        dynamic_actor = True
    else:
        raise ValueError("actor must provide actions or a callable")
    termination_reason = "actor_stopped"
    while True:
        if dynamic_actor and len(trace) >= MAX_DYNAMIC_STEPS:
            termination_reason = "max_dynamic_steps_exceeded"
            break
        if dynamic_actor:
            context = {"run_id": run_id, "task_id": task.get("task_id", "flight-refundable-cheapest"), "seed": seed, "step_id": len(trace), "trace": copy.deepcopy(trace)}
            action = _actor_actions(actor, reset_observation if not trace else trace[-1].get("observation", {}), context)
            if action is None:
                termination_reason = "actor_returned_none"
                break
            if isinstance(action, list):
                action_source = iter(action)
                dynamic_actor = False
                continue
        else:
            try:
                action = next(action_source)
            except StopIteration:
                break
        if not isinstance(action, dict):
            raise ValueError("actor actions must be objects")
        step = post(TASK_ENV_URL, "/step", {**action, "run_id": run_id})
        if isinstance(step, dict):
            step["actor_id"] = actor_meta["actor_id"]
            step["actor_config_hash"] = actor_meta["config_hash"]
        trace.append(step)
        if not step.get("result", {}).get("ok", True):
            termination_reason = "tool_error"
            break
    original_eval = get(f"/evaluate?run_id={quote(run_id, safe='')}")
    diagnosis = post(DIAGNOSER_URL, "/diagnose", {"trace": trace})
    baseline_catalog, oracle_baselines = _baseline_catalog(task)
    requested_baselines = task.get("baselines", ["recovery"])
    if not isinstance(requested_baselines, list) or not requested_baselines:
        raise ValueError("baselines must be a non-empty list from the frozen baseline catalog")
    if not all(isinstance(baseline_id, str) and baseline_id.strip() for baseline_id in requested_baselines):
        raise ValueError("baseline IDs must be non-empty strings")
    baselines = list(dict.fromkeys(requested_baselines))
    unknown = sorted(set(baselines) - baseline_catalog)
    if unknown:
        raise ValueError(f"baseline IDs are not registered for {task.get('evaluation_tier')}: {', '.join(unknown)}")
    # The task spec's fault_truth is an evaluator-only oracle reference.  The
    # actual environment truth must come from reset; do not let an optional
    # reference field mask the faults that were really injected.
    # The canonical configuration is exactly what was sent to /reset.  The
    # public response is redacted, so it cannot be used to recover truth.
    actual_fault_truth = canonical_faults
    # Oracle-only policies are not part of any deployable/main comparison.
    # Their privileged truth is never sent to raw/recovery baselines.
    oracle_fault_truth = task.get("fault_truth", actual_fault_truth)
    decisions = {}
    counterfactuals = {}
    for baseline_id in baselines:
        if baseline_id == "recovery":
            baseline_decision = post(RECOVERY_URL, "/choose", {"diagnosis": diagnosis, "allow_abstain": True})
            baseline_decision.setdefault("baseline_id", "recovery")
        else:
            baseline_payload = {"baseline_id": baseline_id, "diagnosis": diagnosis}
            if baseline_id in oracle_baselines:
                baseline_payload["fault_truth"] = oracle_fault_truth
            baseline_decision = post(RECOVERY_URL, "/baseline", baseline_payload)
        baseline_counterfactual = None
        if baseline_decision.get("patch") is not None:
            step_id = baseline_decision.get("step_id")
            if isinstance(step_id, int) and 0 <= step_id < len(trace):
                baseline_counterfactual = post(
                    REPLAYER_URL,
                    "/replay",
                    {
                        "run_id": run_id,
                        "episode_id": episode_id,
                        "source_seed": seed,
                        "source_faults": canonical_faults,
                        "env_config": canonical_config,
                        "source_contract": source_contract,
                        "replay_contract": expected_clean_replay_contract(source_contract, f"{run_id}:cf"),
                        "strict_replay": strict_replay,
                        "prefix": trace[:step_id],
                        "patch": baseline_decision["patch"],
                        "suffix": trace[step_id + 1:],
                    },
                )
                baseline_counterfactual["patched_step_id"] = step_id
        decisions[baseline_id] = baseline_decision
        counterfactuals[baseline_id] = baseline_counterfactual
    # Keep the legacy top-level fields as aliases for the recovery baseline.
    decision = decisions.get("recovery") or next(iter(decisions.values()))
    counterfactual = counterfactuals.get("recovery")
    final_observation = original_eval
    result = {
        "run_id": run_id,
        "source_run_id": run_id,
        "episode_id": episode_id,
        "environment_contract": source_contract,
        "strict_replay": strict_replay,
        "protocol_id": protocol_id,
        "trial_id": trial_id,
        "model_resource_id": model_resource_id,
        "main_comparison": task.get("main_comparison", False),
        "legacy": task.get("legacy", task.get("evaluation_tier") is None),
        "evaluation_tier": task.get("evaluation_tier", "unregistered"),
        "baseline_registry_version": task.get("baseline_registry_version"),
        "task_id": task.get("task_id", "flight-refundable-cheapest"),
        "seed": seed,
        "task_variant": task.get("task_variant", task.get("variant", "clean_success")),
        "cell": task.get("cell", task.get("task_variant", task.get("variant", "clean_success"))),
        "actor_id": actor_meta["actor_id"],
        "actor_config_hash": actor_meta["config_hash"],
        "termination_reason": termination_reason,
        "actor_usage": _actor_usage(actor),
        # Written after construction as an immutable provenance anchor that is
        # safe to copy into the evaluator-only oracle manifest.
        # Keep oracle truth out of the agent trajectory artifact. The evaluator
        # should receive it through a separate privileged manifest instead.
        "trace": trace,
        "original_evaluation": original_eval,
        "diagnosis": diagnosis,
        "decision": decision,
        "counterfactual": counterfactual,
        "baselines": {
            baseline_id: {"decision": decisions[baseline_id], "counterfactual": counterfactuals[baseline_id]}
            for baseline_id in baselines
        },
    }
    result["source_manifest_sha256"] = _source_manifest_anchor(result)
    return result


def run():
    wait_for_dependencies()
    tasks = load_batch_spec()
    explicit_ids = [str(item.get("run_id")) for item in tasks if isinstance(item, dict) and item.get("run_id")]
    if len(set(explicit_ids)) != len(explicit_ids):
        raise ValueError("duplicate run_id in batch spec")
    results = [run_task(task, index) for index, task in enumerate(tasks)]
    output = {"count": len(results), "results": results} if len(results) != 1 or BATCH_SPEC else results[0]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    os.makedirs(TRAJECTORY_DIR, exist_ok=True)
    os.makedirs(ORACLE_DIR, exist_ok=True)
    for result, task in zip(results, tasks):
        task = task if isinstance(task, dict) else {}
        reset_spec = task.get("reset") if isinstance(task.get("reset"), dict) else {}
        canonical_faults = reset_spec.get("faults", task.get("faults", []))
        filename = f"{result['run_id'].replace('/', '_')}.json"
        trajectory_path = os.path.join(TRAJECTORY_DIR, filename)
        temp_path = trajectory_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        os.replace(temp_path, trajectory_path)
        oracle_path = os.path.join(ORACLE_DIR, filename)
        oracle_temp_path = oracle_path + ".tmp"
        oracle_entry = {
            "run_id": result["run_id"],
            "source_run_id": result["source_run_id"],
            "episode_id": result["episode_id"],
            "environment_contract": result["environment_contract"],
            "task_id": result["task_id"],
            "seed": result["seed"],
            "env_seed": result["seed"],
            "source_manifest_sha256": _source_manifest_anchor(result),
            "fault_truth": (
                task.get("fault_truth", canonical_faults)
            ),
        }
        with open(oracle_temp_path, "w", encoding="utf-8") as file:
            json.dump(oracle_entry, file, ensure_ascii=False, indent=2)
        os.replace(oracle_temp_path, oracle_path)
    return results


if __name__ == "__main__":
    run()
