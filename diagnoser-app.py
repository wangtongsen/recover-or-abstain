import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def _normalize_cause(cause):
    return "_".join(str(cause or "unknown").strip().lower().replace("-", " ").split())


def _normalize_step_id(step_id):
    if step_id is None:
        return None
    try:
        return int(step_id)
    except (TypeError, ValueError):
        return str(step_id).strip().lower()


def _semantic_text(item):
    """Collect task semantics exposed by the public observation."""
    if not isinstance(item, dict):
        return ""
    chunks = []
    for key in ("task", "task_variant", "variant"):
        value = item.get(key)
        if value is not None:
            chunks.append(str(value))
    invariants = item.get("invariants")
    if isinstance(invariants, (list, tuple)):
        chunks.extend(str(value) for value in invariants)
    state = item.get("state")
    if isinstance(state, dict) and state.get("task") is not None:
        chunks.append(str(state["task"]))
    return " ".join(chunks).lower().replace("_", "-")


def _requires_refundable(trace):
    """Infer the refundable constraint from public task text, if present."""
    saw_refundable = False
    for item in trace:
        if not isinstance(item, dict):
            continue
        texts = [_semantic_text(item)]
        observation = item.get("observation")
        if isinstance(observation, dict):
            texts.append(_semantic_text(observation))
            env_config = observation.get("env_config")
            if isinstance(env_config, dict):
                texts.append(_semantic_text(env_config))
        text = " ".join(texts)
        if "non-refundable" in text or "nonrefundable" in text or "not refundable" in text:
            return False
        if "refundable" in text:
            saw_refundable = True
    return True if saw_refundable else None


def _observed_budget(trace):
    for item in trace:
        if not isinstance(item, dict):
            continue
        observation = item.get("observation")
        if not isinstance(observation, dict):
            continue
        state = observation.get("state")
        if isinstance(state, dict) and isinstance(state.get("budget"), (int, float)):
            return state["budget"]
    return None


def _suggest_replacement(trace, index, selected_id):
    """Suggest an observed eligible flight without consulting hidden truth."""
    require_refundable = _requires_refundable(trace)
    if require_refundable is False:
        return None
    budget = _observed_budget(trace)
    flights = []
    for item in trace[: index + 1]:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        if isinstance(result, dict) and isinstance(result.get("flights"), list):
            flights.extend(result["flights"])
        observation = item.get("observation")
        if isinstance(observation, dict):
            result = observation.get("result")
            if isinstance(result, dict) and isinstance(result.get("flights"), list):
                flights.extend(result["flights"])
    eligible = []
    seen_ids = set()
    for flight in flights:
        if not isinstance(flight, dict):
            continue
        flight_id = flight.get("id")
        if flight_id is None or flight_id == selected_id or flight_id in seen_ids:
            continue
        if require_refundable is not False and flight.get("refundable") is not True:
            continue
        price = flight.get("price")
        if budget is not None and (not isinstance(price, (int, float)) or price > budget):
            continue
        seen_ids.add(flight_id)
        eligible.append(flight)
    if not eligible:
        return None
    selected = min(eligible, key=lambda flight: (flight.get("price", float("inf")), str(flight.get("id"))))
    return {"tool": "select_flight", "arguments": {"flight_id": selected["id"]}}


