"""最小、可审计的 tau2 airline adapter 边界。

该模块默认不导入 tau2，也不启动 benchmark。未安装 tau2 时仍可执行
import smoke 和离线轨迹转换；live 环境只有在显式注入 factory/loader 后才会启用。
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Mapping, Sequence


BENCHMARK_REPOSITORY = "sierra-research/tau2-bench"
BENCHMARK_VERSION = "1.0.1"
BENCHMARK_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
ADAPTER_VERSION = "0.1.0"
SCHEMA_VERSION = "tau2-airline-trajectory-v1"


@dataclass(frozen=True)
class BenchmarkSpec:
    repository: str = BENCHMARK_REPOSITORY
    version: str = BENCHMARK_VERSION
    commit: str = BENCHMARK_COMMIT
    python_requires: str = ">=3.12,<3.14"
    domain: str = "airline"


SPEC = BenchmarkSpec()


def tau2_import_status() -> dict[str, Any]:
    """返回不触发导入副作用的本地 tau2 可用性检查。"""
    spec = importlib.util.find_spec("tau2")
    return {
        "available": spec is not None,
        "package": "tau2",
        "required_version": SPEC.version,
        "benchmark_commit": SPEC.commit,
        "python_requires": SPEC.python_requires,
        "live_benchmark_executed": False,
    }


def stable_task_id(task_split: str, task_index: int | str) -> str:
    """按官方任务列表索引生成稳定 ID，不使用 user/reservation ID。"""
    if not task_split or not isinstance(task_split, str):
        raise ValueError("task_split must be a non-empty string")
    try:
        index = int(task_index)
    except (TypeError, ValueError) as exc:
        raise ValueError("task_index must be an integer") from exc
    if index < 0:
        raise ValueError("task_index must be non-negative")
    return f"airline-{task_split}-{index}"


def _state_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def refund_entity_id(action: Mapping[str, Any]) -> str | None:
    """Extract a stable idempotency entity without relying on a global flag."""
    if not isinstance(action, Mapping):
        return None
    arguments = action.get("arguments", action.get("args", {}))
    if not isinstance(arguments, Mapping):
        return None
    for key in ("refund_entity_id", "idempotency_key", "refund_id"):
        value = arguments.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def validate_refund_witness(response: Mapping[str, Any], *, refund_entity: str) -> dict[str, Any]:
    """Validate public evidence for a refund or its idempotent replay.

    A stable entity ID plus a non-empty ledger witness is the minimum evidence
    accepted by strict replay.  This function deliberately does not assume that
    an HTTP success response proves that a side effect was applied.
    """
    if not isinstance(response, Mapping):
        return {"valid": False, "reason": "response_not_mapping"}
    entity = response.get("refund_entity_id")
    witness = response.get("ledger_witness")
    count = response.get("ledger_entry_count")
    if entity != refund_entity:
        return {"valid": False, "reason": "refund_entity_mismatch"}
    if not isinstance(witness, str) or not witness:
        return {"valid": False, "reason": "missing_ledger_witness"}
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        return {"valid": False, "reason": "invalid_ledger_entry_count"}
    return {
        "valid": True,
        "refund_entity_id": entity,
        "ledger_witness": witness,
        "ledger_entry_count": count,
        "idempotent_replay": response.get("idempotent_replay") is True,
    }


def _action_from_step(step: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in ("requested_action", "action", "tool_call"):
        value = step.get(key)
        if isinstance(value, Mapping) and "tool" in value:
            return value
    return None


def convert_offline_record(
    record: Mapping[str, Any],
    *,
    task_split: str,
    task_index: int | str,
) -> dict[str, Any]:
    """将已授权的本地/历史记录转换为 RACER 轨迹字段。

    转换不会计算成功率，也不会把缺失的 reward、truth 或 side effect 补成
    推测值；没有可靠来源的字段保持 None。输出明确标记为 offline。
    """
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    task_id = stable_task_id(task_split, task_index)
    source_trace = record.get("trace", record.get("trajectory", []))
    if not isinstance(source_trace, Sequence) or isinstance(source_trace, (str, bytes)):
        raise ValueError("trace must be a sequence")

    converted_trace: list[dict[str, Any]] = []
    for step_id, raw_step in enumerate(source_trace):
        if not isinstance(raw_step, Mapping):
            raise ValueError(f"trace step {step_id} must be an object")
        requested = _action_from_step(raw_step)
        result = raw_step.get("result")
        observation = raw_step.get("observation")
        before = raw_step.get("state_hash_before", raw_step.get("state_before_hash"))
        after = raw_step.get("state_hash_after", raw_step.get("state_after_hash"))
        if before is None and "state_before" in raw_step:
            before = _state_hash(raw_step["state_before"])
        if after is None and "state_after" in raw_step:
            after = _state_hash(raw_step["state_after"])
        converted_trace.append(
            {
                "step_id": step_id,
                "requested_action": requested,
                "result": result,
                "observation": observation,
                "state_hash_before": before,
                "state_hash_after": after,
            }
        )

    original_evaluation = record.get("original_evaluation")
    if not isinstance(original_evaluation, Mapping):
        original_evaluation = None

    return {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "benchmark_repository": SPEC.repository,
        "benchmark_version": SPEC.version,
        "benchmark_commit": SPEC.commit,
        "domain": SPEC.domain,
        "task_split": task_split,
        "task_index": int(task_index),
        "task_id": task_id,
        "run_id": record.get("run_id"),
        "seed": record.get("seed"),
        "generated_at": record.get("generated_at"),
        "offline": True,
        "live_benchmark_executed": False,
        "trace": converted_trace,
        "original_evaluation": dict(original_evaluation) if original_evaluation is not None else None,
        "reward": record.get("reward"),
        "termination_reason": record.get("termination_reason"),
        "info": record.get("info") if isinstance(record.get("info"), Mapping) else None,
    }


class Tau2AirlineAdapter:
    """可选 live 客户端的窄接口；不注入 factory 时拒绝启动。"""

    REFUND_TOOLS = frozenset({"refund", "refund_booking", "cancel_and_refund"})

    def __init__(
        self,
        *,
        environment_factory: Callable[..., Any] | None = None,
        task_loader: Callable[[str], Sequence[Any]] | None = None,
        task_split: str = "base",
    ) -> None:
        self.environment_factory = environment_factory
        self.task_loader = task_loader
        self.task_split = task_split
        self._environment: Any | None = None
        self._run_id: str | None = None
        self._task_index: int | None = None
        self._refund_witnesses: dict[str, str] = {}

    def _require_live_hooks(self) -> None:
        if self.environment_factory is None or self.task_loader is None:
            raise RuntimeError(
                "live tau2 adapter requires explicit environment_factory and task_loader; "
                "installing dependencies or using credentials is intentionally out of scope"
            )

    def reset(self, task_index: int, task_split: str | None = None, seed: int | None = None) -> tuple[Any, str]:
        self._require_live_hooks()
        split = task_split or self.task_split
        tasks = self.task_loader(split)
        task = tasks[task_index]
        self._environment = self.environment_factory(task=task, seed=seed)
        self._task_index = int(task_index)
        self._run_id = stable_task_id(split, task_index)
        self._refund_witnesses = {}
        observation = self.observe(self._run_id)
        return observation, self._run_id

    def observe(self, run_id: str) -> Any:
        if run_id != self._run_id or self._environment is None:
            raise KeyError(f"unknown run_id: {run_id}")
        if not hasattr(self._environment, "observe"):
            raise TypeError("injected tau2 environment does not expose observe()")
        return self._environment.observe()

    def step(self, run_id: str, tool: str, arguments: Mapping[str, Any]) -> Any:
        if run_id != self._run_id or self._environment is None:
            raise KeyError(f"unknown run_id: {run_id}")
        if not isinstance(tool, str) or not tool:
            raise ValueError("tool must be a non-empty string")
        action = {"tool": tool, "arguments": dict(arguments)}
        if not hasattr(self._environment, "step"):
            raise TypeError("injected tau2 environment does not expose step()")
        response = self._environment.step(action)
        if tool not in self.REFUND_TOOLS:
            return response
        entity = refund_entity_id(action)
        if entity is None:
            raise ValueError("refund actions require refund_entity_id, idempotency_key, or refund_id")
        if not isinstance(response, Mapping):
            return response
        response = dict(response)
        witness = validate_refund_witness(response, refund_entity=entity)
        if witness["valid"]:
            prior = self._refund_witnesses.get(entity)
            if prior is not None and prior != witness["ledger_witness"]:
                raise RuntimeError("refund entity produced inconsistent ledger witnesses")
            self._refund_witnesses[entity] = witness["ledger_witness"]
            return response
        # A response loss is not evidence that no side effect committed. Return
        # the unaltered response so callers must explicitly reconcile through a
        # domain status endpoint before retrying.
        if response.get("response_lost") is True or response.get("retryable") is True:
            return response
        raise RuntimeError(f"refund response lacks verifiable witness: {witness['reason']}")

    def evaluate(self, run_id: str) -> Any:
        if run_id != self._run_id or self._environment is None:
            raise KeyError(f"unknown run_id: {run_id}")
        if not hasattr(self._environment, "evaluate"):
            raise TypeError("injected tau2 environment does not expose evaluate()")
        return self._environment.evaluate()


if __name__ == "__main__":
    print(json.dumps(tau2_import_status(), indent=2, sort_keys=True))
