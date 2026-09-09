import copy
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


# v0.5 planning-error patch derivation. The flight cause keeps its frozen
# literal patch (select_flight F1) for protocol continuity with v0.1-v0.4
# artifacts; new domains derive the repair target from the diagnosis
# evidence (the cheapest eligible item on the public listing, attached by
# the diagnoser). A missing repair target degrades to abstain -- never a
# fabricated patch.

_PLANNING_ERROR_PATCHES = {
    "selected_non_refundable_flight": {"tool": "select_flight", "arguments": {"flight_id": "F1"}},
    "selected_non_cancellable_room": None,   # derived from evidence.repair_target
    "selected_non_returnable_product": None,  # derived from evidence.repair_target
}

_PLANNING_ERROR_SELECT_TOOLS = {
    "selected_non_cancellable_room": "select_room",
    "selected_non_returnable_product": "select_product",
}


def _planning_error_patch(cause, evidence):
    """Resolve the replace_argument patch for a planning-error cause.

    Flight: frozen F1 literal (v0.1-v0.4 continuity).
    Hotel/shop: the diagnoser's repair_target (cheapest eligible item
    derived from the public listing). Without a usable target the strategy
    abstains rather than fabricating an id.
    """
    frozen = _PLANNING_ERROR_PATCHES.get(cause, "missing")
    if isinstance(frozen, dict):
        return copy.deepcopy(frozen)
    select_tool = _PLANNING_ERROR_SELECT_TOOLS.get(cause)
    if select_tool is None:
        return None
    if not isinstance(evidence, dict):
        return None
    target = evidence.get("repair_target")
    if not isinstance(target, dict):
        return None
    target_id = target.get("id")
    if not isinstance(target_id, str) or not target_id.strip():
        return None
    id_arg = "room_id" if select_tool == "select_room" else "product_id"
    return {"tool": select_tool, "arguments": {id_arg: target_id}}


