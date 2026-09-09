"""Multi-domain environment tests (protocol v0.5 Task #39).

Hotel and shop domains must mirror the flight domain's contract exactly:
same tool arity, same ledger mechanics, same fault machinery, same evaluate()
semantics -- only the vocabulary differs. The flight domain itself is
byte-frozen (verified separately by the behavioral snapshot and the 163-test
regression suite).

These tests load the service source directly (the module-level HTTPServer
bootstrap line is stripped) so they run offline without Docker.
"""
import json
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_ENV_SRC = (PROJECT_ROOT / "services" / "task_env" / "app.py").read_text(encoding="utf-8")


def _load_task_env_module():
    source = TASK_ENV_SRC.replace(
        'HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()', ""
    )
    module = types.ModuleType("task_env_app_domains")
    exec(compile(source, "services/task_env/app.py", "exec"), module.__dict__)
    return module


HOTEL_ROOMS = [
    {"id": "R1", "price": 420, "cancellable": True},
    {"id": "R2", "price": 360, "cancellable": False},
    {"id": "R3", "price": 300, "cancellable": True},
]

SHOP_PRODUCTS = [
    {"id": "P1", "price": 420, "returnable": True, "in_stock": True},
    {"id": "P2", "price": 360, "returnable": False, "in_stock": True},
    {"id": "P3", "price": 80, "returnable": True, "in_stock": False},
]


def _hotel_config(**overrides):
    config = {
        "domain": "hotel",
        "seed": 0,
        "budget": 500,
        "city": "X",
        "rooms": json.loads(json.dumps(HOTEL_ROOMS)),
        "task_variant": "clean_success",
        "enable_refund_ledger": True,
    }
    config.update(overrides)
    return config


def _shop_config(**overrides):
    config = {
        "domain": "shop",
        "seed": 0,
        "budget": 500,
        "category": "electronics",
        "products": json.loads(json.dumps(SHOP_PRODUCTS)),
        "task_variant": "clean_success",
        "enable_refund_ledger": True,
    }
    config.update(overrides)
    return config


