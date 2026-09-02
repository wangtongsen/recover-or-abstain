"""Minimal, auditable LLM actor for local Ollama/OpenAI-compatible endpoints.

The actor is intentionally independent from the deterministic runner by default.
It exposes a Python callable interface compatible with ``agent_runner.load_actor``
and records usage/latency without persisting prompts, responses, or credentials.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_TOOLS = ("search_flights", "select_flight", "confirm_booking")


class LLMActorError(RuntimeError):
    """Raised when an endpoint response cannot be used as a safe action."""


@dataclass(frozen=True)
class LLMActorConfig:
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:0.6b"
    timeout_s: float = 30.0
    max_retries: int = 1
    temperature: float = 0.0
    max_tokens: int = 256
    input_cost_usd_per_1k: float | None = None
    output_cost_usd_per_1k: float | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "LLMActorConfig":
        env = environ or os.environ
        base_url = env.get("LLM_BASE_URL") or env.get("OLLAMA_HOST") or cls.base_url
        if not base_url.startswith(("http://", "https://")):
            base_url = "http://" + base_url
        provider = env.get("LLM_PROVIDER", "ollama" if ":11434" in base_url else "openai_compatible")
        return cls(
            provider=provider,
            base_url=base_url.rstrip("/"),
            model=env.get("LLM_MODEL") or env.get("OLLAMA_MODEL") or cls.model,
            timeout_s=_float_env(env, "LLM_TIMEOUT_S", cls.timeout_s),
            max_retries=max(0, _int_env(env, "LLM_MAX_RETRIES", cls.max_retries)),
            temperature=_float_env(env, "LLM_TEMPERATURE", cls.temperature),
            max_tokens=max(1, _int_env(env, "LLM_MAX_TOKENS", cls.max_tokens)),
            input_cost_usd_per_1k=_optional_float_env(env, "LLM_INPUT_COST_USD_PER_1K"),
            output_cost_usd_per_1k=_optional_float_env(env, "LLM_OUTPUT_COST_USD_PER_1K"),
        )


def _float_env(env: Mapping[str, str], key: str, default: float) -> float:
    try:
        return float(env.get(key, default))
    except (TypeError, ValueError):
        return default


def _int_env(env: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(env.get(key, default))
    except (TypeError, ValueError):
        return default


def _optional_float_env(env: Mapping[str, str], key: str) -> float | None:
    value = env.get(key)
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _safe_origin(url: str) -> str:
    """Return origin only; never expose query/fragment credentials."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("LLM_BASE_URL must be an http(s) URL with a hostname")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


