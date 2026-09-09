#!/usr/bin/env python3
"""Protocol v0.5 main-track (E1/E2) statistics: 3-domain stratified.

Q.4: E1/E2 main table reports recovery/harm rates stratified by domain;
between-domain differences are descriptive only (3 domains are insufficient
for domain-level significance claims). All inherited v0.1 conventions
(Wilson 95% CIs, episode-cluster paired bootstrap + sign-flip permutation,
Holm correction over the non-oracle primary family) are reused verbatim
from scripts/main_statistics.py.

Usage:
  python scripts/v05_main_statistics.py <envelope.json> --output <stats.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from main_statistics import (  # noqa: E402
    RACER, ORACLE_BASELINES, load_episodes, baseline_rates,
    paired_outcome, wilson_interval, BOOTSTRAP_RESAMPLES, PERMUTATIONS, RNG_SEED,
)


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        records = payload.get("records")
        if isinstance(records, list):
            return [row for row in records if isinstance(row, dict)]
    return []


def _domain(row: dict[str, Any]) -> str:
    domain = row.get("domain")
    if isinstance(domain, str) and domain:
        return domain
    task_id = str(row.get("task_id", ""))
    if task_id.startswith("v05-main-"):
        return task_id.split("-")[2]
    return "?"


def domain_stratified_rates(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per (domain x baseline) recovery/harm/abstain with Wilson CIs (Q.4)."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in records:
        grouped[_domain(row)][row.get("baseline_id")].append(row)
    out: dict[str, Any] = {}
    for domain, baselines in sorted(grouped.items()):
        domain_out = {}
        for baseline, rows in sorted(baselines.items()):
            failures = [r for r in rows if not r.get("original_success")]
            recovered = sum(1 for r in failures if r.get("recovered_success"))
            harmful = sum(1 for r in failures if r.get("harmful_repair"))
            abstained = sum(1 for r in rows if r.get("abstained"))
            domain_out[baseline] = {
                "n_rows": len(rows),
                "n_failures": len(failures),
                "recovered": recovered,
                "harmful": harmful,
                "abstained": abstained,
                "recovery_rate": (recovered / len(failures)) if failures else None,
                "recovery_wilson": wilson_interval(recovered, len(failures)),
                "harm_rate": (harmful / len(failures)) if failures else None,
                "harm_wilson": wilson_interval(harmful, len(failures)),
                "abstain_rate": (abstained / len(rows)) if rows else None,
            }
        out[domain] = domain_out
    return out


def domain_paired_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Inherited v0.1 paired comparison, computed per domain stratum."""
    import random
    results: dict[str, Any] = {}
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_domain[_domain(row)].append(row)
    for domain, rows in sorted(by_domain.items()):
        episodes = load_episodes(rows)
        comparisons: dict[str, list[int]] = defaultdict(list)
        for _key, baseline_rows in sorted(episodes.items()):
            racer_row = baseline_rows.get(RACER)
            if racer_row is None:
                continue
            racer_outcome = paired_outcome(racer_row)
            for baseline, row in baseline_rows.items():
                if baseline == RACER or baseline in ORACLE_BASELINES:
                    continue
                comparisons[baseline].append(racer_outcome - paired_outcome(row))
        rng = random.Random(RNG_SEED + hash(domain) % 10000)
        domain_results = {}
        for baseline, diffs in sorted(comparisons.items()):
            n = len(diffs)
            observed = sum(diffs)
            boot_means = []
            for _ in range(BOOTSTRAP_RESAMPLES):
                sample = [diffs[rng.randrange(n)] for _ in range(n)]
                boot_means.append(sum(sample) / n)
            boot_means.sort()
            ci_lo = boot_means[int(0.025 * BOOTSTRAP_RESAMPLES)]
            ci_hi = boot_means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]
            extreme = 0
            for _ in range(PERMUTATIONS):
                permuted = sum(d if rng.getrandbits(1) else -d for d in diffs)
                if abs(permuted) >= abs(observed):
                    extreme += 1
            domain_results[baseline] = {
                "n_paired_episodes": n,
                "mean_paired_difference": (observed / n) if n else None,
                "bootstrap_ci95": [ci_lo, ci_hi],
                "permutation_p": (extreme + 1) / (PERMUTATIONS + 1),
            }
        # Holm within-domain family
        order = sorted(domain_results, key=lambda b: domain_results[b]["permutation_p"])
        m = len(order)
        adjusted = {}
        running_max = 0.0
        for rank, baseline in enumerate(order):
            raw_p = domain_results[baseline]["permutation_p"]
            adj = min(1.0, (m - rank) * raw_p)
            running_max = max(running_max, adj)
            adjusted[baseline] = {"raw_p": raw_p, "holm_p": running_max, "rejected_h0": running_max <= 0.05}
        results[domain] = {"paired": domain_results, "holm": adjusted, "episodes": len(episodes)}
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v0.5 主表 3 域分层统计（Q.4）")
    parser.add_argument("envelope", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = json.loads(args.envelope.read_text(encoding="utf-8"))
    records = _records(payload)
    if not records:
        print("no records found", file=sys.stderr)
        return 2
    overall = baseline_rates(records)
    domain_rates = domain_stratified_rates(records)
    domain_paired = domain_paired_statistics(records)
    result = {
        "schema_version": "racer-v2-v05-main-statistics-v1",
        "experiment": payload.get("experiment"),
        "record_count": len(records),
        "episode_count": len(load_episodes(records)),
        "harm_oracle_label": "independent_oracle_v05",
        "model_resource_id": records[0].get("model_resource_id"),
        "overall_baseline_rates": overall,
        "domain_stratified_rates": domain_rates,
        "domain_paired_statistics": domain_paired,
        "q4_disclosure": "between-domain differences are descriptive only; no domain-level significance claims (3 domains)",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # stdout summary
    print(f"records={result['record_count']} episodes={result['episode_count']} model={result['model_resource_id']}")
    for domain, rates in domain_rates.items():
        racer = rates.get(RACER, {})
        n = racer.get("n_rows")
        rec = racer.get("recovery_rate")
        harm = racer.get("harm_rate")
        print(f"  {domain}: racer n={n} recovery={rec} harm={harm}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