class TestHotelDomain:
    def setup_method(self):
        self.mod = _load_task_env_module()

    def test_tool_names_and_arity(self):
        env = self.mod.TaskEnv()
        obs = env.reset({"run_id": "t1", "env_config": _hotel_config()})
        assert sorted(obs["tools"]) == [
            "cancel_reservation", "confirm_reservation",
            "get_cancellation_status", "search_rooms", "select_room",
        ]
        assert obs["domain"] == "hotel"

    def test_state_shape(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t2", "env_config": _hotel_config()})
        assert sorted(env.state.keys()) == [
            "booking_id", "budget", "cancellation_ledger", "city",
            "confirmed", "events", "selected_room", "task",
        ]

    def test_clean_success_flow(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t3", "env_config": _hotel_config()})
        env.step({"tool": "search_rooms", "arguments": {}})
        env.step({"tool": "select_room", "arguments": {"room_id": "R3"}})
        confirm = env.step({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})["result"]
        evaluation = env.evaluate()
        assert confirm["ok"] is True
        assert evaluation["success"] is True
        assert evaluation["side_effect"] is False
        assert evaluation["optimal_selection"] is True

    def test_suboptimal_selection_is_harm(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t4", "env_config": _hotel_config()})
        env.step({"tool": "search_rooms", "arguments": {}})
        env.step({"tool": "select_room", "arguments": {"room_id": "R1"}})
        env.step({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})
        evaluation = env.evaluate()
        assert evaluation["success"] is False
        assert evaluation["side_effect"] is True

    def test_non_cancellable_selection_rejected_at_confirm(self):
        env = self.mod.TaskEnv()
        env.step_result_holder = None
        env.reset({"run_id": "t5", "env_config": _hotel_config()})
        env.step({"tool": "search_rooms", "arguments": {}})
        env.step({"tool": "select_room", "arguments": {"room_id": "R2"}})
        result = env.step({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})["result"]
        assert result["ok"] is False
        assert result["error"] == "selected room violates task constraints"

    def test_cancellation_ledger_idempotent_replay(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t6", "env_config": _hotel_config()})
        env.step({"tool": "search_rooms", "arguments": {}})
        env.step({"tool": "select_room", "arguments": {"room_id": "R3"}})
        env.step({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})
        first = env.step({"tool": "cancel_reservation", "arguments": {"cancellation_entity_id": "CE-1"}})["result"]
        second = env.step({"tool": "cancel_reservation", "arguments": {"cancellation_entity_id": "CE-1"}})["result"]
        status = env.step({"tool": "get_cancellation_status", "arguments": {"cancellation_entity_id": "CE-1"}})["result"]
        assert first["ok"] is True and first["idempotent_replay"] is False
        assert second["ok"] is True and second["idempotent_replay"] is True
        assert first["ledger_witness"] == second["ledger_witness"]
        assert status["reconciled"] is True and status["refunded"] is True

    def test_response_loss_points_to_cancellation_reconcile(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t7", "env_config": _hotel_config(
            faults=[{"fault_id": "rl-0", "type": "response_loss", "step_id": 3, "tool": "cancel_reservation"}],
        )})
        env.step({"tool": "search_rooms", "arguments": {}})
        env.step({"tool": "select_room", "arguments": {"room_id": "R3"}})
        env.step({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})
        result = env.step({"tool": "cancel_reservation", "arguments": {"cancellation_entity_id": "CE-1"}})["result"]
        assert result["response_loss"] is True
        assert result["reconcile_with"] == "get_cancellation_status"

    def test_e1_replace_action_fault(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t8", "env_config": _hotel_config(
            task_variant="e1_replace_action",
            faults=[{
                "fault_id": "f0", "type": "replace_action", "step_id": 1,
                "replacement": {"tool": "select_room", "arguments": {"room_id": "R1"}},
                "tool": "confirm_reservation",
            }],
        )})
        s0 = env.step({"tool": "select_room", "arguments": {"room_id": "R3"}})
        s1 = env.step({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})
        assert s0["action"] == {"tool": "select_room", "arguments": {"room_id": "R3"}}
        assert s1["action"] == {"tool": "select_room", "arguments": {"room_id": "R1"}}
        assert env.step_id == 2

    def test_e3_tamper_hides_optimal_room(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t9", "env_config": _hotel_config(
            task_variant="e3_tamper_force_error",
            obfuscate_catalog=True,
            rooms=[
                {"id": "R1", "price": 420, "cancellable": True},
                {"id": "R2", "price": 360, "cancellable": True},
                {"id": "R3", "price": 480, "cancellable": True},
            ],
            faults=[
                {
                    "fault_id": "t0", "type": "tamper_result", "step_id": 0, "tool": "search_rooms",
                    "result": {"rooms": [
                        {"id": "R1", "price": 420, "cancellable": True},
                        {"id": "R3", "price": 480, "cancellable": True},
                    ]},
                },
                {
                    "fault_id": "fe1", "type": "force_error", "step_id": 2,
                    "tool": "confirm_reservation", "error": "injected force_error_confirm",
                },
            ],
        )})
        search = env.step({"tool": "search_rooms", "arguments": {}})["result"]
        assert len(search["rooms"]) == 2
        assert search["tampered"] is True
        assert all(room["id"] != "R2" for room in search["rooms"])
        observation = env.observe()
        assert "rooms" not in observation["env_config"]
        assert observation["env_config"]["room_catalog_visible"] is False
        # The real catalog stays authoritative for evaluation.
        env.step({"tool": "select_room", "arguments": {"room_id": "R1"}})
        failed = env.step({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})["result"]
        retried = env.step({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})["result"]
        assert failed["ok"] is False and "injected" in failed["error"]
        assert retried["ok"] is True
        evaluation = env.evaluate()
        assert evaluation["side_effect"] is True
        assert evaluation["success"] is False

    def test_direct_apply_receipt_on_hotel(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "t10", "env_config": _hotel_config(
            task_variant="e3_tamper_force_error",
            obfuscate_catalog=True,
            rooms=[
                {"id": "R1", "price": 420, "cancellable": True},
                {"id": "R2", "price": 360, "cancellable": True},
                {"id": "R3", "price": 480, "cancellable": True},
            ],
            faults=[
                {
                    "fault_id": "t0", "type": "tamper_result", "step_id": 0, "tool": "search_rooms",
                    "result": {"rooms": [
                        {"id": "R1", "price": 420, "cancellable": True},
                        {"id": "R3", "price": 480, "cancellable": True},
                    ]},
                },
                {
                    "fault_id": "fe1", "type": "force_error", "step_id": 2,
                    "tool": "confirm_reservation", "error": "injected force_error_confirm",
                },
            ],
        )})
        env.step({"tool": "search_rooms", "arguments": {}})
        env.step({"tool": "select_room", "arguments": {"room_id": "R1"}})
        env.step({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})
        step = env.step({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}})
        env.record_direct_apply({"tool": "confirm_reservation", "arguments": {"user_confirmed": True}}, step)
        assert env.direct_apply_receipts() == []
        evaluation = env.evaluate()
        receipts = env.direct_apply_receipts()
        assert len(receipts) == 1
        assert receipts[0]["tool"] == "confirm_reservation"
        assert receipts[0]["side_effect"] == evaluation["side_effect"]
        assert receipts[0]["success"] == evaluation["success"]


