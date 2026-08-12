"""Offline guards for layer-two mission rendering and trial aggregation."""

from __future__ import annotations

import importlib.util
import json
import sys
import copy
from collections import OrderedDict
from pathlib import Path

from click.testing import CliRunner


_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS.parent / "src"))
_spec = importlib.util.spec_from_file_location("run_missions", _SCRIPTS / "run_missions.py")
rm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rm)


def _shape(value):
    if isinstance(value, dict):
        return ("dict", tuple((key, _shape(item)) for key, item in value.items()))
    if isinstance(value, list):
        return ("list", len(value), tuple(_shape(item) for item in value))
    return type(value).__name__


def test_describe_shape_reports_structure_without_values():
    payload = {"mission_id": "secret-123", "items": [{"id": "alpha", "amount": 900}]}

    rendered = rm.describe_shape(payload)

    assert "mission_id" in rendered and "items" in rendered
    assert "secret-123" not in rendered
    assert "alpha" not in rendered
    assert "900" not in rendered


def test_pick_example_is_category_matched_seed_stable_and_never_self():
    missions = {
        "target": {"mission_id": "target", "category": "c", "task_snapshot": {"split": "held_out"}},
        "dev-b": {
            "mission_id": "dev-b",
            "category": "c",
            "task_snapshot": {"split": "development"},
        },
        "dev-a": {
            "mission_id": "dev-a",
            "category": "c",
            "task_snapshot": {"split": "development"},
        },
        "other": {
            "mission_id": "other",
            "category": "x",
            "task_snapshot": {"split": "development"},
        },
    }

    assert rm.pick_example(missions["target"], missions, set(missions)) == "dev-a"


def test_redaction_preserves_shape_order_types_lengths_and_enum_vocabulary():
    example_input = {
        "mission_id": "example-01",
        "payload": OrderedDict(
            [
                ("record_id", "customer-77"),
                ("name", "Alex Example"),
                ("status", "pending"),
                ("amount_minor", 1250),
                ("date", "2032-04-12"),
                ("notes", ["Call Alex Example", "customer-77"]),
            ]
        ),
    }
    example_output = {
        "mission_id": "example-01",
        "payload": OrderedDict(
            [
                ("record_id", "customer-77"),
                ("status", "pending"),
                ("amount_minor", 1250),
                ("answer", "Call Alex Example"),
            ]
        ),
    }
    measured = [
        {
            "record_id": "measured-1",
            "status": "pending",
            "amount_minor": 7341,
            "date": "2040-01-02",
        }
    ]

    first = rm.redact_example(
        example_input, example_output, seed="target-01", forbidden_payloads=measured
    )
    second = rm.redact_example(
        example_input, example_output, seed="target-01", forbidden_payloads=measured
    )

    assert _shape(first["input_record"]) == _shape(example_input)
    assert _shape(first["output_record"]) == _shape(example_output)
    assert list(first["input_record"]["payload"]) == list(example_input["payload"])
    assert first["input_record"]["payload"]["status"] == "pending"
    assert first["output_record"]["payload"]["status"] == "pending"
    assert (
        first["input_record"]["payload"]["record_id"]
        == first["output_record"]["payload"]["record_id"]
    )
    assert (
        first["input_record"]["payload"]["amount_minor"]
        == first["output_record"]["payload"]["amount_minor"]
    )
    assert first["input_record"] == second["input_record"]
    assert first["output_record"] == second["output_record"]
    assert first["map_digest"] == second["map_digest"]
    assert first["overlap_audit"]["shared_replaceable_non_id_literals"] == []
    assert first["overlap_audit"]["shared_replaceable_id_literals"] == []
    assert "pending" in first["overlap_audit"]["shared_enum_literals"]
    assert "status" in first["overlap_audit"]["shared_template_keys"]


def test_redaction_is_disjoint_for_every_measured_mission_example():
    missions, inputs, expected = rm.load_suite()
    gradeable, _ = rm.gradeable(missions)
    gradeable_set = set(gradeable)
    measured = [
        mid
        for mid in gradeable
        if missions[mid]["task_snapshot"].get("split") in {"held_out", "ood"}
    ]
    forbidden = [inputs[mid]["payload"] for mid in measured] + [
        expected[mid]["payload"] for mid in measured
    ]

    assert len(measured) == 82
    for mid in measured:
        example_id = rm.pick_example(missions[mid], missions, gradeable_set)
        assert example_id is not None
        assert missions[example_id]["category"] == missions[mid]["category"]
        assert missions[example_id]["task_snapshot"]["split"] == "development"
        redacted = rm.redact_example(
            inputs[example_id],
            expected[example_id],
            seed=f"bare_redacted_example:{mid}:{example_id}",
            forbidden_payloads=forbidden,
        )
        assert redacted["overlap_audit"]["shared_replaceable_non_id_literals"] == []
        assert redacted["overlap_audit"]["shared_replaceable_id_literals"] == []


def test_competence_gate_accepts_a_reference_pair_via_domain_checker():
    missions, inputs, expected = rm.load_suite()
    mid = "sbov1-data_reconciliation-02"

    receipt = rm.redaction_competence_gate(mid, inputs[mid], expected[mid], missions[mid])

    assert receipt["deterministic_conformant"] is True
    assert receipt["operator_id"] == "reconcile-records"
    assert receipt["checker_version"] == "2.0.0"
    assert len(receipt["procedure_checksum"]) == 64
    assert receipt["human_holistic_verified"] is False


