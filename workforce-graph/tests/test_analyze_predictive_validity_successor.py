"""Locked held-out log-loss and blocked-permutation analysis."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "analyze_predictive_validity_successor.py"
_spec = importlib.util.spec_from_file_location("analyze_predictive_validity_successor", SCRIPT)
analysis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analysis)


def _rows() -> list[dict]:
    rows = []
    for category_index, category in enumerate(analysis.CATEGORY_ORDER):
        for index in range(7):
            vote = index % 4
            rows.append(
                {
                    "base_mission_id": f"{category}-{index}",
                    "category": category,
                    "difficulty_index": 8.0 + index / 10 + category_index / 100,
                    "failure": vote >= 2,
                    "vote_doses": {
                        "can_do": vote,
                        "no_human_review": vote,
                        "requires_tool_access": 3 - vote,
                    },
                }
            )
    return rows


def test_cross_validated_models_return_all_held_out_predictions() -> None:
    rows = _rows()
    baseline = analysis.cross_validated_log_loss(rows, include_votes=False)
    augmented = analysis.cross_validated_log_loss(rows, include_votes=True)
    assert baseline["observations"] == 70
    assert augmented["observations"] == 70
    assert augmented["log_loss"] < baseline["log_loss"]
    assert set(augmented["predictions"]) == {row["base_mission_id"] for row in rows}


def test_blocked_permutation_preserves_category_vote_multisets() -> None:
    rows = _rows()
    shuffled = analysis.permute_votes_within_category(rows, seed="test-seed")
    for category in analysis.CATEGORY_ORDER:
        before = sorted(
            tuple(row["vote_doses"].values()) for row in rows if row["category"] == category
        )
        after = sorted(
            tuple(row["vote_doses"].values()) for row in shuffled if row["category"] == category
        )
        assert after == before


def test_analysis_stops_when_failure_target_is_missed() -> None:
    rows = _rows()
    for row in rows:
        row["failure"] = False
    result = analysis.analyze_rows(rows, permutations=19)
    assert result["decision"] == "HOLD_INSTRUMENT_RANGE_MISS"
    assert result["predictive_analysis"] is None