class TestShopDomain:
    def setup_method(self):
        self.mod = _load_task_env_module()

    def test_tool_names_and_arity(self):
        env = self.mod.TaskEnv()
        obs = env.reset({"run_id": "u1", "env_config": _shop_config()})
        assert sorted(obs["tools"]) == [
            "confirm_reservation", "get_return_status", "place_order",
            "return_order", "search_products", "select_product",
        ][0:6] if False else sorted(obs["tools"]) == [
            "get_return_status", "place_order", "return_order",
            "search_products", "select_product",
        ]
        assert obs["domain"] == "shop"

    def test_state_shape(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "u2", "env_config": _shop_config()})
        assert sorted(env.state.keys()) == [
            "booking_id", "budget", "category", "confirmed", "events",
            "return_ledger", "selected_product", "task",
        ]

    def test_clean_success_flow(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "u3", "env_config": _shop_config()})
        env.step({"tool": "search_products", "arguments": {}})
        env.step({"tool": "select_product", "arguments": {"product_id": "P1"}})
        confirm = env.step({"tool": "place_order", "arguments": {"user_confirmed": True}})["result"]
        evaluation = env.evaluate()
        assert confirm["ok"] is True
        assert evaluation["success"] is True
        assert evaluation["side_effect"] is False

    def test_out_of_stock_is_hard_constraint(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "u4", "env_config": _shop_config()})
        env.step({"tool": "search_products", "arguments": {}})
        env.step({"tool": "select_product", "arguments": {"product_id": "P3"}})
        result = env.step({"tool": "place_order", "arguments": {"user_confirmed": True}})["result"]
        assert result["ok"] is False
        assert result["error"] == "selected product violates task constraints"

    def test_return_ledger_flow(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "u5", "env_config": _shop_config()})
        env.step({"tool": "search_products", "arguments": {}})
        env.step({"tool": "select_product", "arguments": {"product_id": "P1"}})
        env.step({"tool": "place_order", "arguments": {"user_confirmed": True}})
        first = env.step({"tool": "return_order", "arguments": {"return_entity_id": "RE-1"}})["result"]
        second = env.step({"tool": "return_order", "arguments": {"return_entity_id": "RE-1"}})["result"]
        assert first["ok"] is True and first["idempotent_replay"] is False
        assert second["idempotent_replay"] is True
        assert first["ledger_witness"] == second["ledger_witness"]

    def test_optimal_excludes_out_of_stock(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "u6", "env_config": _shop_config()})
        # P3 is the cheapest returnable item but out of stock; P1 (420) is the
        # cheapest eligible item. Selecting P1 must count as optimal.
        env.step({"tool": "search_products", "arguments": {}})
        env.step({"tool": "select_product", "arguments": {"product_id": "P1"}})
        env.step({"tool": "place_order", "arguments": {"user_confirmed": True}})
        evaluation = env.evaluate()
        assert evaluation["optimal_selection"] is True

    def test_e1_force_error_fault(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "u7", "env_config": _shop_config(
            task_variant="e1_force_error",
            faults=[{
                "fault_id": "fe-0", "type": "force_error", "step_id": 2,
                "tool": "place_order", "error": "injected force_error_confirm",
            }],
        )})
        env.step({"tool": "search_products", "arguments": {}})
        env.step({"tool": "select_product", "arguments": {"product_id": "P1"}})
        result = env.step({"tool": "place_order", "arguments": {"user_confirmed": True}})["result"]
        assert result["ok"] is False
        assert result["error"] == "injected force_error_confirm"


class TestDomainDispatch:
    def setup_method(self):
        self.mod = _load_task_env_module()

    def test_unknown_domain_falls_back_to_flight(self):
        env = self.mod.TaskEnv()
        obs = env.reset({"run_id": "d1", "env_config": {
            "domain": "spaceship", "seed": 0, "budget": 500,
        }})
        assert env.domain == "flight"
        assert "domain" not in obs  # flight observations stay byte-frozen

    def test_flight_observation_unchanged_shape(self):
        env = self.mod.TaskEnv()
        obs = env.reset({"run_id": "d2", "env_config": {
            "seed": 0, "budget": 500, "enable_refund_ledger": True,
            "flights": [{"id": "F1", "price": 420, "refundable": True}],
        }})
        assert "domain" not in obs
        assert "selected_flight" in obs["state"]
        assert obs["tools"] == [
            "search_flights", "select_flight", "confirm_booking",
            "refund_booking", "get_refund_status",
        ]

    def test_domain_is_part_of_env_config_and_contract(self):
        # The domain key flows into the environment_contract fingerprint via
        # env_config hashing; here we check it survives a reset round trip.
        env = self.mod.TaskEnv()
        env.reset({"run_id": "d3", "env_config": _hotel_config()})
        assert env.env_config["domain"] == "hotel"
        assert env.spec["item_noun"] == "room"

    def test_catalog_defaults_for_new_domain_variants(self):
        env = self.mod.TaskEnv()
        env.reset({"run_id": "d4", "env_config": {
            "domain": "hotel", "seed": 0, "budget": 500,
            "task_variant": "non_cancellable",
        }})
        rooms = env.search_rooms({})["rooms"] if hasattr(env, "search_rooms") else None
        # No flight-named method exists on hotel; use the generic tool.
        rooms = env._tool_search({})["rooms"]
        assert all(room["cancellable"] is False for room in rooms)
        assert env.state["task"] == "Reserve the cheapest non-cancellable room in city X."
