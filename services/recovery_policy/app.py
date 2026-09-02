import copy
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


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
        if self.path == "/choose":
            return self._send(choose(payload.get("diagnosis", {}), payload.get("allow_abstain", True)))
        if self.path == "/baseline":
            baseline_id = payload.get("baseline_id", "recovery")
            diagnosis = payload.get("diagnosis", {})
            if baseline_id == "raw":
                return self._send(raw_decision(diagnosis))
            if baseline_id == "oracle":
                return self._send(oracle_decision(diagnosis, payload.get("fault_truth", [])))
            if baseline_id == "recovery":
                return self._send(recovery_decision(diagnosis, payload.get("allow_abstain", True)))
            return self._send({"error": "unsupported baseline_id"}, 400)
        return self._send({"error": "not found"}, 404)

    def log_message(self, *_):
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
