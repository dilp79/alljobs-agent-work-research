"""Analytical regressions and refusal boundaries for the public research replay."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reproduce_research_note", ROOT / "scripts" / "reproduce_research_note.py"
)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def test_abstention_remains_in_declared_denominator() -> None:
    cells = [
        {"levels": [4, 4, 4], "mode": "screen", "count": 1,
         "importance_mass": 2.0, "employment_mass": 0.25},
        {"levels": [2, 3, 4], "mode": "screen", "count": 3,
         "importance_mass": 6.0, "employment_mass": 0.75},
    ]
    grid = replay.sensitivity_grid(cells)
    assert len(grid) == 108
    row = next(r for r in grid if r["combination"] == "exact_code_unanimity"
               and r["threshold"] == 4 and r["weight"] == "one_task_one_vote"
               and r["denominator"] == "whole_corpus")
    assert row["share_of_declared"] == 0.25
    assert row["share_of_settled"] == 1.0
    assert row["declared_mass"] == 4
    assert row["eligible_for_extrema"] is False


def test_unanswered_trial_is_not_a_failure_or_an_answer() -> None:
    rows = [
        {"mission_id": "a", "arm": "bare", "complete_votes": True,
         "suite_pass": True, "semantic_pass": True, "answered": True},
        {"mission_id": "b", "arm": "bare", "complete_votes": True,
         "suite_pass": None, "semantic_pass": None, "answered": False},
    ]
    table = replay.scaffold_table(rows)
    row = next(r for r in table if r["cohort"] == "all_answered"
               and r["checker"] == "suite_domain")
    assert (row["passes"], row["answered"], row["selected"], row["unanswered"]) == (1, 1, 2, 1)


def test_absent_input_refuses_before_creating_output(tmp_path: Path) -> None:
    output = tmp_path / "output"
    with pytest.raises(FileNotFoundError, match="publication inputs"):
        replay.reproduce(tmp_path, output, figures=False, permutations=0)
    assert not output.exists()


def test_frozen_v3_recomputes_losses_and_grades() -> None:
    result, rows = replay.v3_result(ROOT, permutations=0)
    assert len(rows) == 70
    assert result["passes"] == 44
    assert result["failures"] == 26
    assert result["baseline_log_loss"] == pytest.approx(0.43625738430047883, abs=1e-12)
    assert result["augmented_log_loss"] == pytest.approx(0.5197189980700662, abs=1e-12)
    assert result["homogeneous_categories"] == 6
    assert result["permutation_status"] == "not_recomputed"


def test_current_public_sufficient_statistics_reproduce_the_final_partition() -> None:
    data = replay.read_json(ROOT / replay.PUBLICATION / replay.INPUT_NAME)
    grid = replay.sensitivity_grid(data["sensitivity"]["cells"])
    eligible = [r for r in grid if r["eligible_for_extrema"]]
    assert len(eligible) == 90
    assert min(r["share_of_declared"] for r in eligible) == pytest.approx(0.00025406053800797516)
    assert max(r["share_of_declared"] for r in eligible) == pytest.approx(7069 / 8990)
    table = replay.scaffold_table(data["scaffold"]["rows"])
    all_answered = [r for r in table if r["cohort"] == "all_answered"]
    assert [(r["passes"], r["answered"]) for r in all_answered] == [
        (69, 82), (78, 82), (0, 82), (0, 82), (0, 81), (1, 81)
    ]


def test_corrupt_public_input_refuses_before_creating_output(tmp_path: Path) -> None:
    data = replay.read_json(ROOT / replay.PUBLICATION / replay.INPUT_NAME)
    data["sensitivity"]["cells"][0]["count"] += 1
    inputs = tmp_path / replay.PUBLICATION / replay.INPUT_NAME
    inputs.parent.mkdir(parents=True)
    inputs.write_text(json.dumps(data))
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="payload hash mismatch"):
        replay.reproduce(tmp_path, output, figures=False, permutations=0)
    assert not output.exists()


@pytest.mark.parametrize("location", ["external-output", "data/publication_2026_09_06/reproduced"])
def test_existing_outputs_are_preserved_before_replay(tmp_path: Path, location: str) -> None:
    output = tmp_path / location
    output.mkdir(parents=True)
    original = b"existing published figure bytes\x00\xff"
    figure = output / "figure_1_definition_sensitivity.png"
    figure.write_bytes(original)
    with pytest.raises(FileExistsError, match="refusing existing replay output"):
        replay.reproduce(tmp_path, output, figures=False, permutations=0)
    assert figure.read_bytes() == original
    assert list(output.iterdir()) == [figure]
