"""Preregistered harder-mission predictive-validity successor."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build_predictive_validity_successor.py"
_spec = importlib.util.spec_from_file_location("build_predictive_validity_successor", SCRIPT)
successor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(successor)


def _catalog(tmp_path: Path) -> Path:
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "id": successor.MODEL_ID,
                        "name": "Google: Gemini 3.5 Flash Lite",
                        "context_length": 1_048_576,
                        "pricing": {
                            "prompt": "0.0000003",
                            "completion": "0.0000025",
                        },
                        "supported_parameters": [
                            "max_tokens",
                            "response_format",
                            "seed",
                            "temperature",
                            "tool_choice",
                            "tools",
                        ],
                    }
                ]
            }
        )
    )
    return path


def _endpoints(tmp_path: Path) -> Path:
    path = tmp_path / "endpoints.json"
    path.write_text(
        json.dumps(
            {
                "data": {
                    "id": successor.MODEL_ID,
                    "endpoints": [
                        {
                            "provider_name": "Google AI Studio",
                            "tag": "google-ai-studio",
                            "status": 0,
                            "pricing": {
                                "prompt": "0.0000003",
                                "completion": "0.0000025",
                            },
                        }
                    ],
                }
            }
        )
    )
    return path


def _frame(tmp_path: Path) -> dict:
    transport = tmp_path / "transport.json"
    transport.write_text(
        json.dumps({"data": [{"id": successor.MODEL_ID, "owned_by": "openrouter"}]})
    )
    return successor.build_frame(
        model_catalog=_catalog(tmp_path),
        endpoint_catalog=_endpoints(tmp_path),
        transport_catalog=transport,
        transport_base_url="http://localhost:3001/v1",
        base_commit="1" * 40,
    )


def test_frame_is_balanced_competent_and_frozen_before_model_spend(tmp_path: Path) -> None:
    frame = _frame(tmp_path)
    successor.validate_frame(frame)

    assert len(frame["pilot_cases"]) == 20
    assert len(frame["main_cases"]) == 70
    assert Counter(row["category"] for row in frame["pilot_cases"]) == {
        category: 2 for category in successor.CATEGORY_ORDER
    }
    assert Counter(row["category"] for row in frame["main_cases"]) == {
        category: 7 for category in successor.CATEGORY_ORDER
    }
    assert {row["variant"] for row in frame["pilot_cases"]} == {
        "semantic_shift",
        "dense_semantic_shift",
    }
    assert {row["variant"] for row in frame["main_cases"]} == {"dense_semantic_shift"}
    assert all(row["competence_gate"]["expected_passes"] for row in frame["pilot_cases"])
    assert all(row["competence_gate"]["stale_output_rejected"] for row in frame["main_cases"])
    assert frame["analysis_plan"]["target_failure_count"] == [14, 28]
    assert frame["analysis_plan"]["independent_mission_clusters"] == 70
    assert frame["model_budget"]["maximum_case_runs"] == 110
    assert set(frame["category_worked_examples"]) == set(successor.CATEGORY_ORDER)
    assert frame["claim_ceiling"]["mission_success_measured"] is False


def test_frame_validation_rejects_payload_or_predictor_mutation(tmp_path: Path) -> None:
    frame = _frame(tmp_path)
    frame["main_cases"][0]["vote_doses"]["can_do"] = 99
    with pytest.raises(ValueError, match="payload hash"):
        successor.validate_frame(frame)


def test_pilot_scaffold_rule_is_locked_and_stops_outside_target() -> None:
    records = []
    failure_counts = {
        "worked_example": 8,
        "worked_example_plus_recursive_shape": 5,
    }
    for scaffold, failures in failure_counts.items():
        records.extend(
            {"scaffold": scaffold, "outcome": {"conformant": index >= failures}}
            for index in range(20)
        )
    decision = successor.select_scaffold(records)
    assert decision["decision"] == "PROCEED_MAIN"
    assert decision["selected_scaffold"] == "worked_example_plus_recursive_shape"

    for record in records:
        record["outcome"]["conformant"] = True
    decision = successor.select_scaffold(records)
    assert decision["decision"] == "HOLD_INSTRUMENT_RANGE_MISS"
    assert decision["selected_scaffold"] is None


def test_freeze_is_atomic_no_replace(tmp_path: Path) -> None:
    frame = _frame(tmp_path)
    output = tmp_path / "frame.json"
    assert successor.freeze_json(output, frame) == "written"
    assert successor.freeze_json(output, frame) == "unchanged"
    frame["base_commit"] = "2" * 40
    frame["payload_sha256"] = successor.payload_hash(frame)
    with pytest.raises(FileExistsError):
        successor.freeze_json(output, frame)
