import json
from http.server import BaseHTTPRequestHandler, HTTPServer


# v0.5 planning-error causes across domains. Each cause maps to the
# environment's constraint error string and the select tool it repairs.
# The flight cause keeps its frozen name (selected_non_refundable_flight);
# hotel/shop carry parallel names. The diagnoser matches the domain's
# constraint error verbatim and derives the repair target from the public
# listing in the trace (cheapest eligible item), never from fault truth.
_PLANNING_ERROR_MATCHERS = [
    {
        "domain": "flight",
        "error_substring": "selected flight violates task constraints",
        "select_tool": "select_flight",
        "cause": "selected_non_refundable_flight",
        "id_arg": "flight_id",
        "soft_flag": "refundable",
        "soft_exempt_text": "non-refundable",
        "catalog_key": "flights",
        "constraint": "selected_flight must be refundable",
    },
    {
        "domain": "hotel",
        "error_substring": "selected room violates task constraints",
        "select_tool": "select_room",
        "cause": "selected_non_cancellable_room",
        "id_arg": "room_id",
        "soft_flag": "cancellable",
        "soft_exempt_text": "non-cancellable",
        "catalog_key": "rooms",
        "constraint": "selected_room must be cancellable",
    },
    {
        "domain": "shop",
        "error_substring": "selected product violates task constraints",
        "select_tool": "select_product",
        "cause": "selected_non_returnable_product",
        "id_arg": "product_id",
        "soft_flag": "returnable",
        "soft_exempt_text": "non-returnable",
        "catalog_key": "products",
        "constraint": "selected_product must be returnable and in stock",
    },
]


def _match_planning_error(error):
    for matcher in _PLANNING_ERROR_MATCHERS:
        if matcher["error_substring"] in error:
            return matcher
    return None


def _listing_from_result(result):
    """Extract the public catalog listing from a search step result."""
    if not isinstance(result, dict):
        return None
    for key in ("flights", "rooms", "products"):
        if isinstance(result.get(key), list):
            return result[key]
    return None


def _cheapest_eligible(listing, matcher, budget):
    """Derive the cheapest eligible item from a public listing (repair target).

    Mirrors the actor's decision rule: soft flag true (unless the task text
    exempts it), in stock (default True), price <= budget. Ties break to the
    lowest id, matching the environment's optimal-selection semantics.
    """
    eligible = [
        item
        for item in listing
        if isinstance(item, dict)
        and item.get(matcher["soft_flag"]) is True
        and item.get("in_stock", True) is True
        and isinstance(item.get("price"), (int, float))
        and item["price"] <= budget
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda item: (item["price"], item["id"]))


def _trace_budget(trace, index):
    """Read the task budget from the most recent public observation."""
    for j in range(index, -1, -1):
        item = trace[j] if isinstance(trace[j], dict) else {}
        observation = item.get("observation") if isinstance(item.get("observation"), dict) else {}
        state = observation.get("state") if isinstance(observation.get("state"), dict) else {}
        budget = state.get("budget")
        if isinstance(budget, (int, float)) and not isinstance(budget, bool):
            return budget
    return None


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
        elif _match_planning_error(error) is not None:
            matcher = _match_planning_error(error)
            prior_selection = next((
                j for j in range(index - 1, -1, -1)
                if isinstance(trace[j], dict)
                and isinstance(trace[j].get("action"), dict)
                and trace[j]["action"].get("tool") == matcher["select_tool"]
            ), index)
            # v0.5: derive the repair target from the most recent public
            # listing in the trace (cheapest eligible item). The evidence key
            # is additive; flight candidates keep their frozen fields.
            repair_target = None
            budget = _trace_budget(trace, index)
            if budget is not None:
                for j in range(index - 1, -1, -1):
                    prior_result = trace[j].get("result") if isinstance(trace[j], dict) else None
                    listing = _listing_from_result(prior_result)
                    if listing:
                        repair_target = _cheapest_eligible(listing, matcher, budget)
                        if repair_target is not None:
                            break
            evidence = {
                "error": error,
                "trigger_step_id": index,
                "selected_step_id": prior_selection,
            }
            if repair_target is not None:
                evidence["repair_target"] = repair_target
            add_candidate({
                "step_id": prior_selection,
                "category": "planning_error",
                "cause": matcher["cause"],
                "confidence": 0.89,
                "repair_options": ["replace_argument", "replan"],
                "evidence": evidence,
                "source": "environment_error",
                "constraint": matcher["constraint"],
            })
        elif tool in ("select_flight", "select_room", "select_product"):
            # Item-constraint candidates must follow the task's actual soft
            # requirement, which is public in the observation (task text +
            # invariants) and the select result. A soft-flag-violating item is
            # only a planning error when the task itself requires the flag;
            # hardcoding semantics would fabricate false-positive repairs on
            # variants where the cheap non-conforming item is correct.
            matcher = next((m for m in _PLANNING_ERROR_MATCHERS if m["select_tool"] == tool), None)
            selected = result.get("selected") if isinstance(result.get("selected"), dict) else None
            observation = item.get("observation") if isinstance(item.get("observation"), dict) else {}
            state = observation.get("state") if isinstance(observation.get("state"), dict) else {}
            task_text = str(state.get("task", ""))
            invariants = [str(inv) for inv in (observation.get("invariants") or [])]
            variant_text = " ".join([task_text] + invariants).lower()
            if matcher is None:
                requires_soft = True
                soft_flag = "refundable"
                soft_exempt_text = "non-refundable"
            else:
                soft_flag = matcher["soft_flag"]
                soft_exempt_text = matcher["soft_exempt_text"]
                requires_soft = soft_exempt_text not in variant_text and soft_exempt_text.replace("-", "_") not in variant_text
            if requires_soft and selected is not None and selected.get(soft_flag) is False:
                evidence = {
                    "tool": tool,
                    "id": args.get(matcher["id_arg"]) if matcher else args.get("flight_id"),
                    "selected": selected,
                    "result_ok": result.get("ok", True),
                }
                # v0.5: attach the derived repair target when the public
                # listing is available earlier in the trace.
                budget = _trace_budget(trace, index)
                if budget is not None and matcher is not None:
                    for j in range(index - 1, -1, -1):
                        prior_result = trace[j].get("result") if isinstance(trace[j], dict) else None
                        listing = _listing_from_result(prior_result)
                        if listing:
                            repair_target = _cheapest_eligible(listing, matcher, budget)
                            if repair_target is not None:
                                evidence["repair_target"] = repair_target
                                break
                add_candidate({
                    "step_id": index,
                    "category": "planning_error",
                    "cause": matcher["cause"] if matcher else "selected_non_refundable_flight",
                    "confidence": 0.89,
                    "repair_options": ["replace_argument", "replan"],
                    "evidence": evidence,
                    "source": "trajectory_action",
                    "constraint": matcher["constraint"] if matcher else "selected_flight must be refundable",
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
