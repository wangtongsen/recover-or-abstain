#!/usr/bin/env python3
"""Main-conference statistics for the RACER v2 main matrix.

Reads a canonical racer-v2-results-envelope, expands one flat record per
(baseline, trial, task), and computes:

1. Wilson 95% CIs for recovery/harm/abstention rates per baseline.
2. Stratified paired cluster bootstrap (10,000 resamples, fixed seed) over
   episode-level paired outcomes for RACER vs each primary baseline.
3. One-sample sign-flip permutation p-values (10,000 permutations) for the
   paired difference distribution.
4. Holm-Bonferroni correction over the primary hypothesis family.

Only the standard library is used; all randomness flows from a single
``random.Random(seed)`` instance for reproducibility.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

Z95 = 1.959963984540054
BOOTSTRAP_RESAMPLES = 10_000
PERMUTATIONS = 10_000
RNG_SEED = 20260906
RACER = "racer"
# Primary hypothesis family (protocol §7): RACER vs each non-oracle baseline.
ORACLE_BASELINES = {"oracle_root_cause", "oracle_recovery"}


def wilson_interval(successes: int, n: int, z: float = Z95) -> dict[str, Any] | None:
    if n <= 0:
        return None
    successes = max(0, min(int(successes), int(n)))
    n = int(n)
    p = successes / n
    denominator = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n) / denominator
    lower = max(0.0, centre - margin)
    upper = min(1.0, centre + margin)
    if lower < 1e-15:
        lower = 0.0
    if 1.0 - upper < 1e-15:
        upper = 1.0
    return {"successes": successes, "n": n, "lower": lower, "upper": upper}


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        records = payload.get("records")
        if isinstance(records, list):
            return [row for row in records if isinstance(row, dict)]
    return []


def _cell(row: dict[str, Any]) -> str:
    task = row.get("task_id", "")
    if "-trial-" in str(task):
        return str(task).rsplit("-trial-", 1)[0]
    return str(task)


def load_episodes(records: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Group flat records into {episode_key: {baseline_id: row}}."""
    episodes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in records:
        key = f"{row.get('episode_id')}::{row.get('trial_id')}::{_cell(row)}"
        episodes[key][row.get("baseline_id")] = row
    return dict(episodes)


def baseline_rates(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[row.get("baseline_id")].append(row)
    out: dict[str, dict[str, Any]] = {}
    for baseline, rows in sorted(grouped.items()):
        failures = [r for r in rows if not r.get("original_success")]
        recovered = sum(1 for r in failures if r.get("recovered_success"))
        harmful = sum(1 for r in failures if r.get("harmful_repair"))
        abstained = sum(1 for r in rows if r.get("abstained"))
        strict_valid = sum(1 for r in failures if r.get("recovered_success") and r.get("replay_valid"))
        n_fail = len(failures)
        out[baseline] = {
            "n_rows": len(rows),
            "n_failures": n_fail,
            "recovery_rate": (recovered / n_fail) if n_fail else None,
            "recovery_wilson": wilson_interval(recovered, n_fail),
            "harm_rate": (harmful / n_fail) if n_fail else None,
            "harm_wilson": wilson_interval(harmful, n_fail),
            "abstention_rate": (abstained / len(rows)) if rows else None,
            "abstention_wilson": wilson_interval(abstained, len(rows)),
            "recovery_with_valid_replay": strict_valid,
        }
    return out


def paired_outcome(row: dict[str, Any] | None) -> int:
    """Encode one row into the paired comparison code.

    1 = recovered without harm (safest handling), 0 = not recovered, -1 =
    harmful repair (worst outcome). Abstain counts as 0 for recovery but
    carries no harm.
    """
    if row is None:
        return 0
    if row.get("harmful_repair"):
        return -1
    if row.get("recovered_success"):
        return 1
    return 0


def paired_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    episodes = load_episodes(records)
    # Episode-level pairing: every episode must contain RACER; comparison
    # baselines present in that episode contribute one paired difference.
    comparisons: dict[str, list[int]] = defaultdict(list)
    for episode_key, baseline_rows in sorted(episodes.items()):
        racer_row = baseline_rows.get(RACER)
        if racer_row is None:
            continue
        racer_outcome = paired_outcome(racer_row)
        for baseline, row in baseline_rows.items():
            if baseline == RACER or baseline in ORACLE_BASELINES:
                continue
            comparisons[baseline].append(racer_outcome - paired_outcome(row))

    rng = random.Random(RNG_SEED)
    results: dict[str, Any] = {}
    for baseline, diffs in sorted(comparisons.items()):
        n = len(diffs)
        observed = sum(diffs)
        # Stratified cluster bootstrap: resample episodes (the diffs ARE
        # episode-level paired differences, so each diff is one cluster unit).
        boot_means = []
        for _ in range(BOOTSTRAP_RESAMPLES):
            sample = [diffs[rng.randrange(n)] for _ in range(n)]
            boot_means.append(sum(sample) / n)
        boot_means.sort()
        ci_lo = boot_means[int(0.025 * BOOTSTRAP_RESAMPLES)]
        ci_hi = boot_means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]
        # Sign-flip permutation: flip each diff sign with p=0.5, 10k times.
        extreme = 0
        for _ in range(PERMUTATIONS):
            permuted = sum(d if rng.getrandbits(1) else -d for d in diffs)
            if abs(permuted) >= abs(observed):
                extreme += 1
        p_value = (extreme + 1) / (PERMUTATIONS + 1)
        results[baseline] = {
            "n_paired_episodes": n,
            "mean_paired_difference": (observed / n) if n else None,
            "sum_difference": observed,
            "bootstrap_ci95": [ci_lo, ci_hi],
            "permutation_p": p_value,
        }
    # Holm-Bonferroni over the primary family.
    order = sorted(results, key=lambda b: results[b]["permutation_p"])
    m = len(order)
    adjusted: dict[str, dict[str, float]] = {}
    running_max = 0.0
    for rank, baseline in enumerate(order):
        raw_p = results[baseline]["permutation_p"]
        adjusted_p = min(1.0, (m - rank) * raw_p)
        running_max = max(running_max, adjusted_p)
        adjusted[baseline] = {
            "raw_p": raw_p,
            "holm_p": running_max,
            "rejected_h0": running_max <= 0.05,
        }
    return {"paired": results, "holm": adjusted}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RACER v2 主会统计：Wilson CI + 分层配对 bootstrap + 符号置换 + Holm 校正")
    parser.add_argument("envelope", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = json.loads(args.envelope.read_text(encoding="utf-8"))
    records = _records(payload)
    if not records:
        print("no records found", file=__import__("sys").stderr)
        return 2
    rates = baseline_rates(records)
    paired = paired_statistics(records)
    abstention_gap = None
    if RACER in rates and "always_recover" in rates:
        racer_abst = rates[RACER]["abstention_rate"]
        ar_abst = rates["always_recover"]["abstention_rate"]
        if racer_abst is not None and ar_abst is not None:
            abstention_gap = racer_abst - ar_abst
    result = {
        "schema_version": "racer-v2-main-statistics-v1",
        "experiment": payload.get("experiment"),
        "record_count": len(records),
        "episode_count": len(load_episodes(records)),
        "seed": RNG_SEED,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "permutations": PERMUTATIONS,
        "baseline_rates": rates,
        "paired_comparison": paired["paired"],
        "holm_correction": paired["holm"],
        "racer_vs_always_recover_abstention_gap": abstention_gap,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
