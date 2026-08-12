"""Freeze both deterministic layer-two outcomes without running a model or mission.

The artifact produced here keeps the suite/byte outcome and the semantic comparator outcome
separate at every level: all answered missions, complete-vote joins, failure rosters, dose
tables, and outcome-specific power ceilings. It reads existing trial/vote rows and never calls
the router, a mission runner, or a model evaluator.

The primary historical trial predates `run_spec`; that absence is represented explicitly as
`legacy-missing-run-spec`. The freeze does not repair or rewrite raw rows. It also does not
select a primary outcome: choosing byte identity or semantic agreement changes the estimand
and remains a founder decision.

Usage:
    python scripts/freeze_layer_two.py
    python scripts/freeze_layer_two.py --check
"""

from __future__ import annotations

import collections
import csv
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import click


ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "benchmark" / "support_backoffice" / "v1"
PRIMARY_TRIAL = "TRIALS_bare_deepseek-v4-pro.jsonl"
PRIMARY_ARM = "bare"
PRIMARY_RUN_SPEC = "legacy-missing-run-spec"
OUTPUT = ROOT / "data" / "benchmark_relevance" / "layer_two_freeze.json"
SCHEMA_VERSION = "alljobs.layer-two-freeze.v1"


def _physical_line_count(data: bytes) -> int:
    return data.count(b"\n") + int(bool(data) and not data.endswith(b"\n"))


def file_receipt(path: Path, *, base: Path = ROOT) -> dict:
    data = path.read_bytes()
    try:
        display_path = path.relative_to(base).as_posix()
    except ValueError:
        display_path = path.as_posix()
    return {
        "path": display_path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "line_count": _physical_line_count(data),
    }


def _canonical_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_artifact(artifact: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(artifact))


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: expected an object")
        rows.append(row)
    return rows


def _legacy_latest_primary(path: Path) -> tuple[dict[str, dict], dict]:
    latest: dict[str, dict] = {}
    duplicate_counts = collections.Counter()
    excluded = collections.Counter()
    for row in _load_jsonl(path):
        if row.get("arm") != PRIMARY_ARM:
            excluded["different_arm"] += 1
            continue
        if row.get("run_spec", PRIMARY_RUN_SPEC) != PRIMARY_RUN_SPEC:
            excluded["different_run_spec"] += 1
            continue
        mid = row.get("mission_id")
        if not mid:
            excluded["missing_mission_id"] += 1
            continue
        if mid in latest:
            duplicate_counts[mid] += 1
        latest[mid] = row
    return latest, {
        "raw_rows": sum(1 for _ in _load_jsonl(path)),
        "latest_unique_missions": len(latest),
        "superseded_duplicate_rows": sum(duplicate_counts.values()),
        "missions_with_duplicates": sorted(duplicate_counts),
        "excluded_rows_by_reason": dict(sorted(excluded.items())),
        "selected_arm": PRIMARY_ARM,
        "selected_run_spec": PRIMARY_RUN_SPEC,
    }


