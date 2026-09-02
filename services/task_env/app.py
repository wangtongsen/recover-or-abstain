import copy
import hashlib
import json
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


def state_hash(state):
    payload = json.dumps(state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class TaskEnv:
    def __init__(self, seed=0, fault_id=None, fault_step=None, faults=None, task_variant=None):
        self.seed = seed
        self._rng = random.Random(seed)
        self._initial_faults = list(faults or [])
        if fault_id is not None:
            self._initial_faults.append({"fault_id": fault_id, "type": fault_id, "step_id": fault_step})
        payload = {"seed": seed, "faults": self._initial_faults}
        if task_variant is not None:
            payload["task_variant"] = task_variant
        self.reset(payload)

    @staticmethod
    def _normalize_faults(faults):
        if not faults:
            return []
        if isinstance(faults, dict):
            # Also accept {"replace_action": {...}} for convenient JSON specs.
            if any(key in faults for key in ("type", "fault", "kind")):
                faults = [faults]
            else:
                expanded = []
                for fault_type, config in faults.items():
                    if isinstance(config, list):
                        for item in config:
                            item = dict(item) if isinstance(item, dict) else {}
                            item.setdefault("type", fault_type)
                            expanded.append(item)
                    else:
                        item = dict(config) if isinstance(config, dict) else {}
                        item.setdefault("type", fault_type)
                        expanded.append(item)
                faults = expanded
        if isinstance(faults, str):
            faults = [{"type": faults}]
        normalized = []
        for index, fault in enumerate(faults):
            if isinstance(fault, str):
                fault = {"type": fault}
            if not isinstance(fault, dict):
                continue
            item = copy.deepcopy(fault)
            item["type"] = item.get("type", item.get("fault", item.get("kind")))
            item.setdefault("fault_id", f"fault-{index}")
            normalized.append(item)
        return normalized

    def reset(self, payload=None):
        payload = payload if isinstance(payload, dict) else {}
        self.seed = payload.get("seed", 0)
        self.run_id = payload.get("run_id")
        try:
            random_seed = int(self.seed)
        except (TypeError, ValueError):
            random_seed = self.seed
        self._rng = random.Random(random_seed)
        # Accept the same environment configuration in either an explicit
        # env_config envelope or the legacy reset/direct fields.
        env_config = payload.get("env_config") if isinstance(payload.get("env_config"), dict) else {}
        reset_config = payload.get("reset") if isinstance(payload.get("reset"), dict) else {}
        config = copy.deepcopy(env_config)
        config.update(copy.deepcopy(reset_config))
        for key in (
            "task", "origin", "destination", "budget", "flights", "task_variant",
            "variant", "actions", "invariants", "faults", "enable_refund_ledger",
        ):
            if key in payload:
                config[key] = copy.deepcopy(payload[key])
        self.env_config = config
        self.fault_truth = self._normalize_faults(config.get("faults", []))
        self.faults_applied = []
        self.step_id = 0
        self.task_variant = config.get("task_variant", config.get("variant", "clean_success"))
        if not isinstance(self.task_variant, str) or not self.task_variant:
            self.task_variant = "clean_success"
        self.variant = self.task_variant
        self.actions = copy.deepcopy(config.get("actions")) if isinstance(config.get("actions"), list) else []
        self._custom_invariants = copy.deepcopy(config.get("invariants")) if isinstance(config.get("invariants"), list) else None
        variant_faults = {
            "force_error_confirm": {"fault_id": "force-error-confirm", "type": "force_error", "step_id": 2, "error": "injected force_error_confirm"},
            "drop_confirm": {"fault_id": "drop-confirm", "type": "drop_action", "step_id": 2},
        }
        # An explicit faults=[] is authoritative (used by clean replay).
        if self.task_variant in variant_faults and "faults" not in config:
            self.fault_truth = self._normalize_faults([variant_faults[self.task_variant]])
            self.env_config["faults"] = copy.deepcopy(self.fault_truth)
        task = config.get("task") if isinstance(config.get("task"), dict) else {}
        # Accept both a nested task object and direct task-level fields.
        task_config = dict(task)
        for key in ("origin", "destination", "budget", "flights"):
            if key in config:
                task_config[key] = copy.deepcopy(config[key])
        if "task" in config and not isinstance(config["task"], dict):
            task_config["task"] = copy.deepcopy(config["task"])
        # The refund ledger is opt-in so legacy local-flight behavior and hashes
        # remain unchanged. It models a committed side effect that can survive
        # a lost HTTP response and provides a public, recomputable witness.
        self._refund_ledger_enabled = config.get("enable_refund_ledger") is True
        self._booking_id = str(config.get("booking_id", "BK-001"))
        self.state = {
            "task": task_config.get("task", "Book the cheapest refundable flight from A to B."),
            "origin": task_config.get("origin", "A"),
            "destination": task_config.get("destination", "B"),
            "budget": task_config.get("budget", 500),
            "selected_flight": None,
            "confirmed": False,
            "events": [],
        }
        if self._refund_ledger_enabled:
            self.state["booking_id"] = self._booking_id
            self.state["refund_ledger"] = []
        self._flights = copy.deepcopy(task_config.get("flights")) if isinstance(task_config.get("flights"), list) else None
        # Named variants keep task semantics explicit while preserving the
        # default environment behavior used by existing callers.
        if self.task_variant == "non_refundable":
            self.state["task"] = "Book the cheapest non-refundable flight from A to B."
        elif self.task_variant in {"suboptimal_refundable", "missing_confirmation", "force_error_confirm", "drop_confirm"}:
            self.state["task"] = "Book the cheapest refundable flight from A to B."
        if self.task_variant == "non_refundable" and self._flights is None:
            self._flights = [
                {"id": "F1", "price": 420, "refundable": False},
                {"id": "F2", "price": 360, "refundable": False},
                {"id": "F3", "price": 480, "refundable": False},
            ]
        if self.task_variant == "suboptimal_refundable" and self._flights is None:
            self._flights = [
                {"id": "F1", "price": 420, "refundable": True},
                {"id": "F2", "price": 360, "refundable": True},
                {"id": "F3", "price": 480, "refundable": True},
            ]
        self.tools = {
            "search_flights": self.search_flights,
            "select_flight": self.select_flight,
            "confirm_booking": self.confirm_booking,
        }
        if self._refund_ledger_enabled:
            self.tools["refund_booking"] = self.refund_booking
            self.tools["get_refund_status"] = self.get_refund_status
        return self.observe()

    def observe(self, include_truth=False):
        refundable_word = "non-refundable" if self.task_variant == "non_refundable" else "refundable"
        public_env_config = copy.deepcopy(self.env_config)
        public_env_config.pop("faults", None)
        observation = {
            "state": copy.deepcopy(self.state),
            "state_hash": state_hash(self.state),
            "tools": list(self.tools),
            "seed": self.seed,
            "task_variant": self.task_variant,
            "variant": self.variant,
            "actions": copy.deepcopy(self.actions),
            "env_config": public_env_config,
            "invariants": copy.deepcopy(self._custom_invariants) if self._custom_invariants is not None else [
                f"selected_flight must be {refundable_word}",
                "price must be <= budget",
                f"selected_flight must be the cheapest eligible {refundable_word} flight",
                "confirmation requires explicit user confirmation",
            ],
        }
        if include_truth:
            observation["fault_truth"] = copy.deepcopy(self.fault_truth)
            observation["faults_applied"] = copy.deepcopy(self.faults_applied)
        return observation

    def search_flights(self, args):
        flights = self._flights
        if flights is None:
            flights = [
                {"id": "F1", "price": 420, "refundable": True},
                {"id": "F2", "price": 360, "refundable": False},
                {"id": "F3", "price": 480, "refundable": True},
            ]
        return {"flights": copy.deepcopy(flights)}

    def cheapest_refundable_flight(self):
        require_refundable = self.task_variant != "non_refundable"
        candidates = [
            flight
            for flight in self.search_flights({})["flights"]
            if (flight["refundable"] or not require_refundable) and flight["price"] <= self.state["budget"]
        ]
        return min(candidates, key=lambda flight: (flight["price"], flight["id"])) if candidates else None

    def select_flight(self, args):
        flight_id = args.get("flight_id")
        flight = next((item for item in self.search_flights({})["flights"] if item.get("id") == flight_id), None)
        if flight is None:
            return {"ok": False, "error": "unknown flight"}
        self.state["selected_flight"] = copy.deepcopy(flight)
        self.state["events"].append(f"selected:{flight_id}")
        return {"ok": True, "selected": self.state["selected_flight"]}

    def confirm_booking(self, args):
        if not args.get("user_confirmed"):
            return {"ok": False, "error": "explicit user confirmation required"}
        flight = self.state.get("selected_flight")
        requires_refundable = self.task_variant != "non_refundable"
        if not flight or (requires_refundable and not flight["refundable"]) or flight["price"] > self.state["budget"]:
            return {"ok": False, "error": "selected flight violates task constraints"}
        self.state["confirmed"] = True
        self.state["events"].append("confirmed")
        return {"ok": True, "booking_id": self._booking_id if self._refund_ledger_enabled else "BK-001"}

    @staticmethod
    def _refund_entity(args):
        if not isinstance(args, dict):
            return None
        value = args.get("refund_entity_id", args.get("idempotency_key", args.get("refund_id")))
        return str(value).strip() if value is not None and str(value).strip() else None

    @staticmethod
    def _ledger_witness(entry):
        material = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _refund_entry(self, entity_id):
        for entry in self.state.get("refund_ledger", []):
            if entry.get("refund_entity_id") == entity_id:
                return entry
        return None

    def refund_booking(self, args):
        if not self._refund_ledger_enabled:
            return {"ok": False, "error": "refund ledger is not enabled"}
        if not self.state.get("confirmed"):
            return {"ok": False, "error": "no confirmed booking"}
        entity_id = self._refund_entity(args)
        if entity_id is None:
            return {"ok": False, "error": "refund_entity_id is required"}
        existing = self._refund_entry(entity_id)
        if existing is None:
            entry = {
                "booking_id": self._booking_id,
                "refund_entity_id": entity_id,
                "status": "refunded",
                "sequence": len(self.state["refund_ledger"]) + 1,
            }
            entry["ledger_witness"] = self._ledger_witness(entry)
            self.state["refund_ledger"].append(entry)
            self.state["events"].append(f"refund:{entity_id}")
            existing = entry
            replayed = False
        else:
            replayed = True
        result = {
            "ok": True,
            "booking_id": self._booking_id,
            "refund_entity_id": entity_id,
            "idempotent_replay": replayed,
            "ledger_witness": existing["ledger_witness"],
            "ledger_entry_count": len(self.state["refund_ledger"]),
        }
        return result

    def get_refund_status(self, args):
        if not self._refund_ledger_enabled:
            return {"ok": False, "error": "refund ledger is not enabled"}
        entity_id = self._refund_entity(args)
        if entity_id is None:
            return {"ok": False, "error": "refund_entity_id is required"}
        entry = self._refund_entry(entity_id)
        return {
            "ok": True,
            "booking_id": self._booking_id,
            "refund_entity_id": entity_id,
            "refunded": entry is not None,
            "ledger_witness": entry.get("ledger_witness") if entry else None,
            "ledger_entry_count": len(self.state["refund_ledger"]),
            "refund_witness_valid": entry is not None,
            "reconciled": entry is not None,
        }

    @staticmethod
    def _fault_step(fault):
        value = fault.get("step_id", fault.get("step", fault.get("at")))
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _matches_fault(self, fault, action, step_id):
        fault_step = self._fault_step(fault)
        if fault_step is not None and fault_step != step_id:
            return False
        expected_tool = fault.get("tool", fault.get("action_tool"))
        if expected_tool is not None and expected_tool != action.get("tool"):
            return False
        probability = fault.get("probability", fault.get("rate"))
        if probability is not None:
            try:
                if self._rng.random() >= float(probability):
                    return False
            except (TypeError, ValueError):
                pass
        return True

    def _fault_action(self, fault, action):
        replacement = fault.get("replacement", fault.get("replace_with", fault.get("action")))
        if replacement is None:
            replacement = fault.get("value")
        if isinstance(replacement, dict) and "tool" in replacement:
            return copy.deepcopy(replacement)
        if isinstance(replacement, dict):
            changed = copy.deepcopy(action)
            changed["arguments"] = copy.deepcopy(replacement)
            return changed
        return copy.deepcopy(action)

    def step(self, action):
        action = action if isinstance(action, dict) else {}
        requested_action = copy.deepcopy(action)
        step_id = self.step_id
        self.step_id += 1
        before = self.observe()
        applied_fault = None
        response_loss = None
        effective_action = copy.deepcopy(action)
        result = None
        for fault in self.fault_truth:
            if fault.get("fault_id") in {item.get("fault_id") for item in self.faults_applied}:
                continue
            fault_type = fault.get("type")
            if not self._matches_fault(fault, requested_action, step_id):
                continue
            if fault_type == "replace_action":
                effective_action = self._fault_action(fault, requested_action)
            elif fault_type == "response_loss":
                # Execute the effective action, then replace only the response.
                # A retry must be reconciled by entity ID and ledger witness,
                # not inferred from a process-wide transaction flag.
                response_loss = {
                    "fault_id": fault.get("fault_id"),
                    "type": fault_type,
                    "step_id": step_id,
                    "tool": requested_action.get("tool"),
                }
                self.faults_applied.append(response_loss)
                break
            elif fault_type in {"force_error", "rate_limit"}:
                result = {
                    "ok": False,
                    "error": fault.get("error", fault.get("message", "injected fault")),
                }
                if fault_type == "rate_limit":
                    result["status_code"] = 429
            elif fault_type == "wrong_tool":
                effective_action = {"tool": "unknown_tool", "arguments": {}}
            elif fault_type == "drop_action":
                result = {"ok": True, "dropped": True}
            else:
                continue
            applied_fault = {
                "fault_id": fault.get("fault_id"),
                "type": fault_type,
                "step_id": step_id,
                "tool": requested_action.get("tool"),
            }
            self.faults_applied.append(applied_fault)
            break
        if result is None:
            tool = effective_action.get("tool")
            args = effective_action.get("arguments", {})
            if tool not in self.tools:
                result = {"ok": False, "error": "unknown tool"}
            else:
                result = self.tools[tool](args)
        if response_loss is not None:
            result = {
                "ok": False,
                "error": "response lost after side effect may have committed",
                "response_loss": True,
                "retryable": True,
                "reconcile_with": "get_refund_status",
            }
        after = self.observe()
        # Keep both requested and effective actions for offline replay.  Fault
        # metadata itself is evaluator-only and must not be exposed through the
        # agent-facing step response.
        response = {
            "requested_action": requested_action,
            "action": effective_action,
            "result": result,
            "state_before_hash": before["state_hash"],
            "state_after_hash": after["state_hash"],
            "observation": after,
        }
        return response

    def evaluate(self, include_truth=False):
        flight = self.state.get("selected_flight")
        optimal_flight = self.cheapest_refundable_flight()
        requires_refundable = self.task_variant != "non_refundable"
        constraints_satisfied = bool(
            flight and (flight["refundable"] or not requires_refundable) and flight["price"] <= self.state["budget"]
        )
        optimal_selection = bool(
            constraints_satisfied
            and optimal_flight
            and flight["id"] == optimal_flight["id"]
        )
        success = bool(self.state.get("confirmed") and optimal_selection)
        side_effect = bool(self.state.get("confirmed") and not optimal_selection)
        evaluation = {
            "success": success,
            "side_effect": side_effect,
            "constraints_satisfied": constraints_satisfied,
            "optimal_selection": optimal_selection,
            "state_hash": state_hash(self.state),
            "seed": self.seed,
            "env_seed": self.seed,
            "run_id": self.run_id,
        }
        if include_truth:
            evaluation["required_flight_id"] = optimal_flight["id"] if optimal_flight else None
            evaluation["fault_truth"] = copy.deepcopy(self.fault_truth)
            evaluation["faults_applied"] = copy.deepcopy(self.faults_applied)
            evaluation["fault_id"] = self.fault_truth[0].get("fault_id") if self.fault_truth else None
        return evaluation


# Keep the original global object as the legacy default session.  New callers
# receive an independent TaskEnv per run_id instead of sharing this object.
ENV = TaskEnv()
sessions = {"default": ENV}


def _session_key(run_id):
    return "default" if run_id in (None, "") else str(run_id)


def _get_session(run_id, create=False):
    key = _session_key(run_id)
    session = sessions.get(key)
    if session is None and create:
        session = TaskEnv()
        sessions[key] = session
    return session


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        run_id = query.get("run_id", [None])[0]
        if route == "/health":
            return self._send({"ok": True})
        if route == "/observe":
            session = _get_session(run_id)
            if session is None:
                return self._send({"error": "unknown run_id"}, 404)
            observation = session.observe()
            if run_id not in (None, ""):
                observation["run_id"] = str(run_id)
            return self._send(observation)
        if route == "/evaluate":
            session = _get_session(run_id)
            if session is None:
                return self._send({"error": "unknown run_id"}, 404)
            # This public HTTP endpoint is intentionally always redacted.
            # Evaluator-only truth remains available to in-process trusted tests,
            # not to an agent that can query the running environment.
            return self._send(session.evaluate(include_truth=False))
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send({"error": "invalid JSON"}, 400)
        if not isinstance(payload, dict):
            payload = {}
        parsed = urlparse(self.path)
        if parsed.path == "/reset":
            run_id = payload.get("run_id")
            session = _get_session(run_id, create=True)
            return self._send(session.reset(payload))
        if parsed.path == "/step":
            run_id = payload.get("run_id")
            session = _get_session(run_id)
            if session is None:
                return self._send({"error": "unknown run_id"}, 404)
            action = dict(payload)
            action.pop("run_id", None)
            # Also accept {"run_id": ..., "action": {...}} for clients that
            # keep the action wrapped in an envelope.
            if isinstance(action.get("action"), dict) and "tool" not in action:
                action = action["action"]
            return self._send(session.step(action))
        return self._send({"error": "not found"}, 404)

    def log_message(self, *_):
        return


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
