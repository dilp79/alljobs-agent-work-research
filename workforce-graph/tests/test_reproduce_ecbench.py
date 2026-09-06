"""Offline public arithmetic controls; retained fixture uses MOCK transport, not model evidence."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ec_public", ROOT / "scripts/reproduce_ecbench.py")
public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public)


def fixture():
    return json.loads((ROOT / "tests/fixtures/ecbench/mock-real-kernel-30d.json").read_text())


def test_retained_real_kernel_mock_recomputes_eight_pairs_without_effect_claim():
    result = public.recompute(fixture())
    assert result["complete_pairs"] == result["planned_pairs"] == 8
    assert result["paired_results"][0]["BASE_terminal_bank_wallet_yuan"] == 99528.852
    assert result["paired_mean_difference_yuan"] is None
    assert result["paired_median_difference_yuan"] is None
    assert result["mock_arithmetic_mean_difference_yuan"] == 0
    assert result["exploratory_bootstrap_ci95_yuan"] is None
    assert result["api_costs_by_role"]["actor"]["calls"] == 512
    assert result["api_costs_by_role"]["npc"]["calls"] == 16
    assert result["accounted_known_plus_unknown_reserve_usd"] == 0
    assert "MOCK" in result["claim_boundary"]


@pytest.mark.parametrize("mutation", ["missing", "incomplete"])
def test_missing_pairs_cannot_create_primary_effect(mutation):
    bundle = fixture()
    if mutation == "missing":
        bundle["episodes"].pop()
    else:
        bundle["episodes"][-1]["status"] = mutation
    result = public.recompute(bundle)
    assert result["complete_pairs"] == 7
    assert len(result["incomplete_pairs"]) == 1
    assert result["paired_mean_difference_yuan"] is None
    assert result["exploratory_bootstrap_ci95_yuan"] is None


def test_verified_bankruptcy_is_terminal_economic_outcome_not_missingness():
    # Synthetic arithmetic control, not an actual provider-funded observation.
    bundle = fixture()
    bundle["evidence_mode"] = "MODEL_FUNDED_SIMULATION"
    bundle["model_route"] = "openrouter-direct:google/gemini-3.8-flash"
    for row in bundle["episodes"]:
        for cost in row["api_costs"].values():
            cost["reported_credit_cost_usd"] = 0
    row = bundle["episodes"][-1]
    row["status"] = "bankrupt"
    row["observed_final_state"].update(day=1, bank_yuan=-1000, wallet_yuan=0)
    result = public.recompute(bundle)
    assert result["complete_pairs"] == 7
    assert result["economic_terminal_pairs"] == 8
    assert result["bankrupt_episodes_by_arm"] == {"BASE": 0, "LEDGER": 1}
    assert result["horizon_complete_episodes_by_arm"] == {"BASE": 8, "LEDGER": 7}
    assert result["paired_mean_difference_yuan"] < 0
    assert result["incomplete_pairs"] == []


@pytest.mark.parametrize("finalized,done,failure,expected", [
    (True, True, None, "bankrupt"), (False, True, None, "incomplete"),
    (True, False, None, "incomplete"), (True, True, "BudgetStop", "incomplete"),
])
def test_export_bankruptcy_requires_verified_kernel_finalization(tmp_path, finalized, done, failure, expected):
    config = {"upstream_commit": public.PIN, "horizon_days": 14, "seeds": [1]}
    (tmp_path / "preflight.json").write_text(json.dumps({"mode": "mock", "config": config}))
    directory = tmp_path / "1-BASE"
    directory.mkdir()
    world = {"bank_yuan": -1, "wallet_yuan": 0, "bank_plus_wallet_yuan": -1,
        "escrow_yuan": 0, "day": 2, "horizon_reached": False, "upstream_done": done,
        "pipeline_finalized": finalized, "termination_reason": "bankruptcy",
        "fulfilment": {"units_sold": 0, "units_returned": 0, "orders_cancelled": 0},
        "returns": {"units_shipped": 0, "exp_returns_total": 0},
        "simulated_cost_ledger_yuan": dict.fromkeys((*public.FEES, "revenue_net"), 0)}
    result = {"seed": 1, "arm": "BASE", "world": world, "failure": failure,
        "actor_calls": 0, "npc_calls": 0, "cost_by_role_usd": {"actor": 0, "npc": 0},
        "unknown_reserve_usd": 0, "reserved_usd": 0}
    (directory / "result.json").write_text(json.dumps(result))
    (directory / "calls.jsonl").write_text("")
    assert public.export_bundle(tmp_path)["episodes"][0]["status"] == expected


def test_duplicate_and_private_fields_are_rejected():
    bundle = fixture()
    bundle["episodes"].append(copy.deepcopy(bundle["episodes"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        public.recompute(bundle)
    for target in (lambda b: b, lambda b: b["episodes"][0],
                   lambda b: b["episodes"][0]["observed_final_state"],
                   lambda b: b["episodes"][0]["api_costs"]["actor"]):
        bundle = fixture()
        target(bundle)["reasoning_details"] = "PRIVATE_SENTINEL"
        with pytest.raises(ValueError, match="public fields"):
            public.recompute(bundle)


def test_live_receipt_known_cost_and_unknown_reservation_are_both_retained():
    rows = [
        {"event": "request_reserved", "call_id": "a", "kind": "actor", "reserved_usd": .1},
        {"event": "response_received", "call_id": "a", "kind": "actor",
         "reservation_status": "verified_usage_settled", "price_estimate_usd": .01,
         "reported_credit_cost_usd": .012, "accounted_cost_usd": .012},
        {"event": "request_reserved", "call_id": "n", "kind": "npc", "reserved_usd": .08},
        {"event": "request_failed", "call_id": "n", "kind": "npc"},
    ]
    costs = public.receipt_costs(rows, False)
    assert costs["actor"]["accounted_known_usd"] == .012
    assert costs["actor"]["unknown_reserve_usd"] == 0
    assert costs["npc"]["unknown_reserve_usd"] == .08
    rows[1]["accounted_cost_usd"] = .001
    with pytest.raises(ValueError, match="disagree"):
        public.receipt_costs(rows, False)


def test_aborted_episode_without_result_still_exports_unknown_money(tmp_path):
    cfg = {"upstream_commit": public.PIN, "horizon_days": 14, "seeds": [1],
           "model": "openrouter-direct:google/gemini-3.8-flash"}
    (tmp_path / "preflight.json").write_text(json.dumps({"mode": "live", "config": cfg}))
    episode = tmp_path / "1-BASE"
    episode.mkdir()
    (episode / "calls.jsonl").write_text(json.dumps({"event": "request_reserved",
        "call_id": "a", "kind": "actor", "reserved_usd": .2,
        "request": {"private_history": "PRIVATE_SENTINEL"}}) + "\n")
    bundle = public.export_bundle(tmp_path)
    assert "PRIVATE_SENTINEL" not in json.dumps(bundle)
    result = public.recompute(bundle)
    assert result["complete_pairs"] == 0
    assert result["accounted_known_plus_unknown_reserve_usd"] == .2
    assert result["paired_mean_difference_yuan"] is None
    assert result["actual_billed_usd"] is None


def test_interval_is_reproducible_at_seed_pair_level():
    assert public.bootstrap_interval([4] * 8) == [4, 4]
    a = public.bootstrap_interval([-4, -2, 0, 1, 2, 4, 6, 8], draws=1000)
    assert a == public.bootstrap_interval([-4, -2, 0, 1, 2, 4, 6, 8], draws=1000)
    assert a[0] < a[1]
    assert public.bootstrap_interval([1]) is None


@pytest.mark.parametrize("name", ["pilot_64k", "pilot_512k", "retention_14d", "final_30d"])
def test_distributed_live_bundle_reproduces_shipped_arithmetic_bytes(name, monkeypatch):
    import socket
    import urllib.request

    def deny_network(*args, **kwargs):
        raise AssertionError("Public arithmetic replay must stay offline")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(urllib.request, "urlopen", deny_network)
    directory = ROOT / "data/ecbench_public_2026_09_06"
    bundle = json.loads((directory / f"{name}_bundle.json").read_text())
    assert bundle["evidence_mode"] == "MODEL_FUNDED_SIMULATION"
    result = public.recompute(bundle)
    encoded = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    assert encoded == (directory / f"{name}_recomputed.json").read_bytes()
