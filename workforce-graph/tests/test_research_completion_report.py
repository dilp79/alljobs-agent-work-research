"""Contract and fail-closed guards for the generated research completion report."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "build_research_completion_report.py"
_SPEC = importlib.util.spec_from_file_location("build_research_completion_report", _SCRIPT)
report = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = report
_SPEC.loader.exec_module(report)


def _with_payload_hash(value: dict, field: str) -> dict:
    value[field] = report._payload_sha256(value)
    return value


def _snapshot(*, complete: bool, settled: int = 2, explicit_nonresponse: bool = False) -> dict:
    collection_complete = complete or explicit_nonresponse
    status = {
        "third_rater": "gemini-3.5-flash-lite",
        "third_rater_status": (
            "complete_with_explicit_nonresponse"
            if explicit_nonresponse
            else "complete" if complete else "incomplete"
        ),
        "third_rater_complete": complete,
        "third_rater_collection_complete": collection_complete,
        "third_rater_nonresponses": (
            [
                {
                    "activity_id": "c",
                    "attempt_receipt_count": 20,
                    "cache_busted_record_count": 5,
                    "prompt_hash": "prompt-receipt",
                    "requested_model_id": "google/gemini-3.5-flash-lite",
                    "served_backend": "openrouter/google/gemini-3.5-flash-lite",
                    "status": "exact_route_no_valid_label",
                    "terminal_none_record_count": 5,
                    "claim_ceiling": (
                        "no valid third-rater label after exact-route attempts; per-attempt "
                        "content outcome and provider-side cause are not established"
                    ),
                }
            ]
            if explicit_nonresponse
            else []
        ),
        "claim_ceiling": (
            "hash-bound snapshot; downstream validity gates still apply"
            if collection_complete
            else "interim hash-bound baseline; not final work-mode evidence"
        ),
    }
    activities = {
        activity_id: {
            "label": label,
            "stratum": "control" if label else "contested",
            "n_raters": 3,
            "readings": {
                "gemini-3.5-flash-lite": "screen",
                "glm-5.2": "screen",
                "minimax-m3": "screen" if label else "physical",
            },
            "successful_label_values": ["screen"] if label else ["physical", "screen"],
            "label_source": "unanimous_at_least_two" if label else "split_awaiting_adjudication",
            "settlement": "settled" if label else "unsettled",
            "historical_experiment_arms": {},
        }
        for activity_id, label in (("a", "screen"), ("b", "physical"), ("c", None))
    }
    if explicit_nonresponse:
        activities["c"]["n_raters"] = 2
        activities["c"]["readings"].pop("gemini-3.5-flash-lite")
        activities["c"]["label_source"] = "third_rater_explicit_nonresponse"
    snapshot = {
        "schema": report.SNAPSHOT_SCHEMA,
        "snapshot_date": "2026-08-12",
        "snapshot_status": status,
        "input_scope": "test",
        "inputs": [
            {
                "role": "bulk_label",
                "identity": "gemini-3.5-flash-lite",
                "unique_successful_labels": 3 if complete else 2,
            }
        ],
        "partition_counts": {
            "activities": 3,
            "stratum": {"contested": 1, "control": 2},
            "settlement": {"settled": settled, "unsettled": 3 - settled},
            "n_raters": {"2": 1, "3": 2} if explicit_nonresponse else {"3": 3},
            "label": {"physical": 1, "screen": 1, "unsettled": 1},
            "label_source": (
                {"third_rater_explicit_nonresponse": 1, "unanimous_at_least_two": 2}
                if explicit_nonresponse
                else {"split_awaiting_adjudication": 1, "unanimous_at_least_two": 2}
            ),
        },
        "activities": activities,
    }
    return _with_payload_hash(snapshot, "snapshot_payload_sha256")


def _corrected(baseline: dict, final: dict) -> dict:
    transition = {
        "schema": report.TRANSITION_SCHEMA,
        "baseline_snapshot_payload_sha256": baseline["snapshot_payload_sha256"],
        "final_snapshot_payload_sha256": final["snapshot_payload_sha256"],
        "activity_inventory": {
            "baseline": 3,
            "final": 3,
            "common": 3,
            "added": [],
            "removed": [],
        },
        "stratum_2x2": {
            "baseline_contested__final_contested": 1,
            "baseline_contested__final_control": 0,
            "baseline_control__final_contested": 0,
            "baseline_control__final_control": 2,
        },
        "settlement_2x2": {
            "baseline_settled__final_settled": 2,
            "baseline_settled__final_unsettled": 0,
            "baseline_unsettled__final_settled": 0,
            "baseline_unsettled__final_unsettled": 1,
        },
        "previously_settled_to_split_awaiting_adjudication": 0,
        "stratum_changes": [],
        "label_changes": [],
        "range_under_each": {},
        "range_kind": "deterministic snapshot transition audit; not a confidence interval",
        "coverage_ceiling": "none",
    }
    _with_payload_hash(transition, "audit_payload_sha256")
    rate_keys = [
        f"{stratum}/{mode}"
        for stratum in ("contested", "control")
        for mode in ("screen", "mixed", "physical")
    ]
    strict = [0.2, 0.6]
    generous = [0.3, 0.7]
    result = {
        "schema": report.CORRECTED_SCHEMA,
        "rater_of_the_experiment": "glm-5.2",
        "settled_labels": 2,
        "corpus_size": 3,
        "label_source": final["partition_counts"]["label_source"],
        "state_snapshot_payload_sha256": final["snapshot_payload_sha256"],
        "state_snapshot_status": final["snapshot_status"],
        "experiment_input_binding": {"binding_verified": True},
        "route_receipt": {"route_guard_passed": True, "requested_rater": "glm-5.2"},
        "experiment_arm_policy": "historical",
        "digital_share_strict": strict,
        "digital_share_generous": generous,
        "range_kind": (
            "partial-identification sensitivity range under missing-attempt extrema and "
            "unsettled-label extrema; not a confidence interval"
        ),
        "coverage_ceiling": "none; deterministic extrema conditional on inputs and mapping",
        "components": {
            "missingness_partial_identification": {
                "range_kind": (
                    "partial-identification bounds for unanswered experiment attempts; "
                    "not a confidence interval"
                ),
                "coverage_ceiling": "none; no stochastic coverage claim",
                "decline_rates_low": dict.fromkeys(rate_keys, 0.1),
                "decline_rates_high": dict.fromkeys(rate_keys, 0.2),
                "digital_share_strict": strict,
                "digital_share_generous": generous,
            },
            "sampling_answered_attempts": {
                "range_kind": "separate sampling sensitivity; not a headline confidence interval",
                "coverage_ceiling": (
                    "95.0% marginal per fitted rate cell conditional on answered attempts and "
                    "selected backoff; no simultaneous/headline coverage claim"
                ),
                "method": "two-sided Wilson score interval",
                "digital_share_strict": [0.25, 0.55],
                "digital_share_generous": [0.35, 0.65],
            },
            "directional_not_triple_rated_forced_contested": {
                "all_not_triple_rated_activities": sum(
                    row["n_raters"] < 3 for row in final["activities"].values()
                ),
                "base": {
                    "digital_share_strict": strict,
                    "digital_share_generous": generous,
                },
            },
            "arm_transport": {
                "employment_weighted_material_effect": {
                    "historical_arm_policy": {
                        "digital_share_strict": strict,
                        "digital_share_generous": generous,
                    },
                    "delta_current_minus_historical": {
                        "digital_share_strict": [0.01, -0.01],
                        "digital_share_generous": [0.02, -0.02],
                    }
                }
            },
        },
        "transition_audit": transition,
        "lost_attempts": {"contested": 1, "control": 0},
        "weighted_after_correction": {
            "low": {
                "screen": 0.35,
                "mixed": 0.15,
                "physical": 0.30,
                "unknown": 0.0,
                "unsettled": 0.20,
            },
            "high": {
                "screen": 0.20,
                "mixed": 0.10,
                "physical": 0.30,
                "unknown": 0.20,
                "unsettled": 0.20,
            },
        },
        "incomplete": True,
    }
    return _with_payload_hash(result, "result_payload_sha256")


def _layer_two() -> dict:
    outcome = {
        "all_answered": {"passed": 78, "failed": 4, "total": 82},
        "complete_vote_join": {"passed": 75, "failed": 3, "total": 78},
    }
    return {
        "schema_version": report.LAYER_TWO_SCHEMA,
        "input_set_digest": "a" * 64,
        "selection": {
            "bound_missions": 120,
            "primary_measured_missions": 82,
            "complete_vote_join": 78,
            "exclusions_by_primary_reason": {"development_split": {"count": 38}},
            "complete_vote_join_exclusions_from_primary": {"count": 4},
        },
        "reported_number_checks": {"all_match": True},
        "claim_ceiling": {"primary_outcome": "not_selected"},
        "outcomes": {
            "byte_suite_checker": {
                "all_answered": {"passed": 69, "failed": 13, "total": 82},
                "complete_vote_join": {"passed": 67, "failed": 11, "total": 78},
            },
            "semantic_hardened": outcome,
        },
        "requires_tool_access_mismatch": {
            "construct_mismatch": True,
            "complete_measured_missions_with_any_endorsement": 77,
        },
        "prompt_receipt_assertion": {
            "exact_historical_prompt_bytes_verified": False,
            "rendered_prompt_hashes_present": 0,
        },
        "served_backend_receipt_assertion": {
            "measurement_trials": {"receipts_present": 82},
            "predictor_vote_rows": {"served_backend_verified": False},
        },
        "redacted_arm_preflight": {
            "decision": "HOLD",
            "evaluated_targets": 82,
            "failed_targets": 82,
        },
        "worked_example_literal_overlap": {
            "aggregate": {
                "measured_missions": 82,
                "missions_with_any_exact_non_id_output_literal": 67,
            }
        },
    }


def _registry() -> dict:
    return {
        "schema_version": report.EVIDENCE_SCHEMA,
        "profile_counts": {"collected_profiles": 8, "wired_capability_anchors": 5},
        "profiles": [
            {"id": "osworld_v2_paper_v2", "granularity": "item_level", "channel": ["gui"]},
            *[{"id": f"profile-{index}"} for index in range(7)],
        ],
        "edges": [{}] * 15,
        "edges_authorising_a_bound": 0,
    }


def _rli() -> dict:
    rows = [
        [f"model-{index}", "", str(index), "1.0", "2026-01-01T00:00:00.000Z"]
        for index in range(15)
    ]
    canonical = "".join("\t".join(row) + "\n" for row in rows).encode("utf-8")
    return {
        "schema_id": report.RLI_SCHEMA,
        "row_count": 15,
        "rows": rows,
        "canonical_tsv_bytes": len(canonical),
        "canonical_tsv_sha256": report.hashlib.sha256(canonical).hexdigest(),
        "recovery_verification": {
            "status": "EXACT_CANONICAL_MATCH",
            "raw_capture_retained": False,
            "raw_capture_sha256": None,
        },
    }


def _hh() -> dict:
    return {
        "schema_version": report.HH_SCHEMA,
        "recovery": {
            "relation_row_source": "current_recovery_database_not_missing_historical_database",
            "witness_class": "logical_witness_for_exact_accepted_projection_replay",
            "limitation": (
                "does_not_establish_historical_relation_row_identity_or_recover_historical_duckdb_bytes"
            ),
        },
        "hh_occupation": [{}] * 270,
        "hh_market_signal": [{}] * 270,
        "occupation_activity": [{}] * 2359,
    }


def _write(path: Path, value: object) -> None:
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _fixture_paths(
    tmp_path: Path, *, final_complete: bool = True, explicit_nonresponse: bool = False
) -> report.ReportPaths:
    baseline = _snapshot(complete=False)
    final = _snapshot(complete=final_complete, explicit_nonresponse=explicit_nonresponse)
    if final_complete or explicit_nonresponse:
        final["snapshot_status"]["completion_baseline_payload_sha256"] = baseline[
            "snapshot_payload_sha256"
        ]
        final.pop("snapshot_payload_sha256")
        _with_payload_hash(final, "snapshot_payload_sha256")
    values = {
        "baseline.json": baseline,
        "final.json": final,
        "corrected.json": _corrected(baseline, final),
        "layer-two.json": _layer_two(),
        "registry.json": _registry(),
        "rli.json": _rli(),
        "hh.json": _hh(),
        "external-audit.md": "# Bound audit\n",
    }
    for name, value in values.items():
        _write(tmp_path / name, value)
    return report.ReportPaths(
        baseline=tmp_path / "baseline.json",
        final_snapshot=tmp_path / "final.json",
        corrected=tmp_path / "corrected.json",
        layer_two=tmp_path / "layer-two.json",
        evidence_registry=tmp_path / "registry.json",
        rli_authority=tmp_path / "rli.json",
        hh_witness=tmp_path / "hh.json",
        external_audit=tmp_path / "external-audit.md",
    )


def _cli_args(paths: report.ReportPaths) -> list[str]:
    options = {
        "work_mode_baseline": "--baseline",
        "work_mode_final": "--final-snapshot",
        "work_mode_corrected": "--corrected",
        "layer_two_freeze": "--layer-two",
        "evidence_registry": "--evidence-registry",
        "rli_authority": "--rli-authority",
        "hh_logical_witness": "--hh-witness",
        "computer_use_evidence_audit": "--external-audit",
    }
    return [item for role, path in paths.items() for item in (options[role], str(path))]


def test_partial_identification_is_research_complete_when_rater_is_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "EXPECTED_CORPUS", 3)
    paths = _fixture_paths(tmp_path)

    summary = report.load_and_validate(paths)

    assert summary["research_status"] == "RESEARCH_COMPLETE_WITH_PARTIAL_IDENTIFICATION"
    assert summary["settled"] == 2
    assert summary["unsettled"] == 1


def test_one_bound_nonresponse_completes_collection_without_claiming_a_label(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "EXPECTED_CORPUS", 3)
    paths = _fixture_paths(tmp_path, final_complete=False, explicit_nonresponse=True)

    summary = report.load_and_validate(paths)
    rendered = report.render_report(summary, paths, "2026-08-12", tmp_path / "report.md").decode()

    assert summary["research_status"] == "RESEARCH_COMPLETE_WITH_PARTIAL_IDENTIFICATION"
    assert summary["third_readings"] == 2
    assert summary["third_nonresponses"] == 1
    assert "2 успешных" in rendered
    assert "1 hash-bound explicit nonresponse" in rendered
    assert "не была подставлена" in rendered
    assert "--third-rater-status complete_with_explicit_nonresponse" in rendered
    assert "--third-rater-nonresponse c" in rendered
    assert "--third-rater-request-model google/gemini-3.5-flash-lite" in rendered


def test_incomplete_third_rater_is_hold_and_never_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "EXPECTED_CORPUS", 3)
    paths = _fixture_paths(tmp_path, final_complete=False)
    output = tmp_path / "must-not-exist.md"
    runner = CliRunner()

    result = runner.invoke(
        report.main,
        _cli_args(paths) + ["--report-date", "2026-08-12", "--output", str(output)],
    )

    assert result.exit_code != 0
    assert "HOLD: research completion gates failed" in result.output
    assert "third-rater collection is incomplete" in result.output
    assert not output.exists()


def test_report_bytes_are_deterministic_checked_and_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "EXPECTED_CORPUS", 3)
    paths = _fixture_paths(tmp_path)
    output = tmp_path / "report.md"
    runner = CliRunner()
    args = _cli_args(paths) + ["--report-date", "2026-08-12", "--output", str(output)]

    first = runner.invoke(report.main, args)
    first_bytes = output.read_bytes()
    second = runner.invoke(report.main, args)
    checked = runner.invoke(report.main, args + ["--check"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "unchanged" in second.output
    assert checked.exit_code == 0
    assert "PASS byte-identical" in checked.output
    assert output.read_bytes() == first_bytes
    assert first_bytes.endswith(b"\n")
    assert b"Primary outcome" in first_bytes
    assert b"REPORT_PATH" not in first_bytes
    assert b"mktemp -d /tmp/alljobs-research-replay" in first_bytes
    assert b'--output "$final_replay"' in first_bytes
    assert f"--output {paths.final_snapshot}".encode() not in first_bytes
    assert f"--write {paths.corrected}".encode() not in first_bytes

    output.write_text("different\n", encoding="utf-8")
    refused = runner.invoke(report.main, args)
    assert refused.exit_code != 0
    assert "refusing to replace" in refused.output
    assert output.read_text(encoding="utf-8") == "different\n"


@pytest.mark.parametrize(
    ("role", "mutation", "message"),
    [
        (
            "work_mode_final",
            lambda value: value["activities"]["a"].update({"label": "mixed"}),
            "embedded payload hash mismatch",
        ),
        (
            "layer_two_freeze",
            lambda value: value["claim_ceiling"].update({"primary_outcome": "semantic_hardened"}),
            "primary outcome was selected",
        ),
        (
            "evidence_registry",
            lambda value: value.update({"edges_authorising_a_bound": 1}),
            "external edge now authorises a bound",
        ),
    ],
)
def test_material_drift_fails_closed(tmp_path, monkeypatch, role, mutation, message):
    monkeypatch.setattr(report, "EXPECTED_CORPUS", 3)
    paths = _fixture_paths(tmp_path)
    target = dict(paths.items())[role]
    value = json.loads(target.read_text(encoding="utf-8"))
    mutation(value)
    _write(target, value)

    with pytest.raises(report.ReportInputError, match=message):
        report.load_and_validate(paths)


def test_rehashed_arbitrary_partial_identification_endpoints_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "EXPECTED_CORPUS", 3)
    paths = _fixture_paths(tmp_path)
    corrected = json.loads(paths.corrected.read_text(encoding="utf-8"))
    zero = [0.0, 0.0]
    corrected["digital_share_strict"] = zero
    corrected["digital_share_generous"] = zero
    corrected["components"]["missingness_partial_identification"]["digital_share_strict"] = zero
    corrected["components"]["missingness_partial_identification"]["digital_share_generous"] = zero
    corrected["components"]["directional_not_triple_rated_forced_contested"]["base"] = {
        "digital_share_strict": zero,
        "digital_share_generous": zero,
    }
    corrected["components"]["arm_transport"]["employment_weighted_material_effect"][
        "historical_arm_policy"
    ] = {"digital_share_strict": zero, "digital_share_generous": zero}
    corrected.pop("result_payload_sha256")
    _with_payload_hash(corrected, "result_payload_sha256")
    _write(paths.corrected, corrected)

    with pytest.raises(report.ReportInputError, match="weighted extrema"):
        report.load_and_validate(paths)


def test_current_interim_inputs_are_hold_and_preflight_writes_nothing(tmp_path):
    repo = _ROOT.parent
    paths = report.ReportPaths(
        baseline=_ROOT
        / "data/work_mode/work_mode_baseline_2026-08-11_incomplete-third-rater.json",
        final_snapshot=_ROOT
        / "data/work_mode/work_mode_baseline_2026-08-11_incomplete-third-rater.json",
        corrected=_ROOT
        / "data/work_mode/corrected_result_full_glm_2026-08-11_incomplete-third-rater.json",
        layer_two=_ROOT / "data/benchmark_relevance/layer_two_freeze.json",
        evidence_registry=_ROOT / "data/evidence/registry.json",
        rli_authority=_ROOT / "research/authorities/rli-15row-canonical.json",
        hh_witness=_ROOT
        / "research/authorities/content_27_hh.2026-04-12.logical-slice.v1.json",
        external_audit=repo / "docs/audits/2026-08-11-computer-use-evidence-update.md",
    )
    runner = CliRunner()

    result = runner.invoke(report.main, _cli_args(paths) + ["--preflight"])

    assert result.exit_code != 0
    assert "HOLD: research completion gates failed" in result.output
    assert "third-rater collection is incomplete" in result.output
    assert list(tmp_path.iterdir()) == []
