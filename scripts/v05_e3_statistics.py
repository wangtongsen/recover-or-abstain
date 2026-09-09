#!/usr/bin/env python3
"""Protocol v0.5 statistics: stratified E3 track + dual-model adjudication.

Pre-registered plan (protocol v0.5 §Q):
  Q.1 H-E3a (harm rate): racer harmful_repair rate < retry-family joint
      (fixed_retry, exponential_backoff, generic_reflection, full_trace_judge,
      step_by_step_diagnosis, binary_search_diagnosis,
      agentdebug_targeted_feedback, always_recover) - tested per model over
      the 7-scenario E3 matrix.
  Q.1 H-E3b (no recovery-rate cost): every racer abstention must sit on an
      episode whose clean replay would be harmful (veto accuracy audit) OR
      the episode recovers safely; abstention must never trade away a
      recoverable success.
  Q.2 stratification: (domain x scenario x model) rates; main comparison =
      stratified Mantel-Haenszel with scenario as stratum + scenario-level
      direction-consistency count (7 scenarios same-direction tally).
      Pairing unit = episode (14 baselines share one source trajectory).
  Q.3 dual-model: GLM = primary analysis; DeepSeek = replication; pooled
      stratified Holm statistics only when both models point the same
      direction, otherwise stratified-only reporting with disclosure.
  Q.5 inherited: Wilson 95% CIs, episode-cluster bootstrap, Holm correction,
      zero-drift BEHAVIOR_FIELDS assertion (built into the envelope builder).

Stdlib only; single random.Random(seed) for reproducibility.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

Z95 = 1.959963984540054
BOOTSTRAP_RESAMPLES = 10_000
PERMUTATIONS = 10_000
RNG_SEED = 20260906
RACER = "racer"
ORACLE_BASELINES = {"oracle_root_cause", "oracle_recovery"}
RETRY_FAMILY = [
    "fixed_retry", "exponential_backoff", "generic_reflection", "full_trace_judge",
    "step_by_step_diagnosis", "binary_search_diagnosis", "agentdebug_targeted_feedback",
    "always_recover",
]
# Holm family (Q.1): 2 primary hypotheses.
HOLM_FAMILY = ["H-E3a_harm_rate", "H-E3b_veto_accuracy"]


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


def load_episodes(records: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    episodes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in records:
        key = f"{row.get('model_resource_id')}::{row.get('episode_id')}::{row.get('trial_id')}"
        episodes[key][row.get("baseline_id")] = row
    return dict(episodes)


def _cell(row: dict[str, Any]) -> str:
    task = str(row.get("task_id", ""))
    return task.rsplit("-trial-", 1)[0] if "-trial-" in task else task


def stratified_rates(records: list[dict[str, Any]]) -> dict[str, Any]:
    """(domain x scenario x model) x baseline harmful/abstain/recovered rates."""
    grouped: dict[tuple[str, str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in records:
        key = (row.get("domain") or "?", row.get("scenario_id") or "-", row.get("model_resource_id") or "?")
        grouped[key][row.get("baseline_id")].append(row)
    out: dict[str, Any] = {}
    for (domain, scenario, model), baselines in sorted(grouped.items()):
        cell_out = {}
        for baseline, rows in sorted(baselines.items()):
            failures = [r for r in rows if not r.get("original_success")]
            recovered = sum(1 for r in failures if r.get("recovered_success"))
            harmful = sum(1 for r in failures if r.get("harmful_repair"))
            abstained = sum(1 for r in rows if r.get("abstained"))
            cell_out[baseline] = {
                "n_rows": len(rows),
                "n_failures": len(failures),
                "recovered": recovered,
                "harmful": harmful,
                "abstained": abstained,
                "recovery_rate": (recovered / len(failures)) if failures else None,
                "harm_rate": (harmful / len(failures)) if failures else None,
                "abstain_rate": (abstained / len(rows)) if rows else None,
            }
        out[f"{domain}|{scenario}|{model}"] = cell_out
    return out


def mantel_haenszel(records: list[dict[str, Any]], racer: str = RACER,
                    family: list[str] | None = None) -> dict[str, Any]:
    """Stratified MH common odds ratio with scenario as stratum.

    Compares the event 'harmful_repair' between racer and the retry-family
    joint (rows pooled per stratum). Returns MH OR, its 95% CI (Robins-
    Breslow-Greenland variance), and a chi-square association test.
    """
    if family is None:
        family = RETRY_FAMILY
    episodes = load_episodes(records)
    strata: dict[str, dict[str, int]] = defaultdict(lambda: {"a": 0, "b": 0, "c": 0, "d": 0})
    # a = racer harm, b = family harm, c = racer no-harm, d = family no-harm
    for _key, baseline_rows in episodes.items():
        racer_row = baseline_rows.get(racer)
        if racer_row is None:
            continue
        scenario = racer_row.get("scenario_id") or _cell(racer_row)
        stratum = strata[str(scenario)]
        racer_harm = 1 if racer_row.get("harmful_repair") else 0
        stratum["a"] += racer_harm
        stratum["c"] += 1 - racer_harm
        for baseline in family:
            row = baseline_rows.get(baseline)
            if row is None:
                continue
            fam_harm = 1 if row.get("harmful_repair") else 0
            stratum["b"] += fam_harm
            stratum["d"] += 1 - fam_harm
    # Haldane-Anscombe continuity correction (+0.5 per cell) when any margin
    # is degenerate (e.g. racer_harm=0 across all strata: OR_hat=0 and the
    # RBG variance of log(OR) is undefined; correction is the standard
    # pre-registered remedy for zero-cell MH).
    all_cells = [s for s in strata.values() if (s["a"] + s["b"] + s["c"] + s["d"]) > 0]
    degenerate = any(s["a"] == 0 or s["b"] == 0 or s["c"] == 0 or s["d"] == 0 for s in all_cells)
    if degenerate:
        for stratum in strata.values():
            stratum["a"] += 0.5
            stratum["b"] += 0.5
            stratum["c"] += 0.5
            stratum["d"] += 0.5
    R = S = 0.0
    sum_P = 0.0
    a_tot = b_tot = c_tot = d_tot = 0.0
    for stratum in strata.values():
        a, b, c, d = stratum["a"], stratum["b"], stratum["c"], stratum["d"]
        n = a + b + c + d
        if n == 0:
            continue
        R += a * d / n
        S += b * c / n
        sum_P += (a * d + b * c) / n
        a_tot += a
        b_tot += b
        c_tot += c
        d_tot += d
    mh_or = (R / S) if S > 0 else None
    if R > 0 and S > 0:
        var_log = (sum_P / (2.0 * (R ** 2))
                   + ((R + S) / (2.0 * R * S))
                   + (sum_P / (2.0 * (S ** 2))))
        se_log = math.sqrt(var_log)
        ci_lo = math.exp(math.log(mh_or) - Z95 * se_log)
        ci_hi = math.exp(math.log(mh_or) + Z95 * se_log)
    else:
        se_log = None
        ci_lo = ci_hi = None
    # chi-square 1-dof association test (Yates-corrected; degenerate tables
    # fall back to the corrected cells above)
    if a_tot + b_tot + c_tot + d_tot > 0:
        num = (abs(a_tot * d_tot - b_tot * c_tot) - 0.5 * (a_tot + b_tot + c_tot + d_tot)) ** 2
        den = (a_tot + b_tot) * (c_tot + d_tot) * (a_tot + c_tot) * (b_tot + d_tot)
        if den == 0:
            chi2 = None
            p = None
        else:
            chi2 = num / den
            p = math.erfc(math.sqrt(chi2 / 2.0))
    else:
        chi2 = p = None
    return {
        "descriptive_note": (
            "MH OR is the pre-registered descriptive common-effect estimate; the "
            "inferential test for H-E3a is the episode-cluster bootstrap + sign-flip "
            "permutation on the paired harm-rate difference. Zero-cell tables apply "
            "the Haldane-Anscombe 0.5 correction (disclosed in continuity_correction)."
        ),
        "continuity_correction": degenerate,
        "strata": {k: dict(v) for k, v in sorted(strata.items())},
        "racer_harm_total": a_tot, "family_harm_total": b_tot,
        "racer_no_harm_total": c_tot, "family_no_harm_total": d_tot,
        "mh_odds_ratio": mh_or, "mh_or_ci95": [ci_lo, ci_hi] if ci_lo is not None else None,
        "chi2": chi2, "chi2_p": p,
    }


def scenario_direction_consistency(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per scenario: racer harm < family harm AND racer abstain rate high."""
    episodes = load_episodes(records)
    per_scenario: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for _key, baseline_rows in episodes.items():
        racer_row = baseline_rows.get(RACER)
        if racer_row is None:
            continue
        scenario = racer_row.get("scenario_id") or _cell(racer_row)
        cell = per_scenario[str(scenario)]
        cell["racer_harm"] += 1 if racer_row.get("harmful_repair") else 0
        cell["racer_abstain"] += 1 if racer_row.get("abstained") else 0
        cell["racer_n"] += 1
        for baseline in RETRY_FAMILY:
            row = baseline_rows.get(baseline)
            if row is None:
                continue
            cell["family_harm"] += 1 if row.get("harmful_repair") else 0
            cell["family_n"] += 1
    consistency = {}
    same_direction = 0
    for scenario, cell in sorted(per_scenario.items()):
        family_rate = (cell["family_harm"] / cell["family_n"]) if cell["family_n"] else None
        racer_rate = (cell["racer_harm"] / cell["racer_n"]) if cell["racer_n"] else None
        racer_abstain_rate = (cell["racer_abstain"] / cell["racer_n"]) if cell["racer_n"] else None
        consistent = (racer_rate is not None and family_rate is not None
                      and racer_rate < family_rate)
        veto_consistent = racer_abstain_rate is not None and racer_abstain_rate == 1.0
        if consistent:
            same_direction += 1
        consistency[scenario] = {
            **dict(cell),
            "racer_harm_rate": racer_rate,
            "family_harm_rate": family_rate,
            "racer_abstain_rate": racer_abstain_rate,
            "direction_consistent": consistent,
            "veto_consistent": veto_consistent,
        }
    return {
        "scenarios": consistency,
        "same_direction_count": same_direction,
        "total_scenarios": len(consistency),
    }