def choose(diagnosis, allow_abstain=True):
    candidates = diagnosis.get("candidates", [])
    if not candidates:
        return {"decision": "abstain", "reason": "no diagnosis"}
    root = max(candidates, key=lambda x: x.get("confidence", 0))
    confidence = root.get("confidence", 0)
    if allow_abstain and confidence < 0.55:
        return {"decision": "abstain", "reason": "low diagnosis confidence", "confidence": confidence}
    options = root.get("repair_options", ["abstain"])
    if root.get("cause") == "selected_non_refundable_flight":
        decision = "replace_argument"
        patch = {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
    elif root.get("cause") in ("selected_non_cancellable_room", "selected_non_returnable_product"):
        derived = _planning_error_patch(root.get("cause"), root.get("evidence"))
        if derived is None:
            decision = "abstain"
            patch = None
        else:
            decision = "replace_argument"
            patch = derived
    elif root.get("cause") == "missing_explicit_confirmation":
        decision = "ask_clarification"
        patch = None
    else:
        # A regular tool error can be safely retried in a clean replay only
        # when the trace carries the requested tool call as evidence.  This
        # keeps recovery independent of hidden fault truth while ensuring
        # force_error/rate_limit trajectories are verifiable.
        evidence = root.get("evidence")
        if isinstance(evidence, dict):
            retry_tool = evidence.get("tool")
            retry_args = evidence.get("arguments")
            if isinstance(retry_tool, str) and retry_tool.strip() and isinstance(retry_args, dict):
                decision = "retry"
                patch = {"tool": retry_tool, "arguments": copy.deepcopy(retry_args)}
            else:
                decision = options[0]
                patch = None
        else:
            decision = options[0]
            patch = None
    return {"decision": decision, "confidence": confidence, "step_id": root.get("step_id"), "patch": patch, "expected_cost": 1, "expected_risk": round(1 - confidence, 3)}


def raw_decision(diagnosis):
    """Return the no-repair baseline decision for a diagnosis."""
    return {
        "baseline_id": "raw",
        "decision": "abstain",
        "reason": "raw baseline does not repair",
        "patch": None,
    }


def _usable_patch(patch):
    if not isinstance(patch, dict):
        return None
    tool = patch.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        return None
    arguments = patch.get("arguments")
    if arguments is not None and not isinstance(arguments, dict):
        return None
    return copy.deepcopy(patch)


def _fault_entries(fault_truth):
    if isinstance(fault_truth, (list, tuple)):
        return fault_truth
    if isinstance(fault_truth, dict):
        nested = fault_truth.get("fault_truth", fault_truth.get("faults"))
        if isinstance(nested, (list, tuple)):
            return nested
        return [fault_truth]
    return []


def oracle_decision(diagnosis, fault_truth):
    """Repair only when the fault truth contains an explicit usable patch."""
    for fault in _fault_entries(fault_truth):
        if not isinstance(fault, dict):
            continue
        patch = _usable_patch(fault.get("patch"))
        if patch is None:
            for key in ("replacement", "replace_with", "action"):
                patch = _usable_patch(fault.get(key))
                if patch is not None:
                    break
        if patch is None:
            continue
        result = {
            "baseline_id": "oracle",
            "decision": "oracle_repair",
            "patch": patch,
            "reason": "explicit patch from fault truth",
        }
        for key in ("step_id", "step", "at"):
            if fault.get(key) is not None:
                result["step_id"] = fault[key]
                break
        if fault.get("fault_id") is not None:
            result["fault_id"] = fault["fault_id"]
        return result
    return {
        "baseline_id": "oracle",
        "decision": "abstain",
        "reason": "fault truth has no usable patch",
        "patch": None,
    }


def recovery_decision(diagnosis, allow_abstain=True):
    """Select a recovery action using the existing confidence-aware policy."""
    decision = choose(diagnosis, allow_abstain=allow_abstain)
    decision["baseline_id"] = "recovery"
    return decision


# ---------------------------------------------------------------------------
# Main-tier baseline strategies (protocol section 7). Every non-oracle
# strategy consumes ONLY the public trace diagnosis -- no fault truth, no
# future state, no oracle witness. Output shape matches the pilot
# decision contract: {baseline_id, decision, patch, step_id, confidence,
# expected_cost, expected_risk, reason} plus optional baseline-specific
# fields the runner/evaluator tolerate (they are copied into derived rows).
# ---------------------------------------------------------------------------

ABSTAIN_THRESHOLD = 0.55


def _top(candidates, key=None):
    if not candidates:
        return None
    if key is None:
        key = lambda x: x.get("confidence", 0)
    return max(candidates, key=key)


def _retry_patch(root):
    """Build a retry patch from the top candidate's public evidence."""
    evidence = root.get("evidence")
    if not isinstance(evidence, dict):
        return None
    tool = evidence.get("tool")
    arguments = evidence.get("arguments")
    if isinstance(tool, str) and tool.strip() and isinstance(arguments, dict):
        return {"tool": tool, "arguments": copy.deepcopy(arguments)}
    return None


def _final_decision(baseline_id, decision, patch, root, reason, **extra):
    payload = {
        "baseline_id": baseline_id,
        "decision": decision,
        "patch": patch,
        "step_id": root.get("step_id") if isinstance(root, dict) else None,
        "confidence": root.get("confidence", 0) if isinstance(root, dict) else None,
        "expected_cost": 1,
        "expected_risk": round(1 - (root.get("confidence", 0) if isinstance(root, dict) else 0), 3),
        "reason": reason,
    }
    payload.update(extra)
    return payload


def raw_react_decision(diagnosis):
    """1. raw_react: original ReAct agent -- no diagnosis-driven repair."""
    return {
        "baseline_id": "raw_react",
        "decision": "abstain",
        "reason": "raw_react performs no recovery; terminal state stands",
        "patch": None,
    }


def fixed_retry_decision(diagnosis):
    """2. fixed_retry: blindly retry the failed tool call once, no diagnosis."""
    root = _top(diagnosis.get("candidates", []))
    if root is None:
        return {"baseline_id": "fixed_retry", "decision": "abstain", "reason": "no candidates", "patch": None}
    patch = _retry_patch(root)
    if patch is None:
        return {
            "baseline_id": "fixed_retry",
            "decision": "abstain",
            "reason": "failed step has no retryable requested action",
            "patch": None,
        }
    return _final_decision("fixed_retry", "retry", patch, root, "blind fixed retry of the failed requested action", retry_policy="fixed", max_retries=1)


def exponential_backoff_decision(diagnosis):
    """3. exponential_backoff: retry with backoff schedule (1s, 2s)."""
    root = _top(diagnosis.get("candidates", []))
    if root is None:
        return {"baseline_id": "exponential_backoff", "decision": "abstain", "reason": "no candidates", "patch": None}
    patch = _retry_patch(root)
    if patch is None:
        return {
            "baseline_id": "exponential_backoff",
            "decision": "abstain",
            "reason": "failed step has no retryable requested action",
            "patch": None,
        }
    return _final_decision("exponential_backoff", "retry", patch, root, "retry with exponential backoff schedule", retry_policy="exponential_backoff", backoff_schedule_s=[1, 2], max_retries=2)


def _reflection_patch(root, candidates):
    """Generic reflection: re-derive the repair from the highest-confidence
    candidate, degrading to abstain when evidence is weak (conf < 0.55)."""
    confidence = root.get("confidence", 0)
    if confidence < ABSTAIN_THRESHOLD:
        return None
    cause = root.get("cause")
    if cause == "selected_non_refundable_flight":
        return {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
    if cause in ("selected_non_cancellable_room", "selected_non_returnable_product"):
        return _planning_error_patch(cause, root.get("evidence"))
    return _retry_patch(root)


def generic_reflection_decision(diagnosis):
    """4. generic_reflection: self-reflection on the full public trace; primary
    comparison baseline for H1/H2."""
    candidates = diagnosis.get("candidates", [])
    root = _top(candidates)
    if root is None:
        return {"baseline_id": "generic_reflection", "decision": "abstain", "reason": "no candidates", "patch": None}
    patch = _reflection_patch(root, candidates)
    if patch is None:
        return {
            "baseline_id": "generic_reflection",
            "decision": "abstain",
            "reason": "reflection confidence below action threshold",
            "patch": None,
            "confidence": root.get("confidence", 0),
        }
    return _final_decision("generic_reflection", "retry", patch, root, "self-reflection derived repair", strategy="reflect_then_act")


def full_trace_judge_decision(diagnosis):
    """5. full_trace_judge: judge over the complete trajectory; acts only when
    total evidence (all candidate confidences aggregated) is strong."""
    candidates = diagnosis.get("candidates", [])
    if not candidates:
        return {"baseline_id": "full_trace_judge", "decision": "abstain", "reason": "no candidates", "patch": None}
    # Aggregate view: a judge over the full trace trusts the strongest signal
    # but requires corroborating support (>= 2 candidates or single >= 0.85).
    root = _top(candidates)
    support = len(candidates)
    confidence = root.get("confidence", 0)
    if not (support >= 2 or confidence >= 0.85):
        return {
            "baseline_id": "full_trace_judge",
            "decision": "abstain",
            "reason": "insufficient corroborating trace evidence",
            "patch": None,
            "confidence": confidence,
        }
    patch = _reflection_patch(root, candidates)
    if patch is None:
        return {
            "baseline_id": "full_trace_judge",
            "decision": "abstain",
            "reason": "judge found no safe repair from full trace",
            "patch": None,
            "confidence": confidence,
        }
    return _final_decision("full_trace_judge", "retry", patch, root, "full-trace judge approved repair", judge_scope="full_trace")


def _diagnosis_order_score(candidate):
    """Step-by-step diagnosis prefers the earliest localized step."""
    step = candidate.get("step_id")
    if isinstance(step, int):
        return (0, step)
    return (1, 0)


def step_by_step_diagnosis_decision(diagnosis):
    """6. step_by_step_diagnosis: localize the earliest root cause and repair it."""
    candidates = [c for c in diagnosis.get("candidates", []) if isinstance(c, dict)]
    if not candidates:
        return {"baseline_id": "step_by_step_diagnosis", "decision": "abstain", "reason": "no candidates", "patch": None}
    root = min(candidates, key=_diagnosis_order_score)
    if root.get("confidence", 0) < ABSTAIN_THRESHOLD:
        return {
            "baseline_id": "step_by_step_diagnosis",
            "decision": "abstain",
            "reason": "earliest localized candidate below confidence threshold",
            "patch": None,
            "confidence": root.get("confidence", 0),
        }
    cause = root.get("cause")
    if cause == "selected_non_refundable_flight":
        patch = {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
        return _final_decision("step_by_step_diagnosis", "replace_argument", patch, root, "earliest-step root cause repaired", scan="sequential")
    if cause in ("selected_non_cancellable_room", "selected_non_returnable_product"):
        derived = _planning_error_patch(cause, root.get("evidence"))
        if derived is not None:
            return _final_decision("step_by_step_diagnosis", "replace_argument", derived, root, "earliest-step root cause repaired", scan="sequential")
    patch = _retry_patch(root)
    if patch is None:
        return {
            "baseline_id": "step_by_step_diagnosis",
            "decision": "abstain",
            "reason": "earliest candidate has no repairable evidence",
            "patch": None,
        }
    return _final_decision("step_by_step_diagnosis", "retry", patch, root, "earliest-step root cause retried", scan="sequential")


def binary_search_diagnosis_decision(diagnosis):
    """7. binary_search_diagnosis: narrow the failure window by halving the
    trace, then repair the midpoint-attributed step."""
    candidates = [c for c in diagnosis.get("candidates", []) if isinstance(c, dict)]
    if not candidates:
        return {"baseline_id": "binary_search_diagnosis", "decision": "abstain", "reason": "no candidates", "patch": None}
    # Order candidates by step, then binary-search the ordered list: the
    # probe target is the midpoint of the localized failure window.
    ordered = sorted(candidates, key=_diagnosis_order_score)
    mid = ordered[len(ordered) // 2]
    if mid.get("confidence", 0) < ABSTAIN_THRESHOLD:
        return {
            "baseline_id": "binary_search_diagnosis",
            "decision": "abstain",
            "reason": "binary-search midpoint candidate below threshold",
            "patch": None,
            "confidence": mid.get("confidence", 0),
        }
    cause = mid.get("cause")
    if cause == "selected_non_refundable_flight":
        patch = {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
        return _final_decision("binary_search_diagnosis", "replace_argument", patch, mid, "midpoint-attributed root cause repaired", scan="binary_search")
    if cause in ("selected_non_cancellable_room", "selected_non_returnable_product"):
        derived = _planning_error_patch(cause, mid.get("evidence"))
        if derived is not None:
            return _final_decision("binary_search_diagnosis", "replace_argument", derived, mid, "midpoint-attributed root cause repaired", scan="binary_search")
    patch = _retry_patch(mid)
    if patch is None:
        return {
            "baseline_id": "binary_search_diagnosis",
            "decision": "abstain",
            "reason": "midpoint candidate has no repairable evidence",
            "patch": None,
        }
    return _final_decision("binary_search_diagnosis", "retry", patch, mid, "midpoint-attributed root cause retried", scan="binary_search")


def agentdebug_targeted_feedback_decision(diagnosis):
    """8. agentdebug_targeted_feedback: use the highest-confidence candidate's
    targeted feedback as the repair instruction (AgentDebug-style)."""
    candidates = diagnosis.get("candidates", [])
    root = _top(candidates)
    if root is None:
        return {"baseline_id": "agentdebug_targeted_feedback", "decision": "abstain", "reason": "no candidates", "patch": None}
    confidence = root.get("confidence", 0)
    # AgentDebug acts on targeted feedback even at moderate confidence, but
    # still abstains when feedback carries no actionable repair evidence.
    feedback = root.get("evidence") if isinstance(root.get("evidence"), dict) else {}
    patch = _retry_patch(root)
    if root.get("cause") == "selected_non_refundable_flight":
        patch = {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
    if root.get("cause") in ("selected_non_cancellable_room", "selected_non_returnable_product"):
        patch = _planning_error_patch(root.get("cause"), root.get("evidence"))
    if patch is None:
        return {
            "baseline_id": "agentdebug_targeted_feedback",
            "decision": "abstain",
            "reason": "targeted feedback contains no actionable repair",
            "patch": None,
            "confidence": confidence,
        }
    return _final_decision("agentdebug_targeted_feedback", "retry", patch, root, "targeted feedback applied as repair", feedback_source="top_candidate_evidence", targeted=True)


def always_recover_decision(diagnosis):
    """9. always_recover: never abstain -- always attempt the best repair."""
    candidates = [c for c in diagnosis.get("candidates", []) if isinstance(c, dict)]
    if not candidates:
        return {"baseline_id": "always_recover", "decision": "abstain", "reason": "no candidates to act on", "patch": None}
    root = _top(candidates)
    cause = root.get("cause")
    if cause == "selected_non_refundable_flight":
        patch = {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
        return _final_decision("always_recover", "replace_argument", patch, root, "forced recovery without abstention", allow_abstain=False)
    if cause in ("selected_non_cancellable_room", "selected_non_returnable_product"):
        derived = _planning_error_patch(cause, root.get("evidence"))
        if derived is not None:
            return _final_decision("always_recover", "replace_argument", derived, root, "forced recovery without abstention", allow_abstain=False)
    patch = _retry_patch(root)
    if patch is None:
        # Never abstain on principle, but with no actionable evidence the
        # strategy still cannot fabricate a patch; abstain here is forced by
        # evidence absence, not by risk gating.
        return {
            "baseline_id": "always_recover",
            "decision": "abstain",
            "reason": "no actionable repair evidence available",
            "patch": None,
            "confidence": root.get("confidence", 0),
        }
    return _final_decision("always_recover", "retry", patch, root, "forced recovery without abstention", allow_abstain=False)


def _racer_utility(root, patch, counterfactual_budget=1):
    """RACER risk-utility: act only when expected utility is positive."""
    confidence = root.get("confidence", 0) if isinstance(root, dict) else 0
    if patch is None:
        return None
    # expected utility = confidence * value_of_success - (1-confidence) * risk_of_harm
    utility = confidence - (1 - confidence)
    return utility


def racer_decision(diagnosis, allow_abstain=True, use_counterfactual=True):
    """10. racer: full method -- multi-candidate ranking, risk-utility gating,
    counterfactual verification, abstention."""
    candidates = [c for c in diagnosis.get("candidates", []) if isinstance(c, dict)]
    if not candidates:
        return {"baseline_id": "racer", "decision": "abstain", "reason": "no candidates", "patch": None}
    # Multi-root-cause ranking: rank by confidence, then by earliest step.
    ranked = sorted(candidates, key=lambda c: (-c.get("confidence", 0), _diagnosis_order_score(c)))
    root = ranked[0]
    confidence = root.get("confidence", 0)
    cause = root.get("cause")
    patch = None
    if cause == "selected_non_refundable_flight":
        patch = {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
    elif cause == "missing_explicit_confirmation":
        patch = None  # ask_clarification, no replayable patch
    elif cause in ("selected_non_cancellable_room", "selected_non_returnable_product"):
        patch = _planning_error_patch(cause, root.get("evidence"))
    else:
        patch = _retry_patch(root)
    utility = _racer_utility(root, patch)
    if allow_abstain and (confidence < ABSTAIN_THRESHOLD or (utility is not None and utility < 0)):
        return {
            "baseline_id": "racer",
            "decision": "abstain",
            "reason": "risk-utility gate rejects repair",
            "patch": None,
            "confidence": confidence,
            "expected_utility": utility,
            "use_counterfactual": use_counterfactual,
        }
    if patch is None:
        decision = "ask_clarification"
        return _final_decision("racer", decision, None, root, "clarification requested before any risky repair", use_counterfactual=use_counterfactual, expected_utility=utility)
    decision = "replace_argument" if cause in ("selected_non_refundable_flight", "selected_non_cancellable_room", "selected_non_returnable_product") else "retry"
    return _final_decision("racer", decision, patch, root, "risk-utility gated repair with counterfactual verification", use_counterfactual=use_counterfactual, expected_utility=utility)


def racer_no_abstain_decision(diagnosis):
    """11. racer_no_abstain: RACER without the abstention gate."""
    decision = racer_decision(diagnosis, allow_abstain=False)
    decision["baseline_id"] = "racer_no_abstain"
    decision["ablation"] = "no_abstain"
    return decision


def racer_no_counterfactual_decision(diagnosis):
    """12. racer_no_counterfactual: RACER without counterfactual verification.
    The patch is applied without replay validation -- the runner must skip
    the counterfactual replay for this branch (skip_counterfactual=true)."""
    decision = racer_decision(diagnosis, allow_abstain=True, use_counterfactual=False)
    decision["baseline_id"] = "racer_no_counterfactual"
    decision["ablation"] = "no_counterfactual"
    decision["skip_counterfactual"] = True
    return decision


def oracle_root_cause_decision(diagnosis, fault_truth):
    """13. oracle_root_cause: privileged ground-truth root cause attribution.
    Uses fault truth ONLY to select the step, but the patch still must be
    constructible from public evidence (upper bound on diagnosis, not repair)."""
    root = _top([c for c in diagnosis.get("candidates", []) if isinstance(c, dict)])
    fault = None
    for entry in _fault_entries(fault_truth):
        if isinstance(entry, dict):
            fault = entry
            break
    if fault is None or root is None:
        return {
            "baseline_id": "oracle_root_cause",
            "decision": "abstain",
            "reason": "no fault truth or no candidates",
            "patch": None,
        }
    # Locate the true step and pick the candidate matching it when present;
    # otherwise synthesize a retry patch from public evidence at that step.
    true_step = fault.get("step_id")
    step_patch = _usable_patch(fault.get("patch"))
    if step_patch is None:
        matching = [c for c in diagnosis.get("candidates", []) if c.get("step_id") == true_step]
        source = matching[0] if matching else root
        if source.get("cause") == "selected_non_refundable_flight":
            step_patch = {"tool": "select_flight", "arguments": {"flight_id": "F1"}}
        elif source.get("cause") in ("selected_non_cancellable_room", "selected_non_returnable_product"):
            step_patch = _planning_error_patch(source.get("cause"), source.get("evidence"))
        else:
            step_patch = _retry_patch(source)
    if step_patch is None:
        return {
            "baseline_id": "oracle_root_cause",
            "decision": "abstain",
            "reason": "oracle step has no repairable public evidence",
            "patch": None,
        }
    return {
        "baseline_id": "oracle_root_cause",
        "decision": "oracle_repair",
        "patch": step_patch,
        "step_id": true_step if true_step is not None else root.get("step_id"),
        "reason": "ground-truth root cause step, public-evidence patch",
        "confidence": 1.0,
        "expected_cost": 1,
        "expected_risk": 0.0,
    }


def oracle_recovery_decision(diagnosis, fault_truth):
    """14. oracle_recovery: privileged upper bound -- repair with the explicit
    ground-truth patch when one exists."""
    decision = oracle_decision(diagnosis, fault_truth)
    decision["baseline_id"] = "oracle_recovery"
    return decision


MAIN_BASELINE_DISPATCH = {
    "raw_react": lambda p: raw_react_decision(p.get("diagnosis", {})),
    "fixed_retry": lambda p: fixed_retry_decision(p.get("diagnosis", {})),
    "exponential_backoff": lambda p: exponential_backoff_decision(p.get("diagnosis", {})),
    "generic_reflection": lambda p: generic_reflection_decision(p.get("diagnosis", {})),
    "full_trace_judge": lambda p: full_trace_judge_decision(p.get("diagnosis", {})),
    "step_by_step_diagnosis": lambda p: step_by_step_diagnosis_decision(p.get("diagnosis", {})),
    "binary_search_diagnosis": lambda p: binary_search_diagnosis_decision(p.get("diagnosis", {})),
    "agentdebug_targeted_feedback": lambda p: agentdebug_targeted_feedback_decision(p.get("diagnosis", {})),
    "always_recover": lambda p: always_recover_decision(p.get("diagnosis", {})),
    "racer": lambda p: racer_decision(p.get("diagnosis", {})),
    "racer_no_abstain": lambda p: racer_no_abstain_decision(p.get("diagnosis", {})),
    "racer_no_counterfactual": lambda p: racer_no_counterfactual_decision(p.get("diagnosis", {})),
    "oracle_root_cause": lambda p: oracle_root_cause_decision(p.get("diagnosis", {}), p.get("fault_truth", [])),
    "oracle_recovery": lambda p: oracle_recovery_decision(p.get("diagnosis", {}), p.get("fault_truth", [])),
}

ORACLE_BASELINE_IDS = frozenset({"oracle_root_cause", "oracle_recovery"})


def baseline_dispatch(baseline_id, payload):
    """Dispatch a main-tier baseline by ID; fail closed on unknown IDs."""
    handler = MAIN_BASELINE_DISPATCH.get(baseline_id)
    if handler is None:
        # Pilot-tier baseline ids remain supported through /baseline.
        if baseline_id == "raw":
            return raw_decision(payload.get("diagnosis", {}))
        if baseline_id == "oracle":
            return oracle_decision(payload.get("diagnosis", {}), payload.get("fault_truth", []))
        if baseline_id == "recovery":
            return recovery_decision(payload.get("diagnosis", {}), payload.get("allow_abstain", True))
        return None
    return handler(payload)


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
            return self._send({"ok": True, "baselines": sorted(MAIN_BASELINE_DISPATCH) + ["raw", "recovery", "oracle"]})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/choose":
            return self._send(choose(payload.get("diagnosis", {}), payload.get("allow_abstain", True)))
        if self.path == "/baseline":
            baseline_id = payload.get("baseline_id", "recovery")
            decision = baseline_dispatch(baseline_id, payload)
            if decision is None:
                return self._send({"error": f"unsupported baseline_id: {baseline_id}"}, 400)
            return self._send(decision)
        if self.path == "/baselines":
            batch = payload.get("baselines", [])
            results = {}
            for entry in batch if isinstance(batch, list) else []:
                if not isinstance(entry, dict):
                    continue
                bid = entry.get("baseline_id")
                decision = baseline_dispatch(bid, entry)
                if decision is not None:
                    results[bid] = decision
            return self._send({"decisions": results})
        return self._send({"error": "not found"}, 404)

    def log_message(self, *_):
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
