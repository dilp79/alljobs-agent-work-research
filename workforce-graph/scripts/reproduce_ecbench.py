#!/usr/bin/env python3
"""Export allowlisted ECBench outcomes, or recompute paired statistics without model calls.

This replays derived result arithmetic, not environment trajectories or provider execution.
Only Python's standard library is required. No network or credential access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

PIN = "0c48f76f2577779cba786998f73b7992078b932d"
SCHEMA = "alljobs.ecbench-public-results.v1"
FEES = ("setup", "ops", "storage", "shipping", "procurement", "refunds_gross", "vip_fees")
WORLD_FIELDS = {
    "day", "bank_yuan", "wallet_yuan", "escrow_yuan", "units_sold", "units_shipped",
    "units_returned", "orders_cancelled", "expected_returns", "fees_yuan", "revenue_net_yuan",
}
COST_FIELDS = {"calls", "list_price_estimate_usd", "reported_credit_cost_usd",
               "accounted_known_usd", "unknown_reserve_usd"}


def number(value, *, nonnegative=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Finite numeric evidence required")
    if nonnegative and value < 0:
        raise ValueError("Negative count or cost")
    return value


def exact_keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("Unexpected/missing public fields; export refused")


def close(actual, expected):
    if not math.isclose(number(actual), number(expected), rel_tol=1e-9, abs_tol=1e-8):
        raise ValueError("Derived receipts disagree with declared result")


def digest_bytes(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt_costs(rows, mock):
    reserved, settled = {}, {}
    for row in rows:
        event, call = row.get("event"), row.get("call_id")
        if event == "request_reserved":
            if (not isinstance(call, str) or not call or call in reserved
                    or row.get("kind") not in ("actor", "npc")):
                raise ValueError("Duplicate/invalid request receipt")
            number(row.get("reserved_usd"), nonnegative=True)
            if mock and row["reserved_usd"] != 0:
                raise ValueError("Mock cannot report reserved API money")
            reserved[call] = row
        elif event == "response_received":
            if call not in reserved or call in settled or row.get("kind") != reserved[call]["kind"]:
                raise ValueError("Unmatched/duplicate settlement")
            if not mock and row.get("reservation_status") != "verified_usage_settled":
                raise ValueError("Live receipt was not verified/settled")
            estimate = number(row.get("price_estimate_usd"), nonnegative=True)
            credit = row.get("reported_credit_cost_usd")
            if mock:
                if estimate != 0 or credit is not None:
                    raise ValueError("Mock cannot report model expense")
            else:
                number(credit, nonnegative=True)
                close(row.get("accounted_cost_usd"), max(estimate, credit))
                if max(estimate, credit) > reserved[call]["reserved_usd"] + 1e-8:
                    raise ValueError("Verified expense exceeded request bound")
            settled[call] = row
    result = {}
    for role in ("actor", "npc"):
        requests = [r for r in reserved.values() if r["kind"] == role]
        successes = [r for r in settled.values() if r["kind"] == role]
        result[role] = {
            "calls": len(requests),
            "list_price_estimate_usd": sum(r["price_estimate_usd"] for r in successes),
            "reported_credit_cost_usd": None if mock else sum(r["reported_credit_cost_usd"] for r in successes),
            "accounted_known_usd": sum(r.get("accounted_cost_usd", 0) for r in successes),
            "unknown_reserve_usd": sum(r["reserved_usd"] for key, r in reserved.items()
                                       if r["kind"] == role and key not in settled),
        }
    return result


def export_bundle(run_root):
    manifest_path = run_root / "preflight.json"
    manifest = json.loads(manifest_path.read_text())
    cfg = manifest["config"]
    if manifest.get("mode") not in ("mock", "live") or cfg["upstream_commit"] != PIN:
        raise ValueError("Recognized run mode and exact upstream pin required")
    mock = manifest["mode"] == "mock"
    mode = "MOCK_TRANSPORT_REAL_KERNEL" if mock else "MODEL_FUNDED_SIMULATION"
    bundle = {
        "schema": SCHEMA, "evidence_mode": mode,
        "upstream": {"repository": "https://github.com/QwenLM/E-CommerceBench",
                     "commit": PIN, "license": "Apache-2.0"},
        "horizon_days": cfg["horizon_days"], "planned_seeds": cfg["seeds"],
        "model_route": "LOCAL_MOCK" if mock else cfg["model"],
        "manifest_sha256": digest_bytes(manifest_path), "episodes": [],
    }
    for seed in cfg["seeds"]:
        for arm in ("BASE", "LEDGER"):
            directory = run_root / f"{seed}-{arm}"
            result_path, calls_path = directory / "result.json", directory / "calls.jsonl"
            if not result_path.exists():
                # An absent/aborted episode remains absent, never a zero-valued observation.
                if calls_path.exists():
                    receipts = [json.loads(line) for line in calls_path.read_text().splitlines()]
                    bundle["episodes"].append({
                        "seed": seed, "arm": arm, "status": "incomplete",
                        "observed_final_state": None, "api_costs": receipt_costs(receipts, mock),
                        "actual_billed_usd": None, "result_sha256": None,
                        "receipts_sha256": digest_bytes(calls_path),
                    })
                continue
            result = json.loads(result_path.read_text())
            if result.get("seed") != seed or result.get("arm") != arm:
                raise ValueError("Episode identity mismatch")
            world = result["world"]
            close(world["bank_plus_wallet_yuan"], world["bank_yuan"] + world["wallet_yuan"])
            complete = (world["horizon_reached"] is True and world["upstream_done"] is True
                        and world["termination_reason"] == "max_days_reached"
                        and world["day"] == cfg["horizon_days"] and result["failure"] is None)
            bankrupt = (world.get("termination_reason") == "bankruptcy"
                        and world.get("upstream_done") is True
                        and world.get("pipeline_finalized") is True and result["failure"] is None)
            status = "complete" if complete else "bankrupt" if bankrupt else "incomplete"
            receipts = [json.loads(line) for line in calls_path.read_text().splitlines()]
            costs = receipt_costs(receipts, mock)
            for role in ("actor", "npc"):
                close(costs[role]["calls"], result[role + "_calls"])
                close(costs[role]["list_price_estimate_usd"], result["cost_by_role_usd"][role])
                if not mock:
                    close(costs[role]["reported_credit_cost_usd"], result["reported_credit_cost_by_role_usd"][role])
            close(sum(v["unknown_reserve_usd"] for v in costs.values()), result["unknown_reserve_usd"])
            close(sum(v["accounted_known_usd"] + v["unknown_reserve_usd"] for v in costs.values()), result["reserved_usd"])
            state = {
                "day": world["day"], "bank_yuan": world["bank_yuan"],
                "wallet_yuan": world["wallet_yuan"], "escrow_yuan": world["escrow_yuan"],
                "units_sold": world["fulfilment"]["units_sold"],
                "units_shipped": world["returns"]["units_shipped"],
                "units_returned": world["fulfilment"]["units_returned"],
                "orders_cancelled": world["fulfilment"]["orders_cancelled"],
                "expected_returns": world["returns"]["exp_returns_total"],
                "fees_yuan": {key: world["simulated_cost_ledger_yuan"][key] for key in FEES},
                "revenue_net_yuan": world["simulated_cost_ledger_yuan"]["revenue_net"],
            }
            bundle["episodes"].append({
                "seed": seed, "arm": arm, "status": status, "observed_final_state": state,
                "api_costs": costs, "actual_billed_usd": None,
                "result_sha256": digest_bytes(result_path), "receipts_sha256": digest_bytes(calls_path),
            })
    validate_bundle(bundle)
    return bundle


def validate_bundle(bundle):
    exact_keys(bundle, {"schema", "evidence_mode", "upstream", "horizon_days", "planned_seeds",
                        "model_route", "manifest_sha256", "episodes"})
    if bundle["schema"] != SCHEMA or bundle["evidence_mode"] not in (
        "MOCK_TRANSPORT_REAL_KERNEL", "MODEL_FUNDED_SIMULATION"
    ):
        raise ValueError("Unknown public schema/evidence mode")
    if bundle["upstream"] != {"repository": "https://github.com/QwenLM/E-CommerceBench",
                               "commit": PIN, "license": "Apache-2.0"}:
        raise ValueError("Unknown upstream")
    mock = bundle["evidence_mode"] == "MOCK_TRANSPORT_REAL_KERNEL"
    if bundle["model_route"] != ("LOCAL_MOCK" if mock else "openrouter-direct:google/gemini-3.8-flash"):
        raise ValueError("Unsupported route identity")
    seeds = bundle["planned_seeds"]
    if (bundle["horizon_days"] not in (14, 30) or not isinstance(seeds, list) or not seeds
            or len(seeds) != len(set(seeds)) or any(type(s) is not int for s in seeds)):
        raise ValueError("Invalid horizon/seeds")
    hashes = [bundle["manifest_sha256"]]
    seen = set()
    if not isinstance(bundle["episodes"], list):
        raise TypeError("Episode array required")
    for row in bundle["episodes"]:
        exact_keys(row, {"seed", "arm", "status", "observed_final_state", "api_costs",
                         "actual_billed_usd", "result_sha256", "receipts_sha256"})
        key = row["seed"], row["arm"]
        if row["seed"] not in seeds or row["arm"] not in ("BASE", "LEDGER") or key in seen:
            raise ValueError("Unplanned/duplicate episode")
        seen.add(key)
        if row["status"] not in ("complete", "incomplete", "bankrupt") or row["actual_billed_usd"] is not None:
            raise ValueError("Unsupported episode status/billing claim")
        world = row["observed_final_state"]
        validate_state(world, row["status"], bundle["horizon_days"])
        if world is None and row["result_sha256"] is not None:
            raise ValueError("Missing final state must have absent result digest")
        exact_keys(row["api_costs"], ("actor", "npc"))
        for cost in row["api_costs"].values():
            exact_keys(cost, COST_FIELDS)
            for name, value in cost.items():
                if name == "reported_credit_cost_usd" and mock:
                    if value is not None:
                        raise ValueError("Mock credit charge claim")
                else:
                    number(value, nonnegative=True)
            if type(cost["calls"]) is not int:
                raise ValueError("Integer request count required")
            if mock:
                if any(cost[k] != 0 for k in COST_FIELDS - {"calls", "reported_credit_cost_usd"}):
                    raise ValueError("Mock API expense claim")
            else:
                # Sum(max(per-call estimate, charge)) may exceed max(the two totals).
                if cost["accounted_known_usd"] + 1e-8 < max(cost["list_price_estimate_usd"], cost["reported_credit_cost_usd"]):
                    raise ValueError("Under-accounted known costs")
        hashes.append(row["receipts_sha256"])
        if world is not None:
            hashes.append(row["result_sha256"])
    if any(not isinstance(h, str) or len(h) != 64 or set(h) - set("0123456789abcdef") for h in hashes):
        raise ValueError("Invalid source digest")


def validate_state(world, status, horizon):
    if world is None:
        if status != "incomplete":
            raise ValueError("Only incomplete episode may lack a final state")
        return
    if world is not None:
        exact_keys(world, WORLD_FIELDS)
        exact_keys(world["fees_yuan"], FEES)
        for name, value in world.items():
            if name != "fees_yuan":
                number(value, nonnegative=name not in ("bank_yuan", "wallet_yuan", "revenue_net_yuan"))
        for name in ("day", "units_sold", "units_shipped", "units_returned", "orders_cancelled"):
            if type(world[name]) is not int:
                raise ValueError("Integer simulation count required")
        if world["day"] > horizon or (status == "complete" and world["day"] != horizon):
            raise ValueError("Premature completion")
        for value in world["fees_yuan"].values():
            number(value, nonnegative=True)


def bootstrap_interval(differences, draws=20000, seed=7301):
    """Finite-seed exploratory percentile interval, not population or causal identification."""
    if len(differences) < 2:
        return None
    rng = random.Random(seed)
    samples = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(draws))
    def quantile(p):
        position = (len(samples) - 1) * p
        lower = int(position)
        return samples[lower] + (samples[min(lower + 1, len(samples) - 1)] - samples[lower]) * (position - lower)
    return [quantile(0.025), quantile(0.975)]


def recompute(bundle):
    validate_bundle(bundle)
    episodes = {(x["seed"], x["arm"]): x for x in bundle["episodes"]}
    pairs, incomplete = [], []
    for seed in bundle["planned_seeds"]:
        arms = [episodes.get((seed, arm)) for arm in ("BASE", "LEDGER")]
        if any(row is None or row["status"] not in ("complete", "bankrupt") for row in arms):
            incomplete.append({"seed": seed, "BASE": arms[0]["status"] if arms[0] else "missing",
                               "LEDGER": arms[1]["status"] if arms[1] else "missing"})
            continue
        values = [row["observed_final_state"] for row in arms]
        terminal = [w["bank_yuan"] + w["wallet_yuan"] for w in values]
        pairs.append({"seed": seed, "BASE_terminal_bank_wallet_yuan": terminal[0],
                      "BASE_status": arms[0]["status"], "LEDGER_status": arms[1]["status"],
                      "LEDGER_terminal_bank_wallet_yuan": terminal[1],
                      "difference_LEDGER_minus_BASE_yuan": terminal[1] - terminal[0],
                      "secondary_differences_LEDGER_minus_BASE": {
                          name: values[1][name] - values[0][name]
                          for name in WORLD_FIELDS - {"fees_yuan"}},
                      "fee_differences_LEDGER_minus_BASE_yuan": {
                          name: values[1]["fees_yuan"][name] - values[0]["fees_yuan"][name]
                          for name in FEES}})
    differences = [p["difference_LEDGER_minus_BASE_yuan"] for p in pairs]
    mock = bundle["evidence_mode"] == "MOCK_TRANSPORT_REAL_KERNEL"
    eligible = bool(differences) and not incomplete
    totals = {role: {key: None if mock and key == "reported_credit_cost_usd" else sum(
        row["api_costs"][role][key] for row in bundle["episodes"])
        for key in COST_FIELDS} for role in ("actor", "npc")}
    return {
        "schema": "alljobs.ecbench-recomputation.v1", "evidence_mode": bundle["evidence_mode"],
        "horizon_days": bundle["horizon_days"], "planned_pairs": len(bundle["planned_seeds"]),
        "complete_pairs": sum(p["BASE_status"] == p["LEDGER_status"] == "complete" for p in pairs),
        "economic_terminal_pairs": len(pairs), "paired_results": pairs, "incomplete_pairs": incomplete,
        "horizon_complete_episodes_by_arm": {arm: sum(r["arm"] == arm and r["status"] == "complete"
            for r in bundle["episodes"]) for arm in ("BASE", "LEDGER")},
        "bankrupt_episodes_by_arm": {arm: sum(r["arm"] == arm and r["status"] == "bankrupt"
            for r in bundle["episodes"]) for arm in ("BASE", "LEDGER")},
        "paired_mean_difference_yuan": statistics.mean(differences) if eligible and not mock else None,
        "paired_median_difference_yuan": statistics.median(differences) if eligible and not mock else None,
        "mock_arithmetic_mean_difference_yuan": statistics.mean(differences) if eligible and mock else None,
        "exploratory_bootstrap_ci95_yuan": bootstrap_interval(differences) if eligible and not mock else None,
        "bootstrap": {"draws": 20000, "seed": 7301, "resampling_unit": "economic_terminal_seed_pair"},
        "api_costs_by_role": totals,
        "accounted_known_plus_unknown_reserve_usd": sum(
            c["accounted_known_usd"] + c["unknown_reserve_usd"] for c in totals.values()),
        "actual_billed_usd": None,
        "claim_boundary": "MOCK arithmetic only; no model effect evidence" if mock else
            "Finite constructed seed experiment; exploratory interval, no occupational/ROI/365day claim",
        "incomplete_pair_policy": "No imputation; technical truncation suppresses overall primary; verified finalized bankruptcy remains an economic terminal outcome",
        "replay_scope": "Derived final-state and receipt arithmetic only; not environment or provider replay",
        "source_verification": "SHA256 binds exported source bytes; no independent trajectory/model execution verified",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--run", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    calculate = commands.add_parser("recompute")
    calculate.add_argument("--bundle", type=Path, required=True)
    calculate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = export_bundle(args.run) if args.command == "export" else recompute(json.loads(args.bundle.read_text()))
    with args.output.open("x") as file:
        file.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": "OFFLINE_DERIVED_ARITHMETIC", "command": args.command, "output": str(args.output)}))


if __name__ == "__main__":
    main()
