#!/usr/bin/env python3
"""Probe: replicate the E1 replace_action episode against the live relay.

Drives task-env (localhost:18080) + the real actor module turn by turn,
logging every relay attempt's stop_reason and content block types so we can
see exactly which turn and which response shape triggers the empty-tool_use
defect. Run with RELAY_* and ANTHROPIC_* env vars set.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.request

_ACTOR_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "experiments", "actors", "remote-relay-actor.py")
)
_spec = importlib.util.spec_from_file_location("remote_relay_actor", _ACTOR_PATH)
actor = importlib.util.module_from_spec(_spec)
sys.modules["remote_relay_actor"] = actor
_spec.loader.exec_module(actor)

TASK_ENV = "http://localhost:18080"
ENV_CONFIG = {
    "budget": 500,
    "flights": [
        {"id": "F1", "price": 420, "refundable": True},
        {"id": "F2", "price": 360, "refundable": False},
        {"id": "F3", "price": 480, "refundable": True},
    ],
    "task_variant": "e1_replace_action",
    "variant": "e1_replace_action",
    "faults": [
        {
            "fault_id": "replace_action-0",
            "type": "replace_action",
            "step_id": 1,
            "replacement": {"tool": "select_flight", "arguments": {"flight_id": "F1"}},
            "tool": "confirm_booking",
        }
    ],
}


def post(path, payload):
    req = urllib.request.Request(
        TASK_ENV + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def get(path):
    with urllib.request.urlopen(TASK_ENV + path, timeout=10) as response:
        return json.load(response)


def instrumented_post(messages, temperature=None):
    """Call the relay with the actor's payload shape but log response details."""
    import time
    started = time.perf_counter()
    payload = {
        "model": actor._MODEL,
        "max_tokens": actor._MAX_TOKENS,
        "temperature": actor._TEMPERATURE if temperature is None else temperature,
        "system": actor.SYSTEM_PROMPT,
        "messages": messages,
        "tools": actor._tool_definitions(),
    }
    request = urllib.request.Request(
        actor._BASE_URL + "/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": actor._API_KEY,
            "Authorization": "Bearer " + actor._API_KEY,
            "anthropic-version": actor.ANTHROPIC_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=actor._TIMEOUT_S) as response:
            raw = json.load(response)
    except Exception as exc:
        print(f"    PROBE http error: {exc}")
        raise
    latency = (time.perf_counter() - started) * 1000
    blocks = [
        f"{b.get('type')}({len(json.dumps(b))}B)"
        for b in raw.get("content", [])
        if isinstance(b, dict)
    ]
    usage = raw.get("usage", {})
    print(
        f"    stop_reason={raw.get('stop_reason')} blocks=[{', '.join(blocks) or 'EMPTY'}] "
        f"in={usage.get('input_tokens')} out={usage.get('output_tokens')} latency={latency:.0f}ms"
    )
    return raw


def main() -> int:
    # Monkeypatch _post_messages so every actor attempt is logged.
    actor._post_messages = instrumented_post
    actor._MAX_ACTOR_STEPS = 6

    reset = post("/reset", {"env_config": ENV_CONFIG, "seed": 0, "run_id": "probe-e1-replace-0"})
    observation = reset.get("observation", reset)
    context = {"run_id": "probe-e1-replace-0", "task_id": "probe", "seed": 0, "trace": []}
    trace = []
    for step in range(6):
        print(f"== turn {step} ==")
        context["step_id"] = len(trace)
        context["trace"] = trace
        action = actor.act(observation if not trace else trace[-1].get("observation", {}), context)
        print(f"  actor -> {action}")
        if action is None:
            break
        result = post("/step", {**action, "run_id": "probe-e1-replace-0"})
        result["observation"] = get(f"/observe?run_id=probe-e1-replace-0").get("observation", {})
        trace.append(result)
        print(f"  env ok={result.get('result', {}).get('ok')} effective={result.get('action')}")
        if not result.get("result", {}).get("ok", True):
            break
    evaluation = get("/evaluate?run_id=probe-e1-replace-0")
    print("evaluation:", json.dumps(evaluation, ensure_ascii=False)[:300])
    print("usage ledger:", json.dumps(actor.usage_snapshot(), ensure_ascii=False)[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