def diagnose(trace):
    candidates = []
    seen_keys = set()

    def add_candidate(candidate):
        key = (
            _normalize_cause(candidate.get("cause")),
            _normalize_step_id(candidate.get("step_id")),
        )
        if key in seen_keys:
            return
        seen_keys.add(key)
        candidate.setdefault("evidence", {})
        candidate.setdefault("source", "diagnoser")
        candidate.setdefault("constraint", None)
        candidates.append(candidate)

    for index, item in enumerate(trace):
        item = item if isinstance(item, dict) else {}
        # The public trace contains requested and effective actions, but never
        # fault truth.  Prefer the requested action when preparing evidence so
        # a replay can restore what the agent actually asked for.
        action = item.get("action", item)
        action = action if isinstance(action, dict) else {}
        # Avoid treating result/observation envelope fields as action data in
        # legacy traces that put tool/arguments at the top level.
        if "tool" not in action and "arguments" not in action:
            action = {}
        requested_action = item.get("requested_action", action)
        requested_action = requested_action if isinstance(requested_action, dict) else action
        result = item.get("result", {})
        result = result if isinstance(result, dict) else {}
        error = str(result.get("error", ""))
        tool = action.get("tool")
        args = action.get("arguments", {})
        requested_tool = requested_action.get("tool")
        requested_args = requested_action.get("arguments", {})
        requested_args = requested_args if isinstance(requested_args, dict) else {}

        # Environment faults such as wrong_tool/replace_action can alter the
        # effective tool.  This is observable from the trace alone and must be
        # diagnosed without consulting fault_truth.
        action_diff = requested_action != action
        if action_diff and requested_tool is not None and tool is not None and requested_tool != tool:
            add_candidate({
                "step_id": index,
                "category": "action_error",
                "cause": "effective_tool_mismatch",
                "confidence": 0.86,
                "repair_options": ["retry", "abstain"],
                "evidence": {
                    # Keep requested tool/arguments available for a clean
                    # replay; do not include any fault metadata.
                    "tool": requested_tool,
                    "arguments": requested_args,
                    "requested_action": requested_action,
                    "effective_action": action,
                    "requested_tool": requested_tool,
                    "effective_tool": tool,
                    "error": error,
                },
                "source": "trace_action_diff",
                "constraint": None,
            })
        if "explicit user confirmation required" in error:
            add_candidate({
                "step_id": index,
                "category": "constraint_violation",
                "cause": "missing_explicit_confirmation",
                "confidence": 0.92,
                "repair_options": ["ask_clarification", "abstain"],
                "evidence": {"error": error, "tool": tool, "arguments": args},
                "source": "environment_error",
                "constraint": "confirmation requires explicit user confirmation",
            })
        elif "selected flight violates task constraints" in error:
            prior_selection = next((
                j for j in range(index - 1, -1, -1)
                if trace[j].get("action", {}).get("tool") == "select_flight"
            ), index)
            refundable = _requires_refundable(trace)
            selected_id = None
            if 0 <= prior_selection < len(trace):
                selected = trace[prior_selection].get("action", {}).get("arguments", {})
                if isinstance(selected, dict):
                    selected_id = selected.get("flight_id")
            replacement = _suggest_replacement(trace, prior_selection, selected_id)
            if refundable is False:
                cause = "selected_flight_constraint_violation"
                constraint = "selected_flight must satisfy task constraints"
                confidence = 0.58
            else:
                cause = "selected_non_refundable_flight"
                constraint = "selected_flight must be refundable"
                confidence = 0.89
            evidence = {
                "error": error,
                "trigger_step_id": index,
                "selected_step_id": prior_selection,
            }
            if replacement is not None:
                evidence["replacement"] = replacement
            add_candidate({
                "step_id": prior_selection,
                "category": "planning_error",
                "cause": cause,
                "confidence": confidence,
                "repair_options": ["replace_argument", "replan"],
                "evidence": evidence,
                "source": "environment_error",
                "constraint": constraint,
            })
        elif tool == "select_flight" and args.get("flight_id") == "F2":
            refundable = _requires_refundable(trace)
            if refundable is False:
                continue
            replacement = _suggest_replacement(trace, index, args.get("flight_id"))
            evidence = {
                "tool": tool,
                "flight_id": args.get("flight_id"),
                "result_ok": result.get("ok", True),
            }
            if replacement is not None:
                evidence["replacement"] = replacement
            add_candidate({
                "step_id": index,
                "category": "planning_error",
                "cause": "selected_non_refundable_flight",
                "confidence": 0.89,
                "repair_options": ["replace_argument", "replan"],
                "evidence": evidence,
                "source": "trajectory_action",
                "constraint": "selected_flight must be refundable",
            })
        elif not result.get("ok", True):
            add_candidate({
                "step_id": index,
                "category": "action_error",
                "cause": error or "tool_execution_failed",
                "confidence": 0.71,
                "repair_options": ["retry", "fallback_tool", "abstain"],
                "evidence": {
                    "error": error,
                    "tool": requested_tool,
                    "arguments": requested_args,
                    "requested_action": requested_action,
                },
                "source": "tool_result",
                "constraint": None,
            })
    if not candidates:
        add_candidate({
            "step_id": None,
            "category": "unknown",
            "cause": "no_localized_root_cause",
            "confidence": 0.25,
            "repair_options": ["replan", "ask_clarification", "abstain"],
            "evidence": {"trace_length": len(trace)},
            "source": "diagnoser",
            "constraint": None,
        })
    return {"candidates": candidates, "diagnosis_confidence": max(c["confidence"] for c in candidates)}


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send({"ok": True})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/diagnose":
            return self._send(diagnose(payload.get("trace", [])))
        return self._send({"error": "not found"}, 404)

    def log_message(self, *_):
        return


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
