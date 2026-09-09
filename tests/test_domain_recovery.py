"""Cross-domain diagnoser + recovery policy tests (protocol v0.5 Task #39).

The hotel/shop planning-error paths must mirror the flight contract:
- diagnoser: domain constraint error -> planning-error cause with a
  repair_target derived from the public listing (never fault truth);
- recovery: replace_argument patch from evidence.repair_target, abstain
  when no usable target (never a fabricated id);
- flight behavior unchanged (frozen F1 literal, frozen cause names).
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(path, name):
    source = Path(path).read_text()
    for line in (
        '    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()',
        'HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()',
    ):
        if line in source:
            source = source.replace(line, "    pass")
            break
    module = types.ModuleType(name)
    exec(compile(source, path, "exec"), module.__dict__)
    return module


diagnoser = _load(PROJECT_ROOT / "services" / "diagnoser" / "app.py", "diagnoser_app")
recovery = _load(PROJECT_ROOT / "services" / "recovery_policy" / "app.py", "recovery_app")


def _shop_planning_trace():
    return [
        {
            "action": {"tool": "search_products", "arguments": {}},
            "result": {"ok": True, "products": [
                {"id": "P1", "price": 420, "returnable": True, "in_stock": True},
                {"id": "P2", "price": 360, "returnable": False, "in_stock": True},
                {"id": "P3", "price": 80, "returnable": True, "in_stock": False},
            ]},
            "observation": {"state": {"task": "Buy the cheapest returnable product in category electronics.", "budget": 500}},
        },
        {
            "action": {"tool": "select_product", "arguments": {"product_id": "P3"}},
            "result": {"ok": True, "selected": {"id": "P3", "price": 80, "returnable": True, "in_stock": False}},
            "observation": {"state": {"task": "Buy the cheapest returnable product in category electronics.", "budget": 500}},
        },
        {
            "action": {"tool": "place_order", "arguments": {"user_confirmed": True}},
            "result": {"ok": False, "error": "selected product violates task constraints"},
            "observation": {"state": {"task": "Buy the cheapest returnable product in category electronics.", "budget": 500}},
        },
    ]


def _hotel_planning_trace():
    return [
        {
            "action": {"tool": "search_rooms", "arguments": {}},
            "result": {"ok": True, "rooms": [
                {"id": "R1", "price": 420, "cancellable": True},
                {"id": "R2", "price": 360, "cancellable": False},
            ]},
            "observation": {"state": {"task": "Reserve the cheapest cancellable room in city X.", "budget": 500}},
        },
        {
            "action": {"tool": "select_room", "arguments": {"room_id": "R2"}},
            "result": {"ok": True, "selected": {"id": "R2", "price": 360, "cancellable": False}},
            "observation": {"state": {"task": "Reserve the cheapest cancellable room in city X.", "budget": 500}},
        },
        {
            "action": {"tool": "confirm_reservation", "arguments": {"user_confirmed": True}},
            "result": {"ok": False, "error": "selected room violates task constraints"},
            "observation": {"state": {"task": "Reserve the cheapest cancellable room in city X.", "budget": 500}},
        },
    ]


class ShopDiagnosisTest(unittest.TestCase):

    def test_constraint_error_yields_planning_error_with_repair_target(self):
        diagnosis = diagnoser.diagnose(_shop_planning_trace())
        planning = [c for c in diagnosis["candidates"] if c["category"] == "planning_error"]
        self.assertEqual(len(planning), 1)
        candidate = planning[0]
        self.assertEqual(candidate["cause"], "selected_non_returnable_product")
        self.assertEqual(candidate["evidence"]["repair_target"]["id"], "P1")

    def test_repair_target_excludes_out_of_stock_and_soft_violators(self):
        diagnosis = diagnoser.diagnose(_shop_planning_trace())
        candidate = [c for c in diagnosis["candidates"] if c["category"] == "planning_error"][0]
        target = candidate["evidence"]["repair_target"]
        # P3 (cheapest) is out of stock; P2 is non-returnable -> target is P1.
        self.assertEqual(target["id"], "P1")
        self.assertEqual(target["price"], 420)

    def test_racer_issues_derived_replace_argument(self):
        diagnosis = diagnoser.diagnose(_shop_planning_trace())
        decision = recovery.racer_decision(diagnosis)
        self.assertEqual(decision["decision"], "replace_argument")
        self.assertEqual(decision["patch"], {"tool": "select_product", "arguments": {"product_id": "P1"}})

    def test_missing_repair_target_degrades_to_abstain_or_clarification(self):
        trace = _shop_planning_trace()
        # Strip the search result so no listing exists to derive from.
        trace[0]["result"] = {"ok": True}
        diagnosis = diagnoser.diagnose(trace)
        candidate = [c for c in diagnosis["candidates"] if c["category"] == "planning_error"][0]
        self.assertNotIn("repair_target", candidate["evidence"])
        decision = recovery.racer_decision(diagnosis)
        self.assertIn(decision["decision"], ("abstain", "ask_clarification"))
        if decision["decision"] == "ask_clarification":
            self.assertIsNone(decision["patch"])


class HotelDiagnosisTest(unittest.TestCase):

    def test_constraint_error_yields_cancellable_cause(self):
        diagnosis = diagnoser.diagnose(_hotel_planning_trace())
        planning = [c for c in diagnosis["candidates"] if c["category"] == "planning_error"]
        self.assertEqual(len(planning), 1)
        self.assertEqual(planning[0]["cause"], "selected_non_cancellable_room")
        self.assertEqual(planning[0]["evidence"]["repair_target"]["id"], "R1")

    def test_racer_issues_derived_replace_argument(self):
        diagnosis = diagnoser.diagnose(_hotel_planning_trace())
        decision = recovery.racer_decision(diagnosis)
        self.assertEqual(decision["patch"], {"tool": "select_room", "arguments": {"room_id": "R1"}})

    def test_baselines_dispatch_on_hotel_cause(self):
        diagnosis = diagnoser.diagnose(_hotel_planning_trace())
        for baseline_id in ("fixed_retry", "always_recover", "step_by_step_diagnosis", "generic_reflection"):
            decision = recovery.baseline_dispatch(baseline_id, {"diagnosis": diagnosis})
            self.assertIsNotNone(decision, baseline_id)
            # Planning-error top candidate with a repair target must never
            # fabricate a flight-style patch.
            if decision.get("patch") is not None:
                self.assertNotEqual(decision["patch"].get("tool"), "select_flight", baseline_id)


class FlightFrozenBehaviorTest(unittest.TestCase):
    """The flight planning-error path stays byte-frozen (F1 literal, cause name)."""

    def _flight_trace(self):
        return [
            {
                "action": {"tool": "select_flight", "arguments": {"flight_id": "F2"}},
                "result": {"ok": True, "selected": {"id": "F2", "price": 360, "refundable": False}},
                "observation": {"state": {"task": "Book the cheapest refundable flight from A to B.", "budget": 500}},
            },
            {
                "action": {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
                "result": {"ok": False, "error": "selected flight violates task constraints"},
                "observation": {"state": {"task": "Book the cheapest refundable flight from A to B.", "budget": 500}},
            },
        ]

    def test_flight_cause_and_frozen_patch(self):
        diagnosis = diagnoser.diagnose(self._flight_trace())
        candidate = [c for c in diagnosis["candidates"] if c["category"] == "planning_error"][0]
        self.assertEqual(candidate["cause"], "selected_non_refundable_flight")
        self.assertEqual(candidate["constraint"], "selected_flight must be refundable")
        decision = recovery.racer_decision(diagnosis)
        self.assertEqual(decision["patch"], {"tool": "select_flight", "arguments": {"flight_id": "F1"}})

    def test_flight_step_id_semantics_unchanged(self):
        diagnosis = diagnoser.diagnose(self._flight_trace())
        candidate = [c for c in diagnosis["candidates"] if c["category"] == "planning_error"][0]
        # The confirm-error branch attributes to the prior select step.
        self.assertEqual(candidate["step_id"], 0)

    def test_flight_repair_target_also_derived_but_patch_stays_frozen(self):
        # The diagnoser may now attach repair_target to flight candidates
        # (additive evidence), but the recovery patch stays the F1 literal.
        trace = [
            {
                "action": {"tool": "search_flights", "arguments": {}},
                "result": {"ok": True, "flights": [
                    {"id": "F1", "price": 420, "refundable": True},
                    {"id": "F2", "price": 360, "refundable": False},
                ]},
                "observation": {"state": {"task": "Book the cheapest refundable flight from A to B.", "budget": 500}},
            },
            {
                "action": {"tool": "select_flight", "arguments": {"flight_id": "F2"}},
                "result": {"ok": True, "selected": {"id": "F2", "price": 360, "refundable": False}},
                "observation": {"state": {"task": "Book the cheapest refundable flight from A to B.", "budget": 500}},
            },
            {
                "action": {"tool": "confirm_booking", "arguments": {"user_confirmed": True}},
                "result": {"ok": False, "error": "selected flight violates task constraints"},
                "observation": {"state": {"task": "Book the cheapest refundable flight from A to B.", "budget": 500}},
            },
        ]
        diagnosis = diagnoser.diagnose(trace)
        candidate = [c for c in diagnosis["candidates"] if c["category"] == "planning_error"][0]
        # Flight patch remains the frozen literal regardless of derived target.
        decision = recovery.racer_decision(diagnosis)
        self.assertEqual(decision["patch"], {"tool": "select_flight", "arguments": {"flight_id": "F1"}})


class CrossDomainRetryPathTest(unittest.TestCase):

    def test_hotel_force_error_retry_patch_uses_hotel_tools(self):
        trace = [
            {
                "action": {"tool": "confirm_reservation", "arguments": {"user_confirmed": True}},
                "result": {"ok": False, "error": "injected force_error_confirm"},
            },
        ]
        diagnosis = diagnoser.diagnose(trace)
        decision = recovery.fixed_retry_decision(diagnosis)
        self.assertEqual(decision["decision"], "retry")
        self.assertEqual(decision["patch"], {"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})


if __name__ == "__main__":
    unittest.main()
