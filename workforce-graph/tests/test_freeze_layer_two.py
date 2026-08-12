"""Determinism and arithmetic guards for the layer-two freeze artifact."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location("freeze_layer_two", _SCRIPTS / "freeze_layer_two.py")
fl2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fl2)


def test_file_receipt_binds_hash_bytes_and_physical_lines(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_bytes(b'{"a":1}\n{"b":2}')

    receipt = fl2.file_receipt(path, base=tmp_path)

    assert receipt["path"] == "input.jsonl"
    assert receipt["bytes"] == 15
    assert receipt["line_count"] == 2
    assert len(receipt["sha256"]) == 64


def test_exact_fisher_power_ceiling_is_outcome_specific():
    semantic = fl2.power_ceiling(successes=75, total=78, reference_group_n=30, contrast_group_n=14)
    byte = fl2.power_ceiling(successes=67, total=78, reference_group_n=30, contrast_group_n=14)

    assert semantic["minimum_detectable_contrast_failures"] == 3
    assert semantic["minimum_detectable_contrast_failure_rate"] == 3 / 14
    assert semantic["observed_failure_rate"] == 3 / 78
    assert byte["observed_failure_rate"] == 11 / 78
    assert (
        semantic["detectable_to_observed_failure_rate_ratio"]
        != byte["detectable_to_observed_failure_rate_ratio"]
    )


def test_canonical_write_is_byte_stable(tmp_path):
    artifact = {"z": [3, 2, 1], "a": {"value": 1}}
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    fl2.write_artifact(artifact, first)
    fl2.write_artifact(artifact, second)

    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().endswith(b"\n")


def test_production_freeze_keeps_byte_and_semantic_outcomes_separate():
    root = Path(__file__).resolve().parent.parent
    raw = root / "data" / "trials" / "TRIALS_bare_deepseek-v4-pro.jsonl"
    if not raw.exists():
        return

    artifact = fl2.build_freeze(root)

    assert artifact["outcomes"]["byte_suite_checker"]["all_answered"] == {
        "passed": 69,
        "failed": 13,
        "total": 82,
    }
    assert artifact["outcomes"]["semantic_legacy"]["all_answered"] == {
        "passed": 78,
        "failed": 4,
        "total": 82,
    }
    assert artifact["outcomes"]["semantic_hardened"]["all_answered"] == {
        "passed": 78,
        "failed": 4,
        "total": 82,
    }
    assert artifact["outcomes"]["byte_suite_checker"]["complete_vote_join"]["failed"] == 11
    assert artifact["outcomes"]["semantic_legacy"]["complete_vote_join"]["failed"] == 3
    assert artifact["outcomes"]["semantic_hardened"]["complete_vote_join"]["failed"] == 3
    assert artifact["semantic_transition"]["changed_verdicts"] == []
    assert artifact["outcomes"]["semantic_legacy"]["power_calculations"] is None
    assert artifact["outcomes"]["semantic_hardened"]["power_calculations"]
    assert artifact["redacted_arm_preflight"]["evaluated_targets"] == 82
    assert artifact["redacted_arm_preflight"]["decision"] in {"HOLD", "DIAGNOSTIC_ONLY"}
    assert artifact["claim_ceiling"]["redacted_arm"] == (
        "bundled redaction sensitivity diagnostic only; not format, reusable-content, "
        "copying, capability, mission success, or a causal arm effect"
    )
    assert len(artifact["missions"]) == 120
    assert artifact["claim_ceiling"]["primary_outcome"] == "not_selected"


def test_committed_freeze_reproduces_exactly_when_raw_inputs_exist():
    root = Path(__file__).resolve().parent.parent
    committed = root / "data" / "benchmark_relevance" / "layer_two_freeze.json"
    raw = root / "data" / "trials" / "TRIALS_bare_deepseek-v4-pro.jsonl"
    if not committed.exists() or not raw.exists():
        return

    artifact = fl2.build_freeze(root)
    overlap = artifact["worked_example_literal_overlap"]

    assert overlap["aggregate"]["missions_with_any_exact_non_id_output_literal"] == 67
    assert overlap["aggregate"]["measured_missions"] == 82
    assert overlap["aggregate"]["missions_with_replaceable_non_id_output_string"] == 39
    assert overlap["aggregate"]["missions_with_enum_output_string"] == 64
    assert overlap["aggregate"]["missions_with_enum_output_string_only"] == 28
    assert overlap["policy"]["enum_treatment"] == "included in aggregate and itemized separately"
    assert set(overlap["policy"]["excluded"]) == {
        "identity_strings",
        "template_keys",
        "non_string_scalars",
    }
    assert len(overlap["per_mission_receipts"]) == 82
    assert (
        sum(
            receipt["shares_any_exact_non_id_output_literal"]
            for receipt in overlap["per_mission_receipts"]
        )
        == 67
    )
    assert all(
        len(payload_receipt["sha256"]) == 64
        for receipt in overlap["per_mission_receipts"]
        for payload_receipt in receipt["source_payload_receipts"].values()
    )
    assert committed.read_bytes() == fl2._canonical_bytes(artifact)
    assert json.loads(committed.read_text(encoding="utf-8")) == artifact
