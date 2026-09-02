"""RACER v2 的离线环境与配对运行契约。

本模块只处理 JSON 兼容元数据和哈希，不导入 benchmark、网络客户端或模型。
指纹用于审计是否由同一初始环境、同一故障日程和同一源 episode 派生；它们不
替代环境快照，也不向智能体公开 evaluator-only 的 fault truth。
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

CONTRACT_VERSION = "racer-v2-environment-contract"


def canonical_json(value: Any) -> str:
    """Return deterministic JSON for hashable, JSON-compatible values."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, Mapping) else {}


def _initial_environment(env_config: Any) -> dict[str, Any]:
    """Keep all reset inputs except evaluator-only fault scheduling."""
    value = _mapping(env_config)
    nested = value.get("env_config")
    if isinstance(nested, Mapping):
        value = {**_mapping(nested), **{key: item for key, item in value.items() if key != "env_config"}}
    value.pop("faults", None)
    return value


def _fault_schedule(env_config: Any) -> list[Any]:
    value = _mapping(env_config)
    nested = value.get("env_config")
    if isinstance(nested, Mapping):
        value = {**_mapping(nested), **{key: item for key, item in value.items() if key != "env_config"}}
    faults = value.get("faults", [])
    if isinstance(faults, Mapping):
        return [copy.deepcopy(faults)]
    return copy.deepcopy(faults) if isinstance(faults, list) else []


def environment_contract(
    *,
    env_config: Any,
    seed: Any,
    run_id: Any,
    episode_id: Any = None,
    source_run_id: Any = None,
) -> dict[str, Any]:
    """Build the v2 provenance block for one source or replay execution."""
    source = str(source_run_id if source_run_id is not None else run_id)
    episode = str(episode_id if episode_id is not None else source)
    initial = _initial_environment(env_config)
    schedule = _fault_schedule(env_config)
    return {
        "contract_version": CONTRACT_VERSION,
        "episode_id": episode,
        "source_run_id": source,
        "run_id": str(run_id),
        "env_seed": seed,
        "initial_state_fingerprint": fingerprint({"seed": seed, "environment": initial}),
        "fault_schedule_fingerprint": fingerprint(schedule),
        "environment_fingerprint": fingerprint({"seed": seed, "environment": initial, "fault_schedule": schedule}),
    }


def paired_identity(value: Mapping[str, Any], baseline_id: Any = None) -> tuple[str, str, str, str, str, str] | None:
    """Return a complete v2 pairing key, or None when the artifact is legacy/incomplete."""
    contract = value.get("environment_contract") if isinstance(value.get("environment_contract"), Mapping) else value
    episode = contract.get("episode_id")
    source_run = contract.get("source_run_id")
    seed = contract.get("env_seed", contract.get("seed"))
    initial = contract.get("initial_state_fingerprint")
    schedule = contract.get("fault_schedule_fingerprint")
    task = value.get("task_id", contract.get("task_id"))
    if any(item is None or str(item) == "" for item in (episode, source_run, task, seed, initial, schedule)):
        return None
    return (
        str(episode),
        str(source_run),
        str(task),
        canonical_json(seed),
        str(initial),
        str(schedule),
    )


def expected_clean_replay_contract(source_contract: Mapping[str, Any], replay_run_id: Any) -> dict[str, Any]:
    """Derive immutable identity facts that must survive clean counterfactual replay."""
    return {
        "contract_version": source_contract.get("contract_version", CONTRACT_VERSION),
        "episode_id": source_contract.get("episode_id"),
        "source_run_id": source_contract.get("source_run_id"),
        "source_environment_fingerprint": source_contract.get("environment_fingerprint"),
        "initial_state_fingerprint": source_contract.get("initial_state_fingerprint"),
        "fault_schedule_fingerprint": source_contract.get("fault_schedule_fingerprint"),
        "replay_run_id": str(replay_run_id),
    }


def validate_replay_contract(source_contract: Mapping[str, Any], provided: Any, replay_run_id: Any) -> tuple[bool, str | None]:
    """Fail closed for v2 replay when provenance is absent or inconsistent."""
    if not isinstance(provided, Mapping):
        return False, "missing_replay_contract"
    expected = expected_clean_replay_contract(source_contract, replay_run_id)
    for key, expected_value in expected.items():
        if expected_value is None or provided.get(key) != expected_value:
            return False, f"replay_contract_mismatch:{key}"
    return True, None