def _extract_content(payload: Mapping[str, Any], provider: str) -> str:
    if provider.lower() in {"ollama", "local", "ollama_chat"}:
        message = payload.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
    else:
        choices = payload.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get("message") if isinstance(first, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content.strip():
        raise LLMActorError("endpoint returned no textual message content")
    return content.strip()


def _extract_usage(payload: Mapping[str, Any], provider: str) -> dict[str, int | None]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    if provider.lower() in {"ollama", "local", "ollama_chat"}:
        prompt = payload.get("prompt_eval_count")
        completion = payload.get("eval_count")
    else:
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
    prompt = prompt if isinstance(prompt, int) and prompt >= 0 else None
    completion = completion if isinstance(completion, int) and completion >= 0 else None
    total = prompt + completion if prompt is not None and completion is not None else None
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


class StructuredLLMActor:
    """Callable actor returning one validated action per observation."""

    def __init__(self, config: LLMActorConfig | None = None, tools: tuple[str, ...] = DEFAULT_TOOLS):
        self.config = config or LLMActorConfig.from_env()
        self.tools = tuple(tools)
        self._calls = 0
        self._usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._usage_known = {key: True for key in self._usage}
        self._latency_ms = 0.0
        self._last_usage: dict[str, Any] = {}

    @property
    def actor_id(self) -> str:
        return f"llm:{self.config.provider}:{self.config.model}"

    def _endpoint(self) -> tuple[str, bool]:
        origin = _safe_origin(self.config.base_url)
        provider = self.config.provider.lower()
        is_ollama = provider in {"ollama", "local", "ollama_chat"} or ":11434" in origin
        if is_ollama:
            return origin + "/api/chat", True
        return origin + "/v1/chat/completions", False

    def _messages(self, observation: Mapping[str, Any], context: Mapping[str, Any]) -> list[dict[str, str]]:
        state = observation.get("state") if isinstance(observation.get("state"), Mapping) else {}
        task = state.get("task", "")
        invariants = observation.get("invariants", [])
        tools = observation.get("tools", list(self.tools))
        trace = context.get("trace")
        previous = trace[-1] if isinstance(trace, list) and trace and isinstance(trace[-1], Mapping) else None
        instruction = (
            "You are a tool-calling agent. Return exactly one JSON object and no markdown. "
            "For a tool call use {\"tool\": \"<name>\", \"arguments\": {}}. "
            "Use {\"done\": true} only when state.confirmed is true or no listed tool can make progress; "
            "if state.confirmed is false, select a listed tool instead. "
            "Use only the listed tools and never invent tool names. Follow this order: "
            "when selected_flight is null and no previous search result exists, call search_flights; "
            "after search, choose the cheapest eligible flight and call select_flight with its id; "
            "only after a valid selection call confirm_booking with {\"user_confirmed\":true}. "
            "Never call confirm_booking before select_flight succeeds."
        )
        user = {
            "task": task,
            "observation": observation,
            "previous_step": previous,
            "tools": tools,
            "invariants": invariants,
            "step_id": context.get("step_id"),
        }
        return [{"role": "system", "content": instruction}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]

    def _request(self, observation: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[Mapping[str, Any], float]:
        endpoint, is_ollama = self._endpoint()
        messages = self._messages(observation, context)
        if is_ollama:
            payload: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "stream": False,
                "format": "json",
                # Qwen3 models may spend the full budget in a hidden thinking
                # channel; disable it so the structured action is returned in
                # message.content for the actor contract.
                "think": False,
                "options": {"temperature": self.config.temperature, "num_predict": self.config.max_tokens},
            }
        else:
            payload = {
                "model": self.config.model,
                "messages": messages,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "response_format": {"type": "json_object"},
            }
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if api_key and not is_ollama:
            headers["Authorization"] = "Bearer " + api_key
        request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=self.config.timeout_s) as response:
                raw = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise LLMActorError(f"LLM endpoint request failed: {type(exc).__name__}") from exc
        latency_ms = (time.perf_counter() - started) * 1000.0
        if not isinstance(raw, Mapping):
            raise LLMActorError("LLM endpoint response must be an object")
        return raw, latency_ms

    def _validate_action(self, content: str) -> dict[str, Any] | None:
        if content.startswith("```") or content.endswith("```"):
            raise LLMActorError("markdown-wrapped output is not accepted")
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMActorError("model output is not valid JSON") from exc
        if not isinstance(value, dict):
            raise LLMActorError("model output must be a JSON object")
        if value.get("done") is True:
            return None
        tool = value.get("tool")
        arguments = value.get("arguments", {})
        if not isinstance(tool, str) or tool not in self.tools:
            raise LLMActorError("model selected an unknown tool")
        if not isinstance(arguments, dict):
            raise LLMActorError("tool arguments must be an object")
        return {"tool": tool, "arguments": arguments}

    def __call__(self, observation: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any] | None:
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                raw, latency_ms = self._request(observation, context)
                content = _extract_content(raw, self.config.provider)
                action = self._validate_action(content)
                usage = _extract_usage(raw, self.config.provider)
                self._record(usage, latency_ms)
                self._last_usage = {**usage, "latency_ms": round(latency_ms, 3), "call_index": self._calls}
                return action
            except LLMActorError as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    raise
        raise LLMActorError(str(last_error) if last_error else "LLM actor failed")

    def _record(self, usage: Mapping[str, int | None], latency_ms: float) -> None:
        self._calls += 1
        self._latency_ms += latency_ms
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                self._usage[key] += value
            else:
                self._usage_known[key] = False

    def usage_snapshot(self) -> dict[str, Any]:
        input_cost = self.config.input_cost_usd_per_1k
        output_cost = self.config.output_cost_usd_per_1k
        cost = None
        if input_cost is not None and output_cost is not None and self._usage_known["prompt_tokens"] and self._usage_known["completion_tokens"]:
            cost = (self._usage["prompt_tokens"] / 1000.0) * input_cost + (self._usage["completion_tokens"] / 1000.0) * output_cost
        return {
            "provider": self.config.provider,
            "model": self.config.model,
            "base_url": _safe_origin(self.config.base_url),
            "calls": self._calls,
            "prompt_tokens": self._usage["prompt_tokens"] if self._usage_known["prompt_tokens"] else None,
            "completion_tokens": self._usage["completion_tokens"] if self._usage_known["completion_tokens"] else None,
            "total_tokens": self._usage["total_tokens"] if self._usage_known["total_tokens"] else None,
            "cost_usd": round(cost, 8) if cost is not None else None,
            "latency_ms": round(self._latency_ms, 3),
            "last_call": dict(self._last_usage),
        }


def build_actor(observation: Mapping[str, Any] | None = None, context: Mapping[str, Any] | None = None) -> StructuredLLMActor:
    """Factory for Python actor configs; the returned object is directly callable."""
    return StructuredLLMActor()
