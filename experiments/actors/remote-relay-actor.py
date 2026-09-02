"""Remote oneapi-relay LLM actor for the RACER paired pilot.

Calls the relay's Anthropic-native ``/v1/messages`` endpoint with ``tool_use``
blocks. Text-JSON mode is unusable on this relay (responses are markdown
wrapped), and ``/v1/chat/completions`` is not exposed, so this actor speaks
the native protocol directly.

Credentials are read exclusively from the runtime environment variables
ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL (never from the repository).

The actor is self-terminating: it returns ``None`` once the booking is
confirmed, the actor step budget is exhausted, or the model calls the finish
tool. The runner loop has no step cap of its own, so this actor enforces the
pilot's ``max_actor_steps=3`` budget locally.

Known relay defect: auto ``tool_choice`` intermittently returns
``stop_reason=tool_use`` with an empty ``content`` array. The actor retries
the request (same parameters) and counts the defect as an ``empty_tool_use``
event; it never fabricates an action.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

Path(__file__).resolve().parents[2]  # keep project-root anchor importable

_BASE_URL = (os.environ.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
_API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
_MODEL = os.environ.get("RELAY_LLM_MODEL", "Claude Haiku 4.5")
_TIMEOUT_S = float(os.environ.get("RELAY_LLM_TIMEOUT_S", "60"))
_MAX_EMPTY_RETRIES = int(os.environ.get("RELAY_LLM_EMPTY_RETRIES", "4"))
_MAX_ACTOR_STEPS = int(os.environ.get("RELAY_LLM_MAX_ACTOR_STEPS", "3"))
_TEMPERATURE = 0.0
_MAX_TOKENS = 256
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = (
    "You are an airline-booking agent operating a flight-booking toolset. "
    "On every turn you must issue exactly one tool call via the tool_use block. "
    "Follow this strict procedure with the CURRENT observation state:\n"
    "1. If state.confirmed is true, or the previous step returned a booking_id, "
    "call the finish tool.\n"
    "2. If state.selected_flight is null and no previous step selected a flight, "
    "call select_flight. First compute the eligible set: flights where "
    "refundable is true AND price <= budget. Then take the eligible flight with "
    "the MINIMUM price (ties: lowest id) and pass exactly its id. Never select "
    "a non-refundable or over-budget flight even if it is cheaper.\n"
    "3. If a flight is selected but not confirmed, call confirm_booking with "
    "{\"user_confirmed\": true}.\n"
    "4. Only call search_flights if available_flights is empty AND "
    "state.selected_flight is null.\n"
    "Never call confirm_booking before select_flight succeeds. Never invent "
    "flight ids or arguments. Return exactly one tool call per turn."
)


class RelayActorError(RuntimeError):
    """Raised when the relay response cannot be used as a safe action."""


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "search_flights",
            "description": "List available flights with price and refundability. Use only when flight candidates are not already visible in the observation.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "select_flight",
            "description": "Select a flight for booking. flight_id must be one of the listed flights.",
            "input_schema": {
                "type": "object",
                "properties": {"flight_id": {"type": "string", "description": "Flight identifier, e.g. F1"}},
                "required": ["flight_id"],
            },
        },
        {
            "name": "confirm_booking",
            "description": "Confirm the selected booking. Requires explicit user confirmation.",
            "input_schema": {
                "type": "object",
                "properties": {"user_confirmed": {"type": "boolean"}},
                "required": ["user_confirmed"],
            },
        },
        {
            "name": "finish",
            "description": "Signal that the task is complete. Use when the booking is confirmed or no tool can make progress.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
    ]


_ALLOWED_TOOLS = ("search_flights", "select_flight", "confirm_booking", "finish")


def _observation_flights(observation: Mapping[str, Any]) -> list[Any]:
    env_config = observation.get("env_config")
    if isinstance(env_config, Mapping) and isinstance(env_config.get("flights"), list):
        return env_config["flights"]
    return []


def _build_user_content(observation: Mapping[str, Any], context: Mapping[str, Any]) -> list[dict[str, Any]]:
    state = observation.get("state") if isinstance(observation.get("state"), Mapping) else {}
    previous = None
    trace = context.get("trace")
    if isinstance(trace, list) and trace and isinstance(trace[-1], Mapping):
        previous = trace[-1]
    user = {
        "instruction": "Choose the next action for the CURRENT state below. Issue exactly one tool call.",
        "current_state": {
            "task": state.get("task"),
            "budget": state.get("budget"),
            "selected_flight": state.get("selected_flight"),
            "confirmed": state.get("confirmed"),
            "events": state.get("events"),
        },
        "previous_step": (
            {
                "action": previous.get("action"),
                "result": previous.get("result"),
            }
            if previous
            else None
        ),
        "available_flights": _observation_flights(observation),
        "invariants": observation.get("invariants", []),
        "step_id": context.get("step_id"),
        "note": "selected_flight null means no flight is selected yet. Use ids from available_flights only.",
    }
    return [{"type": "text", "text": json.dumps(user, ensure_ascii=False)}]


def _extract_tool_use(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the first tool_use block, or None for an empty-content defect."""
    content = payload.get("content")
    if not isinstance(content, list):
        raise RelayActorError("relay response has no content array")
    for block in content:
        if isinstance(block, Mapping) and block.get("type") == "tool_use":
            return {
                "tool": block.get("name"),
                "arguments": block.get("input") if isinstance(block.get("input"), Mapping) else {},
            }
    return None


