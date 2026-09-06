# Original pure functions extracted from the hash-bound run source snapshot.
import json
import math
import random
from decimal import Decimal
FAMILIES = ('reconciliation', 'record_preparation', 'formal_rules')

def strict_json(value):
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=unique)

def summarize(results, expected_cases):
    by_base = {}
    for r in results:
        by_base.setdefault(r["base_id"], {})[(r["defective"], r["tools_available"])] = r
    per_family = {f: [] for f in FAMILIES}
    for cells in by_base.values():
        if len(cells) != 4 or any(r["metrics"]["exact_correct"] is None for r in cells.values()):
            continue
        diffs = [
            int(cells[d, True]["metrics"]["exact_correct"])
            - int(cells[d, False]["metrics"]["exact_correct"])
            for d in (False, True)
        ]
        per_family[next(iter(cells.values()))["family"]].append(
            [(diffs[0] + diffs[1]) / 2, diffs[0], diffs[1], diffs[1] - diffs[0]]
        )
    mean = lambda x: sum(x) / len(x) if x else None
    complete = [x for family in per_family.values() for x in family]

    def contrast(index):
        return (
            mean([mean([x[index] for x in values]) for values in per_family.values()])
            if all(per_family.values())
            else None
        )

    intervals = [None] * 4
    if all(len(x) >= 2 for x in per_family.values()):
        rng = random.Random(20260906)
        bootstrap = [[] for _ in range(4)]
        for _ in range(4000):
            sampled = [rng.choices(v, k=len(v)) for v in per_family.values()]
            for index in range(4):
                bootstrap[index].append(mean([mean([x[index] for x in v]) for v in sampled]))
        intervals = [[sorted(v)[100], sorted(v)[3899]] for v in bootstrap]
    ceiling = (
        1.96 * math.sqrt(sum(1 / (9 * len(v)) for v in per_family.values()))
        if all(per_family.values())
        else None
    )
    latencies = sorted(r.get("latency_ms", 0) for r in results)
    cells_summary = {}
    for f in FAMILIES:
        for d in (False, True):
            for t in (False, True):
                rows = [
                    r
                    for r in results
                    if (r["family"], r["defective"], r["tools_available"]) == (f, d, t)
                ]
                cells_summary[f"{f}:d{int(d)}:t{int(t)}"] = {
                    "expected": expected_cases // 12,
                    "observed": len(rows),
                    "graded": sum(r["metrics"]["exact_correct"] is not None for r in rows),
                    "correct": sum(r["metrics"]["exact_correct"] is True for r in rows),
                    "infrastructure": sum(r["outcome"] == "infrastructure_error" for r in rows),
                }
    # Sharp missing-cell bounds on the equally weighted full planned finite suite.
    planned_per_family = expected_cases // 12
    bounds = {f: [0.0, 0.0] for f in FAMILIES}
    for f in FAMILIES:
        groups = [v for v in by_base.values() if next(iter(v.values()))["family"] == f]
        bounds[f] = [-(planned_per_family - len(groups)), planned_per_family - len(groups)]
        for group in groups:
            for d in (False, True):
                for t in (False, True):
                    r = group.get((d, t))
                    y = r["metrics"]["exact_correct"] if r else None
                    coefficient = 0.5 if t else -0.5
                    if y is None:
                        bounds[f][0] += min(0, coefficient)
                        bounds[f][1] += max(0, coefficient)
                    else:
                        bounds[f][0] += coefficient * int(y)
                        bounds[f][1] += coefficient * int(y)
    full_bounds = (
        [sum(v[i] / planned_per_family for v in bounds.values()) / 3 for i in (0, 1)]
        if planned_per_family
        else None
    )
    return {
        "claim_ceiling": "FINITE_CONSTRUCTED_SUITE",
        "n_expected_trials": expected_cases,
        "n_observed_trials": len(results),
        "n_complete_paired_bases": len(complete),
        "n_expected_bases": expected_cases // 4,
        "n_started_bases": len(by_base),
        "n_unpaired_or_ungraded_bases": expected_cases // 4 - len(complete),
        "primary_equal_family_paired_difference": contrast(0),
        "stratified_base_bootstrap_95": intervals[0],
        "worst_case_normal_half_width": ceiling,
        "bootstrap_warning": "Small or uniform suites yield unstable or degenerate bootstrap intervals; not evidence of population certainty.",
        "defect_stratified_difference": {"False": contrast(1), "True": contrast(2)},
        "interaction_difference_in_differences": contrast(3),
        "secondary_stratified_base_bootstrap_95": {
            "clean": intervals[1],
            "defective": intervals[2],
            "interaction": intervals[3],
        },
        "complete_paired_bases_by_family": {f: len(v) for f, v in per_family.items()},
        "cell_denominators": cells_summary,
        "full_planned_suite_primary_missing_cell_bounds": full_bounds,
        "estimand_population": "Complete-case finite-template contrast; missing bases can select the retained population.",
        "correct_corrections": sum(
            r.get("answer", {}).get("decision") == "corrected"
            and r["metrics"]["exact_correct"] is True
            for r in results
            if isinstance(r.get("answer"), dict)
        ),
        "malformed_outputs": sum(r.get("failure_code") == "MALFORMED_OUTPUT_JSON" for r in results),
        "latency_ms": {
            "n": len(latencies),
            "total": sum(latencies),
            "mean": mean(latencies),
            "maximum": max(latencies) if latencies else None,
        },
        "accounted_list_price_usd": str(
            sum((Decimal(r["accounted_cost_usd"]) for r in results), Decimal(0))
        ),
        "broker_reported_usage_cost_usd": str(
            sum(
                (
                    Decimal(str(q["response"].get("usage", {}).get("cost", 0)))
                    for r in results
                    for q in r.get("receipts", [])
                    if "response" in q
                ),
                Decimal(0),
            )
        ),
        "broker_reported_cost_basis": "OpenRouter response usage.cost where present; not an invoice and not substituted for conservative budget accounting",
        "actual_invoice_cost_verified": False,
        "cost_basis": "upstream_usage_times_official_standard_rates_plus_unknown_request_reservations",
        "outcomes": {
            label: sum(r["outcome"] == label for r in results)
            for label in ["pass", "fail", "incomplete", "infrastructure_error"]
        },
        "metrics_totals": {
            key: sum(r["metrics"].get(key) is True for r in results)
            for key in [
                "exact_correct",
                "completed",
                "correct_escalation",
                "correct_rejection",
                "defect_detected",
                "missed_defect",
                "unsafe_false_completion",
                "false_escalation",
            ]
        },
        "input_tokens": sum(r["input_tokens"] for r in results),
        "output_tokens_including_thinking": sum(r["output_tokens"] for r in results),
        "requests": sum(r["requests"] for r in results),
        "agent_turns": sum(r.get("agent_turns", r["requests"]) for r in results),
        "unknown_usage_attempts": sum(
            r.get(
                "unknown_usage_attempts",
                sum("unknown_billing_reserved_usd" in q for q in r.get("receipts", [])),
            )
            for r in results
        ),
        "tool_calls": sum(len(r["tool_calls"]) for r in results),
        "tool_errors": sum(bool(c["error"]) for r in results for c in r["tool_calls"]),
    }