def _load_semantic_module(root: Path):
    spec = importlib.util.spec_from_file_location(
        "freeze_semantic_match", root / "scripts" / "semantic_match.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_run_missions_module(root: Path):
    spec = importlib.util.spec_from_file_location(
        "freeze_run_missions", root / "scripts" / "run_missions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_operator_lookup(root: Path, mission_ids: list[str]) -> tuple[dict[str, str], list[str]]:
    source = str(root / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    from workforce_graph.evidence.task4_phase2b_operators import (  # noqa: PLC0415
        operator_contract_for_mission,
    )

    operators = {}
    ungradeable = []
    for mid in mission_ids:
        try:
            operators[mid] = operator_contract_for_mission(mid).operator_id
        except ValueError:
            ungradeable.append(mid)
    return operators, sorted(ungradeable)


def _load_votes(scoring_dir: Path) -> tuple[dict[str, dict[str, dict]], dict]:
    votes: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    file_roles = {}
    duplicate_rows = collections.Counter()
    for path in sorted(scoring_dir.glob("*.jsonl")):
        if path.stem == "sample":
            file_roles[path.name] = "excluded_non_vote_sample_manifest"
            continue
        file_roles[path.name] = "predictor_vote_rows"
        for row in _load_jsonl(path):
            aid = row.get("activity_id")
            if not aid:
                continue
            if path.stem in votes[aid]:
                duplicate_rows[path.name] += 1
            votes[aid][path.stem] = row
    return votes, {
        "file_roles": dict(sorted(file_roles.items())),
        "rater_files": sorted(
            name for name, role in file_roles.items() if role == "predictor_vote_rows"
        ),
        "duplicate_activity_rows_latest_wins": dict(sorted(duplicate_rows.items())),
    }


def _endorsements(votes: dict[str, dict], field: str) -> int | None:
    if len(votes) != 3:
        return None
    if field == "can_do":
        return sum(row.get("can_do") == "yes" for row in votes.values())
    if field == "no_human_review":
        return sum(row.get("requires_human_review") is False for row in votes.values())
    if field == "requires_tool_access":
        return sum(row.get("requires_tool_access") is True for row in votes.values())
    raise ValueError(field)


def _fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact probability using fixed margins, without SciPy."""
    row_one = a + b
    row_two = c + d
    success_total = a + c
    total = row_one + row_two
    lo = max(0, row_one - (total - success_total))
    hi = min(row_one, success_total)

    def probability(cell_a: int) -> float:
        return (
            math.comb(success_total, cell_a)
            * math.comb(total - success_total, row_one - cell_a)
            / math.comb(total, row_one)
        )

    observed = probability(a)
    return min(
        1.0,
        sum(
            probability(cell_a)
            for cell_a in range(lo, hi + 1)
            if probability(cell_a) <= observed + 1e-15
        ),
    )


def power_ceiling(
    *,
    successes: int,
    total: int,
    reference_group_n: int,
    contrast_group_n: int,
    alpha: float = 0.05,
) -> dict:
    """Minimum extreme-group failures detectable by the exact test used in the narrative.

    This is a ceiling diagnostic, not prospective statistical power. The reference group is
    assumed perfect and failures are added to the contrast group until a two-sided Fisher test
    crosses alpha. The calculation is repeated separately for each observed outcome because
    their overall failure rates differ.
    """
    threshold = None
    threshold_p = None
    for failures in range(1, contrast_group_n + 1):
        p_value = _fisher_two_sided(reference_group_n, 0, contrast_group_n - failures, failures)
        if p_value < alpha:
            threshold = failures
            threshold_p = p_value
            break
    observed_failures = total - successes
    observed_rate = observed_failures / total if total else None
    detectable_rate = (
        threshold / contrast_group_n if threshold is not None and contrast_group_n else None
    )
    ratio = (
        detectable_rate / observed_rate
        if detectable_rate is not None and observed_rate not in (None, 0)
        else None
    )
    return {
        "method": "exact_two_sided_fisher_extreme_group_ceiling_not_prospective_power",
        "alpha": alpha,
        "reference_group_assumed": {"successes": reference_group_n, "failures": 0},
        "contrast_group_n": contrast_group_n,
        "minimum_detectable_contrast_failures": threshold,
        "minimum_detectable_contrast_failure_rate": detectable_rate,
        "threshold_fisher_two_sided_p": threshold_p,
        "observed_failures_all_complete_cases": observed_failures,
        "observed_failure_rate": observed_rate,
        "detectable_to_observed_failure_rate_ratio": ratio,
    }


def _summary(values: list[bool]) -> dict:
    passed = sum(values)
    return {"passed": passed, "failed": len(values) - passed, "total": len(values)}


def _dose_table(missions: list[dict], predictor: str, outcome: str) -> list[dict]:
    rows = []
    for dose in range(4):
        selected = [m for m in missions if m["vote_doses"].get(predictor) == dose]
        values = [
            m["outcomes"][outcome] for m in selected if isinstance(m["outcomes"].get(outcome), bool)
        ]
        rows.append({"dose": dose, **_summary(values)})
    return rows


def _power_from_table(outcome_summary: dict, table: list[dict]) -> dict:
    return power_ceiling(
        successes=outcome_summary["passed"],
        total=outcome_summary["total"],
        reference_group_n=table[0]["total"],
        contrast_group_n=table[3]["total"],
    )


def _operator_from_trial(row: dict | None) -> str | None:
    return ((row or {}).get("verdict") or {}).get("operator_id")


def _ordered_json_receipt(value) -> dict:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _walk_all_scalars(value, key: str | None = None):
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _walk_all_scalars(child, child_key)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_all_scalars(child, key)
    else:
        yield key, value


def _output_literal_inventory(runner, payload: dict) -> dict[str, set[str]]:
    inventory = {
        "replaceable_non_id_strings": set(),
        "enum_strings": set(),
        "identity_strings": set(),
        "non_string_scalars": set(),
        "template_keys": set(runner._walk_keys(payload)),
    }
    for key, value in _walk_all_scalars(payload):
        if not isinstance(value, str):
            inventory["non_string_scalars"].add(runner._canonical_scalar(value))
            continue
        literal_class = runner._literal_class(key, value)
        if literal_class == "replaceable_non_id":
            inventory["replaceable_non_id_strings"].add(value)
        elif literal_class == "enum":
            inventory["enum_strings"].add(value)
        elif literal_class in {"replaceable_id", "gate_bound_identity"}:
            inventory["identity_strings"].add(value)
        else:
            raise ValueError(f"unclassified output string literal: {literal_class}:{key}")
    return inventory


def _worked_example_literal_overlap(
    runner,
    missions: dict[str, dict],
    inputs: dict[str, dict],
    expected: dict[str, dict],
    gradeable_ids: set[str],
    redacted_preflight: dict,
) -> dict:
    """Execute the exact-output-literal claim for the arm's selected source examples.

    Matching is type-sensitive exact equality over JSON string values in the selected
    development example's expected output and the measured target's expected output. Enum
    strings are included in the 67/82 aggregate but itemized separately. Identity-valued
    strings, object keys, and non-string scalars are never counted toward that aggregate.
    """
    receipts = []
    seen_targets = set()
    for result in sorted(redacted_preflight["results"], key=lambda row: row["target_mission_id"]):
        target_mid = result["target_mission_id"]
        example_mid = result.get("example_mission_id")
        if target_mid in seen_targets:
            raise ValueError(f"duplicate redacted-arm target: {target_mid}")
        seen_targets.add(target_mid)
        selected = runner.pick_example(missions[target_mid], missions, gradeable_ids)
        if not example_mid or example_mid != selected:
            raise ValueError(
                f"redacted-arm example selection mismatch for {target_mid}: "
                f"preflight={example_mid!r}, recomputed={selected!r}"
            )

        example_output = expected[example_mid]["payload"]
        target_output = expected[target_mid]["payload"]
        example_inventory = _output_literal_inventory(runner, example_output)
        target_inventory = _output_literal_inventory(runner, target_output)
        shared_replaceable = sorted(
            example_inventory["replaceable_non_id_strings"]
            & target_inventory["replaceable_non_id_strings"]
        )
        shared_enums = sorted(example_inventory["enum_strings"] & target_inventory["enum_strings"])
        shared_included = sorted(set(shared_replaceable) | set(shared_enums))
        receipts.append(
            {
                "target_mission_id": target_mid,
                "example_mission_id": example_mid,
                "category": missions[target_mid]["category"],
                "source_payload_receipts": {
                    "example_input": _ordered_json_receipt(inputs[example_mid]["payload"]),
                    "example_expected_output": _ordered_json_receipt(example_output),
                    "target_input": _ordered_json_receipt(inputs[target_mid]["payload"]),
                    "target_expected_output": _ordered_json_receipt(target_output),
                },
                "shared_replaceable_non_id_output_strings": shared_replaceable,
                "shared_enum_output_strings": shared_enums,
                "shared_exact_non_id_output_strings_including_enums": shared_included,
                "excluded_shared_identity_output_strings": sorted(
                    example_inventory["identity_strings"] & target_inventory["identity_strings"]
                ),
                "excluded_shared_non_string_output_scalars": sorted(
                    example_inventory["non_string_scalars"] & target_inventory["non_string_scalars"]
                ),
                "excluded_shared_template_keys": sorted(
                    example_inventory["template_keys"] & target_inventory["template_keys"]
                ),
                "shares_any_exact_non_id_output_literal": bool(shared_included),
            }
        )

    target_ids = sorted(
        mid
        for mid in gradeable_ids
        if missions[mid]["task_snapshot"].get("split") in {"held_out", "ood"}
    )
    if sorted(seen_targets) != target_ids:
        raise ValueError("worked-example literal receipts do not cover the exact arm targets")

    matched = [
        row["target_mission_id"]
        for row in receipts
        if row["shares_any_exact_non_id_output_literal"]
    ]
    replaceable_matches = [
        row["target_mission_id"]
        for row in receipts
        if row["shared_replaceable_non_id_output_strings"]
    ]
    enum_matches = [
        row["target_mission_id"] for row in receipts if row["shared_enum_output_strings"]
    ]
    enum_only = [
        row["target_mission_id"]
        for row in receipts
        if row["shared_enum_output_strings"] and not row["shared_replaceable_non_id_output_strings"]
    ]
    return {
        "claim": (
            "the selected worked example shares at least one exact non-ID output literal "
            "with 67 of 82 measurement missions"
        ),
        "policy": {
            "selection": (
                "run_missions.pick_example: first sorted gradeable development mission in "
                "the target category; exactly the selection recorded by redacted-arm preflight"
            ),
            "comparison": (
                "type-sensitive exact equality of JSON string scalar values between selected "
                "example expected-output payload and target expected-output payload"
            ),
            "included": ["replaceable_non_id_string", "enum_string"],
            "enum_treatment": "included in aggregate and itemized separately",
            "excluded": {
                "identity_strings": "excluded and itemized separately",
                "template_keys": "object keys are not literal values; excluded and itemized",
                "non_string_scalars": "numbers, booleans, and null excluded and itemized",
            },
            "normalization": "none; exact Unicode code-point and case-sensitive equality",
        },
        "source_binding": {
            "example_and_target_inputs": "benchmark/support_backoffice/v1/fixtures/inputs.jsonl",
            "example_and_target_expected_outputs": (
                "benchmark/support_backoffice/v1/fixtures/expected_outputs.jsonl"
            ),
            "file_hashes": "bound in top-level input_files and input_set_digest",
            "per_payload_hash": "ordered compact UTF-8 JSON sha256 in every mission receipt",
        },
        "aggregate": {
            "measured_missions": len(receipts),
            "missions_with_any_exact_non_id_output_literal": len(matched),
            "mission_ids_with_any_exact_non_id_output_literal": matched,
            "missions_without_any_exact_non_id_output_literal": len(receipts) - len(matched),
            "mission_ids_without_any_exact_non_id_output_literal": sorted(
                set(target_ids) - set(matched)
            ),
            "missions_with_replaceable_non_id_output_string": len(replaceable_matches),
            "missions_with_enum_output_string": len(enum_matches),
            "missions_with_enum_output_string_only": len(enum_only),
        },
        "per_mission_receipts": receipts,
    }


def _input_receipts(root: Path) -> tuple[list[dict], str]:
    paths = [
        *sorted((root / "data" / "trials").glob("*.jsonl")),
        *sorted((root / "data" / "scoring" / "full").glob("*.jsonl")),
        root / "benchmark" / "support_backoffice" / "v1" / "effective_candidate_bindings.csv",
        root / "benchmark" / "support_backoffice" / "v1" / "fixtures" / "inputs.jsonl",
        root / "benchmark" / "support_backoffice" / "v1" / "fixtures" / "expected_outputs.jsonl",
        *sorted((root / "benchmark" / "support_backoffice" / "v1" / "missions").glob("*.jsonl")),
        root / "scripts" / "run_missions.py",
        root / "scripts" / "semantic_match.py",
        root / "scripts" / "freeze_layer_two.py",
        root / "src" / "workforce_graph" / "evidence" / "task4_phase2b_operators.py",
        root / "src" / "workforce_graph" / "evidence" / "task4_phase2b_profiles.py",
    ]
    receipts = [file_receipt(path, base=root) for path in paths]
    digest = hashlib.sha256(
        json.dumps(receipts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return receipts, digest


def build_freeze(root: Path = ROOT) -> dict:
    suite = root / "benchmark" / "support_backoffice" / "v1"
    trial_path = root / "data" / "trials" / PRIMARY_TRIAL
    bindings_path = suite / "effective_candidate_bindings.csv"
    expected_path = suite / "fixtures" / "expected_outputs.jsonl"

    trials, trial_selection = _legacy_latest_primary(trial_path)
    votes, vote_selection = _load_votes(root / "data" / "scoring" / "full")
    bindings = list(csv.DictReader(bindings_path.open(encoding="utf-8")))
    expected = {row["mission_id"]: row["payload"] for row in _load_jsonl(expected_path)}
    semantic = _load_semantic_module(root)
    runner = _load_run_missions_module(root)
    operators, ungradeable = _load_operator_lookup(root, [row["mission_id"] for row in bindings])
    ungradeable_set = set(ungradeable)
    runner_missions, runner_inputs, runner_expected = runner.load_suite()
    runner_gradeable, _ = runner.gradeable(runner_missions)
    redacted_preflight = runner.preflight_redacted_arm(
        runner_missions, runner_inputs, runner_expected, set(runner_gradeable)
    )["report"]
    worked_example_literal_overlap = _worked_example_literal_overlap(
        runner,
        runner_missions,
        runner_inputs,
        runner_expected,
        set(runner_gradeable),
        redacted_preflight,
    )

    mission_rows = []
    exclusion_rosters: dict[str, list[str]] = collections.defaultdict(list)
    for binding in sorted(bindings, key=lambda row: row["mission_id"]):
        mid = binding["mission_id"]
        trial = trials.get(mid)
        activity_votes = votes.get(binding["activity_id"], {})
        split = binding.get("proposed_split")
        all_reasons = []
        if split == "development":
            all_reasons.append("development_split")
        if mid in ungradeable_set:
            all_reasons.append("no_semantic_operator")
        if trial is None and not all_reasons:
            all_reasons.append("missing_primary_trial_unexplained")

        if trial is not None:
            primary_exclusion = None
        elif mid in ungradeable_set:
            primary_exclusion = "no_semantic_operator"
        elif split == "development":
            primary_exclusion = "development_split"
        else:
            primary_exclusion = "missing_primary_trial_unexplained"
        if primary_exclusion:
            exclusion_rosters[primary_exclusion].append(mid)

        byte_outcome = None
        semantic_legacy_outcome = None
        semantic_hardened_outcome = None
        semantic_legacy_detail = None
        semantic_hardened_detail = None
        if trial is not None:
            raw_byte = (trial.get("verdict") or {}).get("conformant")
            byte_outcome = raw_byte if isinstance(raw_byte, bool) else None
            semantic_legacy_detail = semantic.compare_legacy(
                expected[mid], trial.get("deliverable")
            )
            semantic_hardened_detail = semantic.compare(expected[mid], trial.get("deliverable"))
            semantic_legacy_outcome = semantic_legacy_detail["matched"]
            semantic_hardened_outcome = semantic_hardened_detail["matched"]

        doses = {
            predictor: _endorsements(activity_votes, predictor)
            for predictor in ("can_do", "no_human_review", "requires_tool_access")
        }
        mission_rows.append(
            {
                "mission_id": mid,
                "category": binding["category"],
                "activity_id": binding["activity_id"],
                "split": split,
                "operator_id": operators.get(mid) or _operator_from_trial(trial),
                "primary_measured": trial is not None,
                "primary_exclusion_reason": primary_exclusion,
                "all_exclusion_reasons": all_reasons,
                "vote_count": len(activity_votes),
                "complete_vote_join": len(activity_votes) == 3,
                "vote_doses": doses,
                "requires_tool_access_any_endorsement": (
                    doses["requires_tool_access"] > 0
                    if doses["requires_tool_access"] is not None
                    else None
                ),
                "trial_receipt": (
                    {
                        "model_id": trial.get("model_id"),
                        "backend": trial.get("backend"),
                        "status": trial.get("status"),
                        "checker_version": (trial.get("verdict") or {}).get("checker_version"),
                        "run_spec": trial.get("run_spec", PRIMARY_RUN_SPEC),
                        "rendered_prompt_hash": trial.get("rendered_prompt_hash"),
                    }
                    if trial
                    else None
                ),
                "outcomes": {
                    "byte_suite_checker": byte_outcome,
                    "semantic_legacy": semantic_legacy_outcome,
                    "semantic_hardened": semantic_hardened_outcome,
                },
                "semantic_legacy_detail": semantic_legacy_detail,
                "semantic_hardened_detail": semantic_hardened_detail,
            }
        )

    measured = [row for row in mission_rows if row["primary_measured"]]
    answered = [
        row
        for row in measured
        if isinstance(row["outcomes"]["byte_suite_checker"], bool)
        and isinstance(row["outcomes"]["semantic_legacy"], bool)
        and isinstance(row["outcomes"]["semantic_hardened"], bool)
    ]
    complete = [row for row in answered if row["complete_vote_join"]]

    outcomes = {}
    for name in ("byte_suite_checker", "semantic_legacy", "semantic_hardened"):
        all_summary = _summary([row["outcomes"][name] for row in answered])
        complete_summary = _summary([row["outcomes"][name] for row in complete])
        dose_tables = {
            predictor: _dose_table(complete, predictor, name)
            for predictor in ("no_human_review", "can_do", "requires_tool_access")
        }
        outcomes[name] = {
            "definition": (
                "stored suite/domain-checker deterministic conformance"
                if name == "byte_suite_checker"
                else (
                    "historical pre-repair comparator reproduction; not current grading policy"
                    if name == "semantic_legacy"
                    else "hardened agreement on compared decisions and memberships; exempt prose unverified"
                )
            ),
            "all_answered": all_summary,
            "failed_mission_ids_all_answered": sorted(
                row["mission_id"] for row in answered if not row["outcomes"][name]
            ),
            "complete_vote_join": complete_summary,
            "failed_mission_ids_complete_vote_join": sorted(
                row["mission_id"] for row in complete if not row["outcomes"][name]
            ),
            "dose_tables_complete_vote_join": dose_tables,
        }
        if name != "semantic_legacy":
            outcomes[name]["power_calculations"] = {
                predictor: _power_from_table(complete_summary, dose_tables[predictor])
                for predictor in ("no_human_review", "can_do")
            }
        else:
            outcomes[name]["power_calculations"] = None
            outcomes[name]["inference_status"] = (
                "historical reproduction only; association/power uses semantic_hardened"
            )

    selection_tables = {}
    complete_bound = [row for row in mission_rows if row["complete_vote_join"]]
    for predictor in ("no_human_review", "can_do", "requires_tool_access"):
        selection_tables[predictor] = [
            {
                "dose": dose,
                "measured": sum(
                    row["vote_doses"][predictor] == dose and row["primary_measured"]
                    for row in complete_bound
                ),
                "excluded": sum(
                    row["vote_doses"][predictor] == dose and not row["primary_measured"]
                    for row in complete_bound
                ),
            }
            for dose in range(4)
        ]

    category_rows = []
    for category in sorted({row["category"] for row in mission_rows}):
        rows = [row for row in mission_rows if row["category"] == category]
        category_rows.append(
            {
                "category": category,
                "operator_ids": sorted({row["operator_id"] for row in rows if row["operator_id"]}),
                "bound": len(rows),
                "measured": sum(row["primary_measured"] for row in rows),
                "excluded": sum(not row["primary_measured"] for row in rows),
                "complete_votes": sum(row["complete_vote_join"] for row in rows),
                "measured_complete_votes": sum(
                    row["primary_measured"] and row["complete_vote_join"] for row in rows
                ),
                "byte_failures_complete": sum(
                    row["primary_measured"]
                    and row["complete_vote_join"]
                    and row["outcomes"]["byte_suite_checker"] is False
                    for row in rows
                ),
                "semantic_failures_complete": sum(
                    row["primary_measured"]
                    and row["complete_vote_join"]
                    and row["outcomes"]["semantic_hardened"] is False
                    for row in rows
                ),
            }
        )

    latest_backends = [row["trial_receipt"] for row in measured if row["trial_receipt"]]
    backend_received = [row for row in latest_backends if row.get("backend")]
    backend_match = [
        row for row in backend_received if row["backend"].rsplit("/", 1)[-1] == row.get("model_id")
    ]
    scoring_vote_rows = [row for activity in votes.values() for row in activity.values()]
    scoring_backend_receipts = sum(
        bool(row.get("backend") or row.get("served_backend") or row.get("_routed_via"))
        for row in scoring_vote_rows
    )

    input_receipts, input_set_digest = _input_receipts(root)
    expected_checks = {
        "byte_all_answered_69_of_82": outcomes["byte_suite_checker"]["all_answered"]
        == {"passed": 69, "failed": 13, "total": 82},
        "semantic_legacy_all_answered_78_of_82": outcomes["semantic_legacy"]["all_answered"]
        == {"passed": 78, "failed": 4, "total": 82},
        "byte_complete_67_of_78": outcomes["byte_suite_checker"]["complete_vote_join"]
        == {"passed": 67, "failed": 11, "total": 78},
        "semantic_legacy_complete_75_of_78": outcomes["semantic_legacy"]["complete_vote_join"]
        == {"passed": 75, "failed": 3, "total": 78},
        "worked_example_exact_non_id_output_literal_67_of_82": (
            worked_example_literal_overlap["aggregate"][
                "missions_with_any_exact_non_id_output_literal"
            ]
            == 67
            and worked_example_literal_overlap["aggregate"]["measured_missions"] == 82
        ),
    }

    semantic_changes = []
    for row in measured:
        legacy = row["outcomes"]["semantic_legacy"]
        hardened = row["outcomes"]["semantic_hardened"]
        if legacy != hardened:
            detail = row["semantic_hardened_detail"]
            semantic_changes.append(
                {
                    "mission_id": row["mission_id"],
                    "semantic_legacy": legacy,
                    "semantic_hardened": hardened,
                    "hardened_reasons": {
                        "mismatched": detail.get("mismatched", []),
                        "missing": detail.get("missing", []),
                        "extra_decision_fields": detail.get("extra_decision_fields", []),
                        "membership_mismatches": detail.get("membership_mismatches", []),
                    },
                }
            )
    semantic_counts_changed = (
        outcomes["semantic_legacy"]["all_answered"] != outcomes["semantic_hardened"]["all_answered"]
        or outcomes["semantic_legacy"]["complete_vote_join"]
        != outcomes["semantic_hardened"]["complete_vote_join"]
    )

    tool_doses = collections.Counter(
        row["vote_doses"]["requires_tool_access"]
        for row in complete
        if row["vote_doses"]["requires_tool_access"] is not None
    )
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "deterministic": True,
        "input_files": input_receipts,
        "input_set_digest": input_set_digest,
        "selection": {
            "primary_trial": trial_selection,
            "vote_files": vote_selection,
            "bound_missions": len(mission_rows),
            "primary_measured_missions": len(measured),
            "answered_on_both_outcomes": len(answered),
            "complete_vote_join": len(complete),
            "complete_vote_join_exclusions_from_primary": {
                "count": sum(not row["complete_vote_join"] for row in answered),
                "mission_ids": sorted(
                    row["mission_id"] for row in answered if not row["complete_vote_join"]
                ),
                "reason": "fewer_than_three_predictor_vote_rows",
            },
            "incomplete_vote_bindings_all_120": {
                "count": sum(not row["complete_vote_join"] for row in mission_rows),
                "mission_ids": sorted(
                    row["mission_id"] for row in mission_rows if not row["complete_vote_join"]
                ),
            },
            "exclusions_by_primary_reason": {
                reason: {"count": len(ids), "mission_ids": sorted(ids)}
                for reason, ids in sorted(exclusion_rosters.items())
            },
            "all_reason_counts_nonexclusive": dict(
                sorted(
                    collections.Counter(
                        reason for row in mission_rows for reason in row["all_exclusion_reasons"]
                    ).items()
                )
            ),
            "dose_x_measured_excluded_complete_votes": selection_tables,
            "category_operator_confound": {
                "table": category_rows,
                "interpretation": (
                    "measurement selection and failures vary jointly with category/operator; "
                    "these rows do not identify an operator-independent effect"
                ),
            },
        },
        "outcomes": outcomes,
        "semantic_transition": {
            "legacy_status": "historical_reproduction_not_current_grading_policy",
            "hardened_status": "current_comparator_policy",
            "counts_changed": semantic_counts_changed,
            "legacy_numbers_superseded": semantic_counts_changed,
            "changed_verdict_count": len(semantic_changes),
            "changed_verdicts": semantic_changes,
            "association_and_power_outcome": "semantic_hardened",
        },
        "requires_tool_access_mismatch": {
            "measured_arm_has_tool_access": False,
            "complete_measured_missions_by_endorsement_dose": {
                str(dose): tool_doses.get(dose, 0) for dose in range(4)
            },
            "complete_measured_missions_with_any_endorsement": sum(
                count for dose, count in tool_doses.items() if dose > 0
            ),
            "complete_measured_missions_with_unanimous_endorsement": tool_doses.get(3, 0),
            "construct_mismatch": any(dose > 0 and count for dose, count in tool_doses.items()),
        },
        "served_backend_receipt_assertion": {
            "measurement_trials": {
                "latest_records": len(latest_backends),
                "receipts_present": len(backend_received),
                "receipts_match_requested_model": len(backend_match),
                "all_present_and_matching": len(backend_match) == len(latest_backends),
                "unique_backend_receipts": sorted({row["backend"] for row in backend_received}),
                "scope": "router receipt stored in trial row; not independent backend attestation",
            },
            "predictor_vote_rows": {
                "rows": len(scoring_vote_rows),
                "served_backend_receipts_present": scoring_backend_receipts,
                "served_backend_verified": scoring_backend_receipts == len(scoring_vote_rows),
            },
        },
        "prompt_receipt_assertion": {
            "primary_latest_records": len(measured),
            "rendered_prompt_hashes_present": sum(
                bool(row["trial_receipt"].get("rendered_prompt_hash")) for row in measured
            ),
            "exact_historical_prompt_bytes_verified": all(
                row["trial_receipt"].get("rendered_prompt_hash") for row in measured
            ),
            "finding": (
                "legacy primary trials predate rendered prompt hashes and run_spec; current "
                "source hashes cannot retroactively prove the historical prompt bytes"
            ),
        },
        "reported_number_checks": {
            **expected_checks,
            "all_match": all(expected_checks.values()),
            "policy": "comparison only; observed outcomes are never adjusted to match prose",
        },
        "semantic_comparator_calibration": {
            "mutations": semantic.mutation_calibration(expected),
            "cross_mission": semantic.cross_mission_calibration(expected),
            "coverage": semantic.coverage_report(expected),
        },
        "redacted_arm_preflight": redacted_preflight,
        "worked_example_literal_overlap": worked_example_literal_overlap,
        "missions": mission_rows,
        "claim_ceiling": {
            "primary_outcome": "not_selected",
            "suite_checker": "necessary deterministic conformance, not mission success",
            "semantic_hardened": (
                "compared decisions and memberships only; exempt prose and human holistic review unverified"
            ),
            "semantic_legacy": "historical reproduction only; not a current grading claim",
            "association": (
                "outcome-specific ceiling diagnostics do not establish predictive validity or no association"
            ),
            "tool_access": "one-turn no-tool arm cannot test tool-requiring capability",
            "redacted_arm": runner.REDACTION_DIAGNOSTIC_CEILING,
            "historical_arm_pair": (
                "paired historical diagnostic, not causal unless model snapshot, system prompt, "
                "decoding, and endpoint are held fixed"
            ),
        },
    }
    return artifact


@click.command()
@click.option("--root", "root_path", type=click.Path(path_type=Path), default=ROOT)
@click.option("--output", "output_path", type=click.Path(path_type=Path), default=OUTPUT)
@click.option(
    "--check", is_flag=True, help="Fail if the tracked artifact differs from a fresh render."
)
def main(root_path: Path, output_path: Path, check: bool) -> None:
    artifact = build_freeze(root_path.resolve())
    rendered = _canonical_bytes(artifact)
    if check:
        if not output_path.exists() or output_path.read_bytes() != rendered:
            raise click.ClickException(f"{output_path} is missing or stale")
        click.echo(f"PASS byte-identical: {output_path}")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(rendered)
        click.echo(f"wrote {output_path} ({len(rendered)} bytes)")
    checks = artifact["reported_number_checks"]
    click.echo(f"reported number checks: {checks}")
    if not checks["all_match"]:
        click.echo(
            "WARNING: observed numbers differ from the prose references; nothing was adjusted"
        )


if __name__ == "__main__":
    main()
