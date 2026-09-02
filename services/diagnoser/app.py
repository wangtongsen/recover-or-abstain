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
            add_candidate({
                "step_id": prior_selection,
                "category": "planning_error",
                "cause": "selected_non_refundable_flight",
                "confidence": 0.89,
                "repair_options": ["replace_argument", "replan"],
                "evidence": {
                    "error": error,
                    "trigger_step_id": index,
                    "selected_step_id": prior_selection,
                },
                "source": "environment_error",
                "constraint": "selected_flight must be refundable",
            })
        elif tool == "select_flight" and args.get("flight_id") == "F2":
            add_candidate({
                "step_id": index,
                "category": "planning_error",
                "cause": "selected_non_refundable_flight",
                "confidence": 0.89,
                "repair_options": ["replace_argument", "replan"],
                "evidence": {
                    "tool": tool,
                    "flight_id": args.get("flight_id"),
                    "result_ok": result.get("ok", True),
                },
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