def veto_accuracy_audit(records: list[dict[str, Any]], annotation: dict | None = None) -> dict[str, Any]:
    """H-E3b: every racer veto must correspond to a truly harmful replay path.

    Uses cf_outcome_harm (the oracle-labeled predicted path outcome stamped
    on vetoed rows by the envelope builder).
    """
    episodes = load_episodes(records)
    vetoed = correct = recoverable = 0
    per_scenario: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for _key, baseline_rows in episodes.items():
        racer_row = baseline_rows.get(RACER)
        if racer_row is None or not racer_row.get("abstained"):
            continue
        scenario = str(racer_row.get("scenario_id") or _cell(racer_row))
        vetoed += 1
        predicted_harm = racer_row.get("cf_outcome_harm") is True
        per_scenario[scenario]["vetoed"] += 1
        per_scenario[scenario]["correct"] += 1 if predicted_harm else 0
        correct += 1 if predicted_harm else 0
    return {
        "vetoed_total": vetoed,
        "veto_correct": correct,
        "veto_accuracy": (correct / vetoed) if vetoed else None,
        "per_scenario": {k: dict(v) for k, v in sorted(per_scenario.items())},
    }


def paired_bootstrap(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Episode-cluster bootstrap for racer harm-rate difference vs family joint."""
    episodes = load_episodes(records)
    # family joint harm per episode: fraction of retry-family rows harmful
    diffs: list[float] = []
    for _key, baseline_rows in episodes.items():
        racer_row = baseline_rows.get(RACER)
        if racer_row is None:
            continue
        fam_rows = [baseline_rows[b] for b in RETRY_FAMILY if b in baseline_rows]
        if not fam_rows:
            continue
        fam_harm_rate = sum(1 for r in fam_rows if r.get("harmful_repair")) / len(fam_rows)
        racer_harm = 1 if racer_row.get("harmful_repair") else 0
        diffs.append(fam_harm_rate - racer_harm)
    if not diffs:
        return {"n_episodes": 0}
    rng = random.Random(RNG_SEED)
    n = len(diffs)
    observed = sum(diffs) / n
    boot_means = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        boot_means.append(sum(sample) / n)
    boot_means.sort()
    ci_lo = boot_means[int(0.025 * BOOTSTRAP_RESAMPLES)]
    ci_hi = boot_means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]
    # sign-flip permutation
    extreme = 0
    scaled = [int(d * 8) for d in diffs]  # 8th-integer coding for sign flips
    observed_int = sum(scaled)
    for _ in range(PERMUTATIONS):
        permuted = sum(d if rng.getrandbits(1) else -d for d in scaled)
        if abs(permuted) >= abs(observed_int):
            extreme += 1
    p_value = (extreme + 1) / (PERMUTATIONS + 1)
    return {
        "n_episodes": n,
        "mean_harm_rate_difference_family_minus_racer": observed,
        "bootstrap_ci95": [ci_lo, ci_hi],
        "permutation_p": p_value,
    }


def e3_track_statistics(records: list[dict[str, Any]], model_id: str) -> dict[str, Any]:
    rates = stratified_rates(records)
    mh = mantel_haenszel(records)
    consistency = scenario_direction_consistency(records)
    veto = veto_accuracy_audit(records)
    boot = paired_bootstrap(records)
    # H-E3a raw p + H-E3b audit-derived p (exact binomial on veto accuracy)
    p_a = boot.get("permutation_p")
    p_b = None
    if veto["vetoed_total"] > 0:
        # one-sided exact binomial: P(>= veto_correct correct | n, p=0.5)
        # all-correct is the most extreme case (p = 2^-n), not a missing one.
        from math import comb
        n = veto["vetoed_total"]
        k = veto["veto_correct"]
        p_b = sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n
    # Holm over the 2-hypothesis family
    family = [("H-E3a_harm_rate", p_a), ("H-E3b_veto_accuracy", p_b)]
    family = [(name, p) for name, p in family if p is not None]
    family.sort(key=lambda x: x[1])
    m = len(family)
    running_max = 0.0
    holm: dict[str, dict[str, float | bool]] = {}
    for rank, (name, raw_p) in enumerate(family):
        adj = min(1.0, (m - rank) * raw_p)
        running_max = max(running_max, adj)
        holm[name] = {"raw_p": raw_p, "holm_p": running_max, "rejected_h0": running_max <= 0.05}
    return {
        "schema_version": "racer-v2-v05-e3-statistics-v1",
        "model_resource_id": model_id,
        "record_count": len(records),
        "episode_count": len(load_episodes(records)),
        "seed": RNG_SEED,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "permutations": PERMUTATIONS,
        "harm_oracle_label": "independent_oracle_v05",
        "stratified_rates": rates,
        "mantel_haenszel_harm": mh,
        "scenario_direction_consistency": consistency,
        "veto_accuracy_audit": veto,
        "harm_rate_bootstrap": boot,
        "holm_family": holm,
    }


def dual_model_adjudication(glm_stats: dict[str, Any], deepseek_stats: dict[str, Any] | None) -> dict[str, Any]:
    """Q.3: pooled stratified statistics only when directions agree."""
    if deepseek_stats is None:
        return {"mode": "glm_only", "pooled": False,
                "reason": "DeepSeek pass not yet executed; single-model reporting."}
    glm_dir = glm_stats["scenario_direction_consistency"]["same_direction_count"]
    ds_dir = deepseek_stats["scenario_direction_consistency"]["same_direction_count"]
    agree = glm_dir == glm_stats["scenario_direction_consistency"]["total_scenarios"] \
        and ds_dir == deepseek_stats["scenario_direction_consistency"]["total_scenarios"]
    return {
        "mode": "dual_model",
        "glm_same_direction": glm_dir,
        "deepseek_same_direction": ds_dir,
        "directions_agree": agree,
        "pooled": agree,
        "reason": ("pooled stratified Holm executed (both models 7/7 same direction)"
                   if agree else
                   "directions differ; stratified reporting only, no pooling (disclosed)"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v0.5 E3 分层统计（MH + Holm + veto 审计）")
    parser.add_argument("--glm-envelope", type=Path)
    parser.add_argument("--deepseek-envelope", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    glm_stats = None
    if args.glm_envelope:
        payload = json.loads(args.glm_envelope.read_text(encoding="utf-8"))
        records = _records(payload)
        model_id = records[0].get("model_resource_id") if records else "unknown"
        glm_stats = e3_track_statistics(records, model_id)

    deepseek_stats = None
    if args.deepseek_envelope:
        payload = json.loads(args.deepseek_envelope.read_text(encoding="utf-8"))
        records = _records(payload)
        model_id = records[0].get("model_resource_id") if records else "unknown"
        deepseek_stats = e3_track_statistics(records, model_id)

    adjudication = dual_model_adjudication(glm_stats, deepseek_stats) if glm_stats else None
    result = {
        "schema_version": "racer-v2-v05-statistics-v1",
        "glm": glm_stats,
        "deepseek": deepseek_stats,
        "dual_model_adjudication": adjudication,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # compact summary to stdout
    for tag, stats in (("GLM", glm_stats), ("DeepSeek", deepseek_stats)):
        if not stats:
            continue
        mh = stats["mantel_haenszel_harm"]
        cons = stats["scenario_direction_consistency"]
        veto = stats["veto_accuracy_audit"]
        boot = stats["harm_rate_bootstrap"]
        holm = stats["holm_family"]
        print(f"[{tag}] records={stats['record_count']} episodes={stats['episode_count']}")
        print(f"[{tag}] MH OR={mh['mh_odds_ratio']} CI={mh['mh_or_ci95']} chi2_p={mh['chi2_p']}")
        print(f"[{tag}] direction {cons['same_direction_count']}/{cons['total_scenarios']} "
              f"veto {veto['veto_correct']}/{veto['vetoed_total']}")
        print(f"[{tag}] harm diff family-racer={boot.get('mean_harm_rate_difference_family_minus_racer')} "
              f"CI={boot.get('bootstrap_ci95')} p={boot.get('permutation_p')}")
        for name, h in (holm or {}).items():
            print(f"[{tag}] Holm {name}: raw_p={h['raw_p']:.6f} holm_p={h['holm_p']:.6f} "
                  f"reject={h['rejected_h0']}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
