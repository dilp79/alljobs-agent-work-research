"""Portable analytical controls; all observations here are explicitly fixture evidence."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "td_public", ROOT / "scripts/reproduce_tool_defect.py"
)
public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public)


def test_distributed_main_package_regrades_and_matches_all_mandatory_outputs(tmp_path, monkeypatch):
    import socket
    import urllib.request

    def no_network(*args, **kwargs):
        raise AssertionError("distributed main replay must remain offline")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    package = ROOT / "data/tool_defect_public_2026_09_06"
    inputs = json.loads((package / "replay_inputs.json").read_text())
    assert inputs["evidence_mode"] == "live"
    assert inputs["suite"]["partition"] == "main"
    output = tmp_path / "main-replayed"
    result = public.replay(package, output)
    assert result["summary"]["n_expected_trials"] == len(inputs["suite"]["cases"])
    for name in ("results.json", "trials.csv", "cells.csv"):
        assert (output / name).read_bytes() == (package / "reproduced" / name).read_bytes(), name


def sources():
    # Canonical development uses unchanged core; the public release uses its frozen snapshots.
    core = ROOT / "src/workforce_graph/evidence/tool_defect"
    if (core / "analysis.py").is_file():
        snapshot = {
            name: (core / name).read_bytes()
            for name in ("cases.py", "tools.py", "analysis.py", "runner.py")
        }
    else:
        core = ROOT / "data/tool_defect_public_2026_09_06/source"
        snapshot = {
            "cases.py": (core / "cases.py").read_bytes(),
            "tools.py": (core / "tools.py").read_bytes(),
            "analysis.py": (core / "analysis_core.py").read_bytes(),
            "runner.py": (core / "analysis_core.py").read_bytes(),
        }
    return public.calculation_sources(snapshot)[0]


def fixture():
    code = sources()
    cases, _ = public.load_calculators(code)
    suite = cases.build_suite("pilot", bases_per_family=2)
    package = {
        "schema_version": public.SCHEMA,
        "claim_ceiling": public.CEILING,
        "evidence_mode": "fixture",
        "suite": suite,
        "design": {
            "route": {
                "request_model": "fixture:model",
                "response_model": "fixture-model",
                "routed_via": "fixture",
                "provider": "fixture",
                "reasoning": {"effort": "low"},
                "input_usd_per_million": "1",
                "output_usd_per_million": "2",
                "price_source": "fixture rates",
            },
            "limits": {},
            "budget_usd": "1",
            "request_interval_seconds": 0,
            "max_transient_retries": 0,
        },
        "trials": [],
    }
    for case in suite["cases"]:
        text = json.dumps(case["expected"])
        package["trials"].append(
            {
                "case_id": case["case_id"],
                "kind": "final_answer",
                "final_answer_text": text,
                "final_answer_sha256": public.sha(text.encode()),
                "failure_code": None,
                "attempts": [
                    {
                        "turn": 0,
                        "attempt": 0,
                        "response_received": True,
                        "validated_usage": True,
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "accounted_cost_usd": "0.00014",
                        "unknown_billing_reserved_usd": None,
                        "broker_cost_usd": "0.0001",
                        "http_status": None,
                        "retry_scheduled": False,
                        "retry_wait_seconds": None,
                        "request_payload_sha256": "a" * 64,
                        "response_sha256": "b" * 64,
                        "input_reserve": 1000,
                        "output_allowance": 100,
                        "cost_reserve_usd": "0.0012",
                        "returned_model": "fixture-model",
                        "returned_provider": "fixture",
                    }
                ],
                "tool_calls": [],
                "latency_ms": 10,
                "recorded": {
                    "answer": case["expected"],
                    "metrics": cases.grade(case, case["expected"]),
                    "outcome": "pass",
                    "accounted_cost_usd": "0.00014",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "requests": 1,
                    "agent_turns": 1,
                    "unknown_usage_attempts": 0,
                    "usage_tokens_complete": True,
                },
                "private_result_sha256": "c" * 64,
            }
        )
    return package, code


def write_package(path, package, code):
    receipts = {
        "members": {
            "replay_inputs.json": public.sha(public.canonical(package)),
            **{name: public.sha(raw) for name, raw in code.items()},
        }
    }
    public.write_files(
        path,
        {
            "replay_inputs.json": public.canonical(package),
            "source_receipts.json": public.canonical(receipts),
            **code,
        },
    )


def test_actual_pure_formulas_replay_fixture_and_cost_arithmetic(tmp_path):
    package, code = fixture()
    write_package(tmp_path / "package", package, code)
    result = public.replay(tmp_path / "package", tmp_path / "out")
    s = result["summary"]
    assert result["evidence_mode"] == "fixture"
    assert s["n_expected_trials"] == s["n_observed_trials"] == 24
    assert s["n_complete_paired_bases"] == 6
    assert s["primary_equal_family_paired_difference"] == 0
    assert s["stratified_base_bootstrap_95"] == [0, 0]
    assert s["full_planned_suite_primary_missing_cell_bounds"] == [0, 0]
    assert s["accounted_list_price_usd"] == "0.00336"
    assert s["broker_reported_usage_cost_usd"] == "0.0024"
    assert s["input_tokens"] == 2400


@pytest.mark.parametrize("nested", [False, True])
def test_exact_duplicate_answer_bytes_replay_as_malformed(nested):
    package, code = fixture()
    case = package["suite"]["cases"][0]
    row = package["trials"][0]
    text = (
        '{"decision":"complete","issues":[],"records":[{"id":"R01","id":"R02"}]}'
        if nested
        else '{"decision":"WRONG",' + row["final_answer_text"][1:]
    )
    row.update(
        final_answer_text=text,
        final_answer_sha256=public.sha(text.encode()),
        failure_code="MALFORMED_OUTPUT_JSON",
    )
    cases, _ = public.load_calculators(code)
    row["recorded"].update(answer=None, metrics=cases.grade(case, None), outcome="fail")
    s, rows = public.calculate(package, code)
    assert rows[0]["exact_correct"] is False
    assert s["malformed_outputs"] == 1
    assert s["outcomes"]["fail"] == 1


def test_infrastructure_and_unstarted_remain_visible_and_ungraded():
    package, code = fixture()
    cases, _ = public.load_calculators(code)
    case = package["suite"]["cases"][0]
    row = package["trials"][0]
    row.update(
        kind="infrastructure_error",
        final_answer_text=None,
        final_answer_sha256=None,
        failure_code="OPENROUTER_HTTP_503",
    )
    row["attempts"][0].update(
        response_received=False,
        validated_usage=False,
        input_tokens=None,
        output_tokens=None,
        accounted_cost_usd="0",
        unknown_billing_reserved_usd="0.0012",
        broker_cost_usd=None,
        response_sha256=None,
        http_status=503,
    )
    row["recorded"].update(
        answer=None,
        metrics={k: None for k in cases.grade(case, None)},
        outcome="infrastructure_error",
        accounted_cost_usd="0.0012",
        input_tokens=0,
        output_tokens=0,
        unknown_usage_attempts=1,
        usage_tokens_complete=False,
    )
    package["trials"][1] = {"case_id": package["trials"][1]["case_id"], "kind": "not_started"}
    s, rows = public.calculate(package, code)
    assert s["n_expected_trials"] == 24 and s["n_observed_trials"] == 23
    assert s["outcomes"]["infrastructure_error"] == 1
    assert s["outcomes"]["fail"] == 0
    assert s["unknown_usage_attempts"] == 1
    assert rows[0]["exact_correct"] is rows[1]["exact_correct"] is None
    assert (
        s["full_planned_suite_primary_missing_cell_bounds"][0]
        < s["full_planned_suite_primary_missing_cell_bounds"][1]
    )


@pytest.mark.parametrize("mutation", ["duplicate", "cost", "recorded", "unexpected"])
def test_corrupted_projection_refuses(mutation):
    package, code = fixture()
    if mutation == "duplicate":
        package["trials"][1] = copy.deepcopy(package["trials"][0])
    elif mutation == "cost":
        package["trials"][0]["attempts"][0]["accounted_cost_usd"] = "0.00001"
    elif mutation == "recorded":
        package["trials"][0]["recorded"]["metrics"]["exact_correct"] = False
    else:
        package["trials"][0]["reasoning_details"] = []
    with pytest.raises(ValueError):
        public.calculate(package, code)


def test_member_tamper_and_existing_output_preserve_files(tmp_path):
    package, code = fixture()
    write_package(tmp_path / "package", package, code)
    source = tmp_path / "package/source/cases.py"
    source.write_bytes(source.read_bytes() + b"\n# changed\n")
    with pytest.raises(ValueError, match="checksum"):
        public.replay(tmp_path / "package", tmp_path / "out")
    assert not (tmp_path / "out").exists()
    output = tmp_path / "existing"
    output.mkdir()
    (output / "owned").write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        public.replay(tmp_path / "missing-package", output)
    assert (output / "owned").read_bytes() == b"preserve"


def test_private_paths_are_refused_without_redacting_output(tmp_path):
    marker = b"/ho" + b"me/private/file"
    with pytest.raises(ValueError, match="private path"):
        public.write_files(tmp_path / "out", {"answer.json": marker})
    assert not (tmp_path / "out").exists()


def test_private_snapshot_drift_refuses_before_public_export(tmp_path):
    snapshot = tmp_path / "source_snapshot"
    snapshot.mkdir()
    (snapshot / "cases.py").write_bytes(b"changed fixture source")
    config = {
        "implementation_sha256": {"src/cases.py": public.sha(b"frozen fixture source")},
        "driver_sha256": public.sha(b"driver"),
    }
    with pytest.raises(ValueError, match="snapshot hash"):
        public.frozen_snapshot(tmp_path, config)


def test_started_case_without_durable_result_is_not_called_unstarted(tmp_path):
    package, code = fixture()
    run = tmp_path / "private"
    snapshot = run / "source_snapshot"
    snapshot.mkdir(parents=True)
    files = {
        "cases.py": code["source/cases.py"],
        "tools.py": code["source/tools.py"],
        "analysis.py": code["source/analysis_core.py"],
        "runner.py": code["source/analysis_core.py"],
        "tool_defect.py": b"# fixture driver\n",
    }
    for name, raw in files.items():
        (snapshot / name).write_bytes(raw)
    (snapshot / "protocol.md").write_bytes(b"fixture-only protocol")
    config = {
        "suite_sha256": package["suite"]["sha256"],
        "implementation_sha256": {
            "source/" + name: public.sha(raw)
            for name, raw in files.items()
            if name != "tool_defect.py"
        },
        "driver_sha256": public.sha(files["tool_defect.py"]),
        "protocol_sha256": public.sha(b"fixture-only protocol"),
    }
    config["sha256"] = public.digest(config)
    (run / "configuration.json").write_bytes(public.canonical(config))
    (run / "suite.json").write_bytes(public.canonical(package["suite"]))
    first = package["suite"]["cases"][0]
    (run / (first["case_id"] + ".input.json")).write_bytes(public.canonical(first))
    with pytest.raises(ValueError, match="started case lacks"):
        public.export_run(run, tmp_path / "public")
    assert not (tmp_path / "public").exists()
