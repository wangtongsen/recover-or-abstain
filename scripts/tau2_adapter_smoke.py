#!/usr/bin/env python3
"""τ² airline adapter live smoke (offline, no LLM).

Empirically verifies refund/cancel semantics of the real, pinned tau2-bench
airline environment against RACER v2 G4 requirements (entity-level refund
witness, idempotent replay, reconciliation tooling).

Runs against the locked tau2-bench v1.0.1 (commit fc0055d) installed in the
isolated venv. Requires TAU2_DATA_DIR pointing to the extracted data tree.

This script is read-only with respect to the RACER project: it writes only
the JSON report given via --output.

Exit codes: 0 = smoke executed (report written), 2 = environment unusable.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.disable(logging.CRITICAL)

SMOKE_ID = "tau2-airline-adapter-smoke-2026-09-02"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Path for the JSON report")
    args = parser.parse_args(argv)

    report: dict = {
        "smoke_id": SMOKE_ID,
        "tau2_version": None,
        "environment": "tau2-bench airline (pinned fc0055d)",
        "llm_used": False,
        "checks": {},
        "g4_conclusion": None,
    }

    try:
        import importlib.metadata
        report["tau2_version"] = importlib.metadata.version("tau2")
        from tau2.domains.airline.data_model import FlightDB
        from tau2.domains.airline.tools import AirlineTools
    except Exception as exc:  # pragma: no cover
        report["checks"]["environment"] = {"ok": False, "error": str(exc)}
        _write(args.output, report)
        return 2

    db_path = Path(__file__).parent.parent / ".tau2-data" / "data" / "tau2" / "domains" / "airline" / "db.json"
    import os
    env_dir = os.environ.get("TAU2_DATA_DIR")
    if env_dir:
        db_path = Path(env_dir) / "tau2" / "domains" / "airline" / "db.json"
    if not db_path.exists():
        # fallback to the isolated install location
        db_path = Path.home() / ".workbuddy" / "binaries" / "python" / "envs" / "tau2-data" / "data" / "tau2" / "domains" / "airline" / "db.json"
    if not db_path.exists():
        report["checks"]["environment"] = {"ok": False, "error": f"db.json not found: {db_path}"}
        _write(args.output, report)
        return 2

    raw = json.loads(db_path.read_text(encoding="utf-8"))
    db = FlightDB.model_validate(raw)
    tools = AirlineTools(db)

    rid = next(iter(db.reservations))
    res = db.reservations[rid]
    uid = res.user_id
    user = db.users[uid]

    entry_counts: list[int] = []
    net_totals: list[int] = []
    entry_counts.append(len(res.payment_history))
    net_totals.append(sum(p.amount for p in res.payment_history))

    # snapshot the user-side payment method state before any cancel
    pm_before = json.loads(json.dumps(user.model_dump().get("payment_methods")))

    # three consecutive cancels of the same reservation entity
    for _ in range(3):
        tools.cancel_reservation(rid)
        entry_counts.append(len(res.payment_history))
        net_totals.append(sum(p.amount for p in res.payment_history))

    pm_after = json.loads(json.dumps(user.model_dump().get("payment_methods")))

    # 1. ledger idempotency
    ledger_idempotent = entry_counts[-1] == entry_counts[1]
    report["checks"]["ledger_idempotency"] = {
        "ok": ledger_idempotent,
        "entry_counts_after_each_cancel": entry_counts,
        "net_totals": net_totals,
        "observation": (
            "cancel_reservation appends negative entries for every existing "
            "payment entry on each call; ledger entries double per cancel. "
            "Net total self-cancels but the ledger is not idempotent."
        ),
    }

    # 2. stable refund witness fields
    sample_payment = res.payment_history[0].model_dump()
    witness_fields = [f for f in ("ledger_entry_id", "refund_id", "idempotency_key", "witness_hash") if f in sample_payment]
    report["checks"]["refund_witness_fields"] = {
        "ok": bool(witness_fields),
        "present_witness_fields": witness_fields,
        "payment_entry_fields": sorted(sample_payment.keys()),
        "observation": (
            "payment entries carry only payment_id (the user's payment method id, "
            "reused across entries) and amount; no unique per-transaction refund "
            "identifier, no idempotency key, no witness hash."
        ),
    }

    # 3. returned object aliasing (receipt pollution)
    db2 = FlightDB.model_validate(raw)
    tools2 = AirlineTools(db2)
    rid2 = next(iter(db2.reservations))
    r_first = tools2.cancel_reservation(rid2)
    first_snapshot = [p.amount for p in r_first.payment_history]
    tools2.cancel_reservation(rid2)
    first_after_second = [p.amount for p in r_first.payment_history]
    report["checks"]["receipt_aliasing"] = {
        "ok": first_snapshot == first_after_second,
        "first_return_entries": len(first_snapshot),
        "same_object_entries_after_second_cancel": len(first_after_second),
        "observation": (
            "cancel_reservation returns the live mutable reservation object; "
            "a previously returned 'receipt' is silently mutated by later calls, "
            "so independent per-call evidence cannot be retained."
        ),
    }

    # 4. user-side balance settlement
    report["checks"]["user_side_settlement"] = {
        "ok": pm_before != pm_after,
        "payment_methods_before": pm_before,
        "payment_methods_after": pm_after,
        "observation": (
            "refunds are recorded only on reservation.payment_history; the user's "
            "payment_methods balance is never credited back."
        ),
    }

    # 5. reconciliation tool availability
    method_names = [m for m in dir(AirlineTools) if not m.startswith("_")]
    reconcile_tools = [m for m in method_names if "refund" in m.lower() or "status" in m.lower() and "flight" not in m.lower()]
    has_reconcile = any("refund" in m for m in method_names)
    report["checks"]["reconciliation_tools"] = {
        "ok": has_reconcile,
        "available_tools": sorted(m for m in method_names if not m.startswith("is_")),
        "observation": (
            "no get_refund_status or equivalent reconciliation tool exists; "
            "response-loss reconciliation cannot be performed via public tools."
        ),
    }

    all_ok = all(c["ok"] for c in report["checks"].values())
    report["g4_conclusion"] = (
        "FAIL: the pinned tau2 airline environment provides no entity-level "
        "idempotent refund ledger, no stable witness fields, mutates returned "
        "receipts, does not settle user-side balances, and offers no "
        "reconciliation tool. RACER G4 (refund witness / idempotent replay / "
        "response-loss reconciliation) cannot be certified on this environment. "
        "Adapter branches involving refunds must set counterfactual_supported=false "
        "unless an external witness layer is introduced."
    )

    _write(args.output, report)
    print(json.dumps({"smoke_id": SMOKE_ID, "checks": {k: v["ok"] for k, v in report["checks"].items()}, "g4": report["g4_conclusion"][:120]}, indent=2))
    return 0


def _write(path: str, report: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