def test_competence_gate_rejects_a_relation_breaking_output():
    missions, inputs, expected = rm.load_suite()
    mid = "sbov1-data_reconciliation-02"
    broken = copy.deepcopy(expected[mid])
    broken["payload"]["matched_records"] = []

    receipt = rm.redaction_competence_gate(mid, inputs[mid], broken, missions[mid])

    assert receipt["deterministic_conformant"] is False
    assert "reconciliation-membership" in receipt["failed_invariants"]


def test_redacted_arm_preflight_evaluates_all_82_and_fails_closed():
    missions, inputs, expected = rm.load_suite()
    gradeable, _ = rm.gradeable(missions)

    preflight = rm.preflight_redacted_arm(missions, inputs, expected, set(gradeable))

    assert preflight["report"]["evaluated_targets"] == 82
    assert preflight["report"]["allowed"] is (not preflight["report"]["failures"])
    assert len(preflight["gate_receipts"]) == 82
    for failure in preflight["report"]["failures"]:
        assert failure["target_mission_id"]
        assert failure["example_mission_id"]
        assert failure["failed_invariants"]


def test_redacted_arm_cli_blocks_before_client_creation():
    result = CliRunner().invoke(
        rm.main,
        ["--arm", "bare_redacted_example", "--model", "must-not-be-called"],
    )

    assert result.exit_code != 0
    assert "decision=HOLD" in result.output
    assert "no model call was made" in result.output


def test_overlap_audit_detects_normalized_and_derived_leakage():
    measured = [
        {
            "name": "Résumé CASE",
            "record_id": "Client-ABC-123",
            "amount": 1,
            "date": "2032-04-12",
            "note": "secretfragment",
        }
    ]
    derived = rm.hashlib.sha256("résumé case".encode("utf-8")).hexdigest()[:12]
    redacted_input = {
        "name": "re\u0301sume\u0301 case",
        "record_id": "clientabc123",
        "amount": "1.00",
        "date": "2032-04-12T00:00:00Z",
        "note": "prefix-secretfragment-suffix",
        "digest": f"derived-{derived}",
    }

    audit = rm.example_overlap_audit(redacted_input, {}, forbidden_payloads=measured)

    assert audit["shared_replaceable_unicode_casefold_literals"]
    assert audit["shared_normalized_id_literals"]
    assert audit["shared_canonical_date_number_literals"]
    assert "secretfragment" in audit["shared_replaceable_tokens_or_substrings"]
    assert audit["shared_deterministically_derived_literals"]


def test_rendered_prompt_hash_binds_system_and_user_prompt():
    first = rm.rendered_prompt_hash("hello")
    assert first == rm.rendered_prompt_hash("hello")
    assert first != rm.rendered_prompt_hash("hello!")


def test_latest_trials_filters_run_spec_and_arm_before_taking_latest(tmp_path):
    path = tmp_path / "trials.jsonl"
    rows = [
        {
            "mission_id": "m1",
            "arm": "bare",
            "run_spec": "old",
            "deliverable": {},
            "verdict": {"conformant": False},
        },
        {
            "mission_id": "m1",
            "arm": "bare_redacted_example",
            "run_spec": "new",
            "deliverable": {},
            "verdict": {"conformant": True},
        },
        {
            "mission_id": "m1",
            "arm": "bare",
            "run_spec": "old",
            "deliverable": {},
            "verdict": {"conformant": True},
        },
        {"mission_id": "m2", "arm": "bare", "deliverable": {}, "verdict": {"conformant": True}},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    old = rm.latest_trials(path, run_spec="old", arm="bare")
    new = rm.latest_trials(path, run_spec="new", arm="bare_redacted_example")
    legacy = rm.latest_trials(path, run_spec=rm.LEGACY_RUN_SPEC, arm="bare")

    assert old["m1"]["verdict"]["conformant"] is True
    assert set(new) == {"m1"}
    assert set(legacy) == {"m2"}


def test_paired_common_answered_returns_exact_mcnemar_discordance():
    left = {
        "same-pass": {"verdict": {"conformant": True}},
        "left-only": {"verdict": {"conformant": True}},
        "right-only": {"verdict": {"conformant": False}},
        "same-fail": {"verdict": {"conformant": False}},
        "unanswered": {"verdict": {"conformant": None}},
    }
    right = {
        "same-pass": {"verdict": {"conformant": True}},
        "left-only": {"verdict": {"conformant": False}},
        "right-only": {"verdict": {"conformant": True}},
        "same-fail": {"verdict": {"conformant": False}},
        "unanswered": {"verdict": {"conformant": True}},
    }

    result = rm.paired_common_answered(left, right)

    assert result["common_answered"] == 4
    assert result["cells"] == {"both_pass": 1, "left_only": 1, "right_only": 1, "both_fail": 1}
    assert result["discordant_pairs"] == {"left_only": ["left-only"], "right_only": ["right-only"]}
    assert result["exact_mcnemar_two_sided_p"] == 1.0