def _validate_tool_choice(choice: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if choice is None:
        raise RelayActorError("relay returned no usable tool_use block")
    tool = choice.get("tool")
    if tool not in _ALLOWED_TOOLS:
        raise RelayActorError(f"relay selected unknown tool: {tool}")
    if tool == "finish":
        return None
    arguments = choice.get("arguments")
    if not isinstance(arguments, dict):
        raise RelayActorError("tool arguments must be an object")
    return {"tool": tool, "arguments": arguments}


def _post_messages(messages: list[dict[str, Any]]) -> Mapping[str, Any]:
    if not _BASE_URL or not _API_KEY:
        raise RelayActorError("ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN must be set in the environment")
    payload = {
        "model": _MODEL,
        "max_tokens": _MAX_TOKENS,
        "temperature": _TEMPERATURE,
        "system": SYSTEM_PROMPT,
        "messages": messages,
        "tools": _tool_definitions(),
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": _API_KEY,
        "Authorization": "Bearer " + _API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
    }
    request = Request(_BASE_URL + "/v1/messages", data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=_TIMEOUT_S) as response:
            raw = json.load(response)
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise RelayActorError(f"relay HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RelayActorError(f"relay request failed: {type(exc).__name__}") from exc
    if not isinstance(raw, Mapping):
        raise RelayActorError("relay response must be a JSON object")
    return raw


# --- actor-level usage ledger -------------------------------------------------
# Modeled on the gemma-fault-admission-pilot usage contract. Every HTTP
# request initiated increments calls and attempts; every attempt resolves to
# exactly one of: terminal response, invalid action, empty tool_use defect,
# or endpoint error. The invariants below must all hold.

_ledger = {
    "provider": "anthropic-oneapi-relay",
    "model": _MODEL,
    "base_url": _BASE_URL,
    "calls": 0,
    "attempts": 0,
    "responses": 0,
    "terminal_responses": 0,
    "invalid_actions": 0,
    "endpoint_errors": 0,
    "empty_tool_use": 0,
    "failed_attempts": 0,
    "valid_actions": 0,
    "finish_terminations": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "latency_ms": 0.0,
    "last_call": {},
}
_usage_known = {"prompt_tokens": True, "completion_tokens": True}


def _record_terminal(payload: Mapping[str, Any], latency_ms: float) -> None:
    _ledger["responses"] += 1
    _ledger["terminal_responses"] += 1
    _accumulate_usage(payload, latency_ms)


def _record_invalid(payload: Mapping[str, Any], latency_ms: float) -> None:
    _ledger["responses"] += 1
    _ledger["invalid_actions"] += 1
    _ledger["failed_attempts"] += 1
    _accumulate_usage(payload, latency_ms)


def _record_empty(latency_ms: float) -> None:
    _ledger["responses"] += 1
    _ledger["empty_tool_use"] += 1
    _ledger["failed_attempts"] += 1
    _ledger["latency_ms"] += latency_ms


def _record_endpoint_error() -> None:
    _ledger["endpoint_errors"] += 1
    _ledger["failed_attempts"] += 1


def _accumulate_usage(payload: Mapping[str, Any], latency_ms: float) -> None:
    _ledger["latency_ms"] += latency_ms
    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        prompt = usage.get("input_tokens")
        completion = usage.get("output_tokens")
        if isinstance(prompt, int):
            _ledger["prompt_tokens"] += prompt
        else:
            _usage_known["prompt_tokens"] = False
        if isinstance(completion, int):
            _ledger["completion_tokens"] += completion
        else:
            _usage_known["completion_tokens"] = False
    else:
        _usage_known["prompt_tokens"] = False
        _usage_known["completion_tokens"] = False
    _ledger["last_call"] = {
        "latency_ms": round(latency_ms, 3),
        "call_index": _ledger["calls"],
        "stop_reason": payload.get("stop_reason"),
    }


def _usage_invariants() -> list[dict[str, Any]]:
    ledger = _ledger
    return [
        {"name": "calls = attempts", "holds": ledger["calls"] == ledger["attempts"]},
        {"name": "attempts = terminal_responses + failed_attempts", "holds": ledger["attempts"] == ledger["terminal_responses"] + ledger["failed_attempts"]},
        {"name": "responses = terminal_responses + invalid_actions + empty_tool_use", "holds": ledger["responses"] == ledger["terminal_responses"] + ledger["invalid_actions"] + ledger["empty_tool_use"]},
        {"name": "failed_attempts = endpoint_errors + invalid_actions + empty_tool_use", "holds": ledger["failed_attempts"] == ledger["endpoint_errors"] + ledger["invalid_actions"] + ledger["empty_tool_use"]},
        {"name": "responses + endpoint_errors = attempts", "holds": ledger["responses"] + ledger["endpoint_errors"] == ledger["attempts"]},
        {"name": "valid_actions + finish_terminations = terminal_responses", "holds": ledger["valid_actions"] + ledger["finish_terminations"] == ledger["terminal_responses"]},
    ]


def _termination_reason(observation: Mapping[str, Any], context: Mapping[str, Any]) -> str | None:
    state = observation.get("state") if isinstance(observation.get("state"), Mapping) else {}
    step_id = context.get("step_id")
    if state.get("confirmed") is True:
        return "confirmed"
    if isinstance(step_id, int) and step_id >= _MAX_ACTOR_STEPS:
        return "step_budget"
    return None


def _conversation(trace) -> list[dict[str, Any]]:
    """Rebuild a minimal Anthropic conversation from the runner trace."""
    messages: list[dict[str, Any]] = []
    if not isinstance(trace, list):
        return messages
    for step in trace:
        if not isinstance(step, Mapping):
            continue
        action = step.get("action")
        if not (isinstance(action, Mapping) and action.get("tool") in ("search_flights", "select_flight", "confirm_booking")):
            continue
        tool_use_id = f"toolu_{len(messages)}"
        messages.append({
            "role": "assistant",
            "content": [{"type": "tool_use", "tool_use_id": tool_use_id, "name": action.get("tool"), "input": action.get("arguments", {})}],
        })
        messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(step.get("result", {}), ensure_ascii=False)}],
        })
    return messages


