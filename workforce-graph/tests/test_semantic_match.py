"""Regression tests for the deterministic layer-two semantic comparator."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path


_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location("semantic_match", _SCRIPTS / "semantic_match.py")
sm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sm)


def _reconciliation() -> dict:
    return {
        "mission_id": "sbov1-data_reconciliation-01",
        "matched_records": [
            {"left_record_id": "left-1", "right_record_id": "right-1", "status": "matched"}
        ],
        "unmatched_records": ["left-2:right-2"],
        "discrepancy_summary": "One exact match and one discrepancy.",
    }


def test_membership_non_id_decision_flip_is_rejected():
    expected = _reconciliation()
    actual = copy.deepcopy(expected)
    actual["matched_records"][0]["status"] = "discrepancy"

    result = sm.compare(expected, actual)

    assert not result["matched"]
    assert result["mismatched"] == ["matched_records"]
    assert "matched_records[].status" in result["membership_mismatches"]


def test_omitted_membership_decision_field_is_rejected():
    expected = _reconciliation()
    actual = copy.deepcopy(expected)
    del actual["matched_records"][0]["status"]

    result = sm.compare(expected, actual)

    assert not result["matched"]
    assert "matched_records[].status" in result["missing"]


def test_contradictory_extra_decision_fields_are_rejected():
    expected = _reconciliation()
    actual = copy.deepcopy(expected)
    actual["matched_records"][0]["severity"] = "critical"
    actual["risk"] = "high"

    result = sm.compare(expected, actual)

    assert not result["matched"]
    assert result["extra_decision_fields"] == ["matched_records[].severity", "risk"]


def test_legacy_reproduction_makes_hardening_delta_explicit():
    expected = _reconciliation()
    actual = copy.deepcopy(expected)
    del actual["matched_records"][0]["status"]
    actual["risk"] = "high"

    assert sm.compare_legacy(expected, actual)["matched"]
    assert not sm.compare(expected, actual)["matched"]


def test_prose_is_exempt_not_claimed_as_compared():
    expected = _reconciliation()
    actual = copy.deepcopy(expected)
    actual["discrepancy_summary"] = "Contradictory prose that is deliberately not adjudicated."

    result = sm.compare(expected, actual)

    assert result["matched"]
    assert result["exempt"] == ["discrepancy_summary"]
    assert "discrepancy_summary" not in result["compared"]
    assert "does not verify exempt prose" in result["claim_ceiling"]


def test_mutation_calibration_rejects_every_required_class():
    report = sm.mutation_calibration(sm.load_expected())

    assert set(report) == {
        "decision_flip",
        "membership_non_id_flip",
        "omitted_field",
        "contradictory_extra_field",
        "numeric_perturbation",
        "identity_swap",
    }
    for result in report.values():
        assert result["attempted"] > 0
        assert result["false_accepts"] == 0
        assert result["false_accept_rate"] == 0.0


def test_cross_mission_calibration_uses_all_ordered_within_category_pairs():
    report = sm.cross_mission_calibration(sm.load_expected())

    # Ten categories, each with twelve missions: 10 * 12 * 11 ordered pairs.
    assert report["ordered_pairs"] == 1320
    assert report["false_accepts"] == 0


def test_uncovered_field_names_are_explicit():
    report = sm.coverage_report(sm.load_expected())

    assert set(report["uncovered_fields"]) == sm.PROSE_FIELDS
    assert report["policy"] == "exempt_not_verified"