def act(observation, context):
    """Return the next action dict, or None to terminate the episode."""
    reason = _termination_reason(observation, context)
    if reason is not None:
        _ledger["termination_reason"] = reason
        return None

    messages = _conversation(context.get("trace"))
    messages.append({"role": "user", "content": _build_user_content(observation, context)})

    last_error: Exception | None = None
    for _attempt in range(_MAX_EMPTY_RETRIES + 1):
        _ledger["calls"] += 1
        _ledger["attempts"] += 1
        started = time.perf_counter()
        try:
            payload = _post_messages(messages)
        except RelayActorError as exc:
            last_error = exc
            _record_endpoint_error()
            continue
        latency_ms = (time.perf_counter() - started) * 1000.0
        choice = _extract_tool_use(payload)
        if choice is None:
            # Relay defect: stop_reason=tool_use with empty content.
            _record_empty(latency_ms)
            continue
        try:
            action = _validate_tool_choice(choice)
        except RelayActorError as exc:
            last_error = exc
            _record_invalid(payload, latency_ms)
            continue
        _record_terminal(payload, latency_ms)
        if action is None:
            _ledger["finish_terminations"] += 1
            _ledger["termination_reason"] = "finish_tool"
        else:
            _ledger["valid_actions"] += 1
        return action
    raise RelayActorError(
        f"relay did not produce a usable tool call after {_MAX_EMPTY_RETRIES + 1} attempts: {last_error}"
    )


def usage_snapshot():
    snapshot = {key: _ledger[key] for key in (
        "provider", "model", "base_url", "calls", "attempts", "responses",
        "terminal_responses", "invalid_actions", "endpoint_errors", "empty_tool_use",
        "failed_attempts", "valid_actions", "finish_terminations",
        "prompt_tokens", "completion_tokens", "latency_ms", "last_call",
    )}
    if _usage_known["prompt_tokens"] and _usage_known["completion_tokens"]:
        snapshot["total_tokens"] = _ledger["prompt_tokens"] + _ledger["completion_tokens"]
    else:
        snapshot["total_tokens"] = None
        snapshot["prompt_tokens"] = _ledger["prompt_tokens"] if _usage_known["prompt_tokens"] else None
        snapshot["completion_tokens"] = _ledger["completion_tokens"] if _usage_known["completion_tokens"] else None
    if "termination_reason" in _ledger:
        snapshot["termination_reason"] = _ledger["termination_reason"]
    snapshot["invariants"] = _usage_invariants()
    snapshot["all_invariants_hold"] = all(item["holds"] for item in snapshot["invariants"])
    return snapshot


def actor_identity():
    return {
        "actor_id": "relay-llm-paired-pilot",
        "provider": "anthropic-oneapi-relay",
        "model": _MODEL,
        "base_url_origin": _BASE_URL,
        "protocol": "anthropic-native /v1/messages + tool_use",
    }
