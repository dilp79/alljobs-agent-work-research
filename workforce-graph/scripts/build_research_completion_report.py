"""Build the fail-closed, evidence-bound AllJobs research completion report.

The report is intentionally unavailable while any research-complete gate fails. Use
``--preflight`` during collection; it validates every supplied artifact but never writes.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import click

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
REPORT_SCHEMA = "alljobs.research-completion-report/v1"
SNAPSHOT_SCHEMA = "alljobs.work-mode-snapshot/v1"
CORRECTED_SCHEMA = "alljobs.work-mode-corrected-result/v1"
TRANSITION_SCHEMA = "alljobs.work-mode-transition-audit/v1"
LAYER_TWO_SCHEMA = "alljobs.layer-two-freeze.v1"
EVIDENCE_SCHEMA = "evidence/1"
RLI_SCHEMA = "alljobs.rli.ordered-tsv-canonical.v1"
HH_SCHEMA = "alljobs.content27.hh-logical-slice.v1"
EXPECTED_CORPUS = 18_796
EXPECTED_THIRD_RATER = "gemini-3.5-flash-lite"
EXPLICIT_NONRESPONSE_STATUS = "complete_with_explicit_nonresponse"
NONRESPONSE_CLAIM_CEILING = (
    "no valid third-rater label after exact-route attempts; per-attempt content outcome and "
    "provider-side cause are not established"
)
EXPECTED_COMPONENTS = {
    "missingness_partial_identification",
    "sampling_answered_attempts",
    "directional_not_triple_rated_forced_contested",
    "arm_transport",
}


class ReportInputError(ValueError):
    """One or more inputs cannot support a research-complete report."""


@dataclass(frozen=True)
class ReportPaths:
    baseline: Path
    final_snapshot: Path
    corrected: Path
    layer_two: Path
    evidence_registry: Path
    rli_authority: Path
    hh_witness: Path
    external_audit: Path

    def items(self) -> tuple[tuple[str, Path], ...]:
        return (
            ("work_mode_baseline", self.baseline),
            ("work_mode_final", self.final_snapshot),
            ("work_mode_corrected", self.corrected),
            ("layer_two_freeze", self.layer_two),
            ("evidence_registry", self.evidence_registry),
            ("rli_authority", self.rli_authority),
            ("hh_logical_witness", self.hh_witness),
            ("computer_use_evidence_audit", self.external_audit),
        )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _payload_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def _command_path(path: Path) -> str:
    return os.path.relpath(path.resolve(), ROOT.resolve())


def _load_object(path: Path, role: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportInputError(f"{role}: cannot load JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportInputError(f"{role}: top-level JSON must be an object")
    return value


def _check(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _embedded_hash_ok(value: dict[str, Any], field: str) -> bool:
    recorded = value.get(field)
    unhashed = dict(value)
    unhashed.pop(field, None)
    return isinstance(recorded, str) and recorded == _payload_sha256(unhashed)


def _probability_range(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
        and 0.0 <= value[0] <= value[1] <= 1.0
    )


def _sum_int_values(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    values = list(value.values())
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in values):
        return None
    return sum(values)


def _outcome_counts_ok(value: object, expected_total: int) -> bool:
    if not isinstance(value, dict):
        return False
    passed, failed, total = value.get("passed"), value.get("failed"), value.get("total")
    return (
        isinstance(passed, int)
        and not isinstance(passed, bool)
        and isinstance(failed, int)
        and not isinstance(failed, bool)
        and total == expected_total
        and passed >= 0
        and failed >= 0
        and passed + failed == expected_total
    )


def _close(left: object, right: object, tolerance: float = 1e-12) -> bool:
    return (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
        and abs(float(left) - float(right)) <= tolerance
    )


def _ranges_close(left: object, right: object) -> bool:
    return (
        _probability_range(left)
        and _probability_range(right)
        and all(_close(a, b) for a, b in zip(left, right, strict=True))
    )


def _weighted_partition_ok(value: object) -> bool:
    expected = {"screen", "mixed", "physical", "unknown", "unsettled"}
    return (
        isinstance(value, dict)
        and set(value) == expected
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and 0.0 <= item <= 1.0
            for item in value.values()
        )
        and _close(sum(value.values()), 1.0)
    )


def validate_inputs(
    *,
    baseline: dict[str, Any],
    final_snapshot: dict[str, Any],
    corrected: dict[str, Any],
    layer_two: dict[str, Any],
    evidence_registry: dict[str, Any],
    rli_authority: dict[str, Any],
    hh_witness: dict[str, Any],
) -> dict[str, Any]:
    """Validate all research-complete gates and return report-ready scalar evidence."""
    failures: list[str] = []

    for name, snapshot in (("baseline", baseline), ("final snapshot", final_snapshot)):
        _check(snapshot.get("schema") == SNAPSHOT_SCHEMA, f"{name}: unsupported schema", failures)
        _check(
            _embedded_hash_ok(snapshot, "snapshot_payload_sha256"),
            f"{name}: embedded payload hash mismatch",
            failures,
        )
        activities = snapshot.get("activities")
        _check(isinstance(activities, dict), f"{name}: activities must be an object", failures)
        _check(
            isinstance(activities, dict) and len(activities) == EXPECTED_CORPUS,
            f"{name}: expected {EXPECTED_CORPUS} activities",
            failures,
        )
        partitions = snapshot.get("partition_counts", {})
        _check(
            isinstance(partitions, dict) and partitions.get("activities") == EXPECTED_CORPUS,
            f"{name}: partition denominator is not {EXPECTED_CORPUS}",
            failures,
        )

    final_status = final_snapshot.get("snapshot_status", {})
    _check(
        isinstance(final_status, dict)
        and final_status.get("third_rater") == EXPECTED_THIRD_RATER,
        f"final snapshot: third rater must be {EXPECTED_THIRD_RATER}",
        failures,
    )
    _check(
        isinstance(final_status, dict)
        and final_status.get("third_rater_collection_complete") is True,
        "final snapshot: third-rater collection is incomplete",
        failures,
    )
    third_status = final_status.get("third_rater_status") if isinstance(final_status, dict) else None
    nonresponses = (
        final_status.get("third_rater_nonresponses", [])
        if isinstance(final_status, dict)
        else []
    )
    _check(
        isinstance(nonresponses, list) and len(nonresponses) <= 1,
        "final snapshot: explicit nonresponses must be a list capped at one",
        failures,
    )
    if not isinstance(nonresponses, list):
        nonresponses = []
    if third_status == "complete":
        _check(
            final_status.get("third_rater_complete") is True and not nonresponses,
            "final snapshot: complete status disagrees with label/nonresponse receipt",
            failures,
        )
    elif third_status == EXPLICIT_NONRESPONSE_STATUS:
        _check(
            final_status.get("third_rater_complete") is False and len(nonresponses) == 1,
            "final snapshot: explicit-nonresponse completion receipt is inconsistent",
            failures,
        )
    else:
        _check(False, "final snapshot: third-rater collection status is unsupported", failures)

    nonresponse_ids: set[str] = set()
    for proof in nonresponses:
        activity_id = proof.get("activity_id") if isinstance(proof, dict) else None
        valid_proof = (
            isinstance(proof, dict)
            and isinstance(activity_id, str)
            and bool(activity_id)
            and isinstance(proof.get("cache_busted_record_count"), int)
            and proof["cache_busted_record_count"] >= 5
            and isinstance(proof.get("attempt_receipt_count"), int)
            and proof["attempt_receipt_count"] >= 20
            and proof["attempt_receipt_count"] >= 4 * proof["cache_busted_record_count"]
            and isinstance(proof.get("prompt_hash"), str)
            and bool(proof["prompt_hash"])
            and isinstance(proof.get("requested_model_id"), str)
            and proof.get("served_backend") == f"openrouter/{proof.get('requested_model_id')}"
            and proof.get("status") == "exact_route_no_valid_label"
            and proof.get("terminal_none_record_count")
            == proof.get("cache_busted_record_count")
            and proof.get("claim_ceiling") == NONRESPONSE_CLAIM_CEILING
        )
        _check(valid_proof, f"final snapshot: invalid nonresponse proof for {activity_id}", failures)
        if isinstance(activity_id, str):
            nonresponse_ids.add(activity_id)
    _check(
        len(nonresponse_ids) == len(nonresponses),
        "final snapshot: explicit nonresponse IDs are missing or duplicated",
        failures,
    )
    if isinstance(final_status, dict) and final_status.get("third_rater_collection_complete") is True:
        _check(
            final_status.get("completion_baseline_payload_sha256")
            == baseline.get("snapshot_payload_sha256"),
            "final snapshot: completion baseline hash is not bound",
            failures,
        )
    third_inputs = [
        row
        for row in final_snapshot.get("inputs", [])
        if isinstance(row, dict)
        and row.get("role") == "bulk_label"
        and row.get("identity") == EXPECTED_THIRD_RATER
    ]
    _check(len(third_inputs) == 1, "final snapshot: third-rater input receipt is not unique", failures)
    expected_third_readings = EXPECTED_CORPUS - len(nonresponse_ids)
    if len(third_inputs) == 1:
        _check(
            third_inputs[0].get("unique_successful_labels") == expected_third_readings,
            "final snapshot: third-rater unique-label count disagrees with nonresponses",
            failures,
        )
    final_activities = final_snapshot.get("activities", {})
    third_readings = (
        sum(
            isinstance(row, dict)
            and row.get("readings", {}).get(EXPECTED_THIRD_RATER)
            in {"screen", "mixed", "physical"}
            for row in final_activities.values()
        )
        if isinstance(final_activities, dict)
        else 0
    )
    _check(
        third_readings == expected_third_readings,
        "final snapshot: successful third-rater readings disagree with nonresponses",
        failures,
    )
    if isinstance(final_activities, dict):
        missing_third_readings = {
            activity_id
            for activity_id, row in final_activities.items()
            if not isinstance(row, dict)
            or row.get("readings", {}).get(EXPECTED_THIRD_RATER)
            not in {"screen", "mixed", "physical"}
        }
        _check(
            missing_third_readings == nonresponse_ids,
            "final snapshot: missing third-rater readings differ from explicit nonresponses",
            failures,
        )
        for activity_id in nonresponse_ids:
            row = final_activities.get(activity_id)
            _check(
                isinstance(row, dict)
                and row.get("label") is None
                and row.get("label_source") == "third_rater_explicit_nonresponse"
                and row.get("settlement") == "unsettled",
                f"final snapshot: nonresponse {activity_id} was imputed or settled",
                failures,
            )

    final_partitions = final_snapshot.get("partition_counts", {})
    settlement = final_partitions.get("settlement", {}) if isinstance(final_partitions, dict) else {}
    settled = settlement.get("settled") if isinstance(settlement, dict) else None
    unsettled = settlement.get("unsettled") if isinstance(settlement, dict) else None
    _check(
        isinstance(settled, int)
        and isinstance(unsettled, int)
        and settled + unsettled == EXPECTED_CORPUS,
        "final snapshot: settlement counts do not sum to the corpus",
        failures,
    )
    for partition_name in ("stratum", "n_raters", "label", "label_source"):
        _check(
            _sum_int_values(final_partitions.get(partition_name)) == EXPECTED_CORPUS,
            f"final snapshot: {partition_name} counts do not sum to the corpus",
            failures,
        )

    _check(corrected.get("schema") == CORRECTED_SCHEMA, "corrected result: unsupported schema", failures)
    _check(
        _embedded_hash_ok(corrected, "result_payload_sha256"),
        "corrected result: embedded payload hash mismatch",
        failures,
    )
    _check(
        corrected.get("state_snapshot_payload_sha256")
        == final_snapshot.get("snapshot_payload_sha256"),
        "corrected result: final snapshot hash is not bound",
        failures,
    )
    _check(
        corrected.get("state_snapshot_status") == final_status,
        "corrected result: snapshot status differs from the frozen final snapshot",
        failures,
    )
    _check(corrected.get("corpus_size") == EXPECTED_CORPUS, "corrected result: bad corpus size", failures)
    _check(
        isinstance(settled, int) and corrected.get("settled_labels") == settled,
        "corrected result: settled denominator differs from the final snapshot",
        failures,
    )
    _check(
        _probability_range(corrected.get("digital_share_strict")),
        "corrected result: strict range is not an ordered probability interval",
        failures,
    )
    _check(
        _probability_range(corrected.get("digital_share_generous")),
        "corrected result: generous range is not an ordered probability interval",
        failures,
    )
    range_kind = corrected.get("range_kind", "")
    _check(
        isinstance(range_kind, str)
        and "partial-identification" in range_kind
        and "not a confidence interval" in range_kind,
        "corrected result: missing partial-identification and no-CI ceiling",
        failures,
    )
    _check(
        corrected.get("coverage_ceiling") == "none; deterministic extrema conditional on inputs and mapping",
        "corrected result: unexpected headline coverage ceiling",
        failures,
    )
    components = corrected.get("components", {})
    _check(
        isinstance(components, dict) and set(components) == EXPECTED_COMPONENTS,
        "corrected result: uncertainty component set drifted",
        failures,
    )
    missingness = (
        components.get("missingness_partial_identification", {})
        if isinstance(components, dict)
        else {}
    )
    _check(
        isinstance(missingness, dict)
        and missingness.get("range_kind")
        == "partial-identification bounds for unanswered experiment attempts; not a confidence interval"
        and missingness.get("coverage_ceiling") == "none; no stochastic coverage claim"
        and _ranges_close(missingness.get("digital_share_strict"), corrected.get("digital_share_strict"))
        and _ranges_close(
            missingness.get("digital_share_generous"), corrected.get("digital_share_generous")
        ),
        "corrected result: missingness component does not bind the headline ranges",
        failures,
    )
    expected_rate_cells = {
        f"{stratum}/{mode}"
        for stratum in ("contested", "control")
        for mode in ("screen", "mixed", "physical")
    }
    missing_low = missingness.get("decline_rates_low", {}) if isinstance(missingness, dict) else {}
    missing_high = (
        missingness.get("decline_rates_high", {}) if isinstance(missingness, dict) else {}
    )
    _check(
        isinstance(missing_low, dict)
        and isinstance(missing_high, dict)
        and set(missing_low) == expected_rate_cells
        and set(missing_high) == expected_rate_cells
        and all(
            isinstance(missing_low[key], (int, float))
            and not isinstance(missing_low[key], bool)
            and isinstance(missing_high[key], (int, float))
            and not isinstance(missing_high[key], bool)
            and 0.0 <= missing_low[key] <= missing_high[key] <= 1.0
            for key in expected_rate_cells
        ),
        "corrected result: missingness decline-rate cells are incomplete or unordered",
        failures,
    )
    weighted = corrected.get("weighted_after_correction", {})
    weighted_low = weighted.get("low", {}) if isinstance(weighted, dict) else {}
    weighted_high = weighted.get("high", {}) if isinstance(weighted, dict) else {}
    _check(
        _weighted_partition_ok(weighted_low) and _weighted_partition_ok(weighted_high),
        "corrected result: weighted partitions do not form probability mass",
        failures,
    )
    if _weighted_partition_ok(weighted_high):
        derived_strict = [
            weighted_high["screen"],
            weighted_high["screen"] + weighted_high["unknown"] + weighted_high["unsettled"],
        ]
        derived_generous = [
            weighted_high["screen"] + weighted_high["mixed"],
            weighted_high["screen"]
            + weighted_high["mixed"]
            + weighted_high["unknown"]
            + weighted_high["unsettled"],
        ]
        _check(
            _ranges_close(derived_strict, corrected.get("digital_share_strict"))
            and _ranges_close(derived_generous, corrected.get("digital_share_generous")),
            "corrected result: headline endpoints do not reproduce from weighted extrema",
            failures,
        )
    sampling_component = (
        components.get("sampling_answered_attempts", {}) if isinstance(components, dict) else {}
    )
    _check(
        isinstance(sampling_component, dict)
        and sampling_component.get("method") == "two-sided Wilson score interval"
        and _probability_range(sampling_component.get("digital_share_strict"))
        and _probability_range(sampling_component.get("digital_share_generous"))
        and "no simultaneous/headline coverage claim"
        in sampling_component.get("coverage_ceiling", ""),
        "corrected result: sampling component is incomplete or overclaims coverage",
        failures,
    )
    directional_component = (
        components.get("directional_not_triple_rated_forced_contested", {})
        if isinstance(components, dict)
        else {}
    )
    directional_base = (
        directional_component.get("base", {}) if isinstance(directional_component, dict) else {}
    )
    expected_not_triple_rated = (
        sum(
            isinstance(row, dict)
            and isinstance(row.get("n_raters"), int)
            and row["n_raters"] < 3
            for row in final_activities.values()
        )
        if isinstance(final_activities, dict)
        else -1
    )
    _check(
        isinstance(directional_base, dict)
        and directional_component.get("all_not_triple_rated_activities")
        == expected_not_triple_rated
        and _ranges_close(
            directional_base.get("digital_share_strict"), corrected.get("digital_share_strict")
        )
        and _ranges_close(
            directional_base.get("digital_share_generous"),
            corrected.get("digital_share_generous"),
        ),
        "corrected result: directional count/base does not bind the final snapshot and headline ranges",
        failures,
    )
    arm_component = components.get("arm_transport", {}) if isinstance(components, dict) else {}
    arm_effect = (
        arm_component.get("employment_weighted_material_effect", {})
        if isinstance(arm_component, dict)
        else {}
    )
    historical_arm = (
        arm_effect.get("historical_arm_policy", {}) if isinstance(arm_effect, dict) else {}
    )
    _check(
        corrected.get("experiment_arm_policy") == "historical"
        and isinstance(historical_arm, dict)
        and _ranges_close(
            historical_arm.get("digital_share_strict"), corrected.get("digital_share_strict")
        )
        and _ranges_close(
            historical_arm.get("digital_share_generous"), corrected.get("digital_share_generous")
        ),
        "corrected result: selected arm policy does not bind the headline ranges",
        failures,
    )
    _check(
        corrected.get("incomplete") == (isinstance(unsettled, int) and unsettled > 0),
        "corrected result: incomplete flag disagrees with unsettled activity mass",
        failures,
    )
    experiment_binding = corrected.get("experiment_input_binding", {})
    _check(
        isinstance(experiment_binding, dict) and experiment_binding.get("binding_verified") is True,
        "corrected result: experiment input is not hash-bound",
        failures,
    )
    route_receipt = corrected.get("route_receipt", {})
    _check(
        isinstance(route_receipt, dict)
        and route_receipt.get("route_guard_passed") is True
        and route_receipt.get("requested_rater") == corrected.get("rater_of_the_experiment"),
        "corrected result: requested-route guard did not pass",
        failures,
    )

    transition = corrected.get("transition_audit", {})
    _check(
        isinstance(transition, dict) and transition.get("schema") == TRANSITION_SCHEMA,
        "transition audit: unsupported or missing schema",
        failures,
    )
    _check(
        isinstance(transition, dict) and _embedded_hash_ok(transition, "audit_payload_sha256"),
        "transition audit: embedded payload hash mismatch",
        failures,
    )
    _check(
        isinstance(transition, dict)
        and transition.get("baseline_snapshot_payload_sha256")
        == baseline.get("snapshot_payload_sha256"),
        "transition audit: baseline hash is not bound",
        failures,
    )
    _check(
        isinstance(transition, dict)
        and transition.get("final_snapshot_payload_sha256")
        == final_snapshot.get("snapshot_payload_sha256"),
        "transition audit: final hash is not bound",
        failures,
    )
    inventory = transition.get("activity_inventory", {}) if isinstance(transition, dict) else {}
    _check(
        isinstance(inventory, dict)
        and inventory.get("baseline") == EXPECTED_CORPUS
        and inventory.get("final") == EXPECTED_CORPUS
        and inventory.get("common") == EXPECTED_CORPUS
        and inventory.get("added") == []
        and inventory.get("removed") == [],
        "transition audit: activity inventory changed",
        failures,
    )

    _check(
        layer_two.get("schema_version") == LAYER_TWO_SCHEMA,
        "layer two: unsupported schema",
        failures,
    )
    selection = layer_two.get("selection", {})
    _check(
        isinstance(selection, dict)
        and selection.get("bound_missions") == 120
        and selection.get("primary_measured_missions") == 82
        and selection.get("complete_vote_join") == 78,
        "layer two: denominator or selection drift",
        failures,
    )
    checks = layer_two.get("reported_number_checks", {})
    _check(
        isinstance(checks, dict) and checks.get("all_match") is True,
        "layer two: reported-number checks failed",
        failures,
    )
    claim_ceiling = layer_two.get("claim_ceiling", {})
    _check(
        isinstance(claim_ceiling, dict) and claim_ceiling.get("primary_outcome") == "not_selected",
        "layer two: a primary outcome was selected without founder authority",
        failures,
    )
    outcomes = layer_two.get("outcomes", {})
    for outcome_name in ("byte_suite_checker", "semantic_hardened"):
        outcome = outcomes.get(outcome_name, {}) if isinstance(outcomes, dict) else {}
        all_answered = outcome.get("all_answered", {}) if isinstance(outcome, dict) else {}
        complete = outcome.get("complete_vote_join", {}) if isinstance(outcome, dict) else {}
        _check(
            _outcome_counts_ok(all_answered, 82),
            f"layer two: {outcome_name} all-answered denominator drift",
            failures,
        )
        _check(
            _outcome_counts_ok(complete, 78),
            f"layer two: {outcome_name} complete-vote denominator drift",
            failures,
        )
    tool_mismatch = layer_two.get("requires_tool_access_mismatch", {})
    _check(
        isinstance(tool_mismatch, dict) and tool_mismatch.get("construct_mismatch") is True,
        "layer two: tool-access construct mismatch disappeared",
        failures,
    )
    prompt_receipt = layer_two.get("prompt_receipt_assertion", {})
    _check(
        isinstance(prompt_receipt, dict)
        and prompt_receipt.get("exact_historical_prompt_bytes_verified") is False,
        "layer two: historical prompt-byte ceiling drift",
        failures,
    )
    backend_receipt = layer_two.get("served_backend_receipt_assertion", {})
    predictor_receipt = (
        backend_receipt.get("predictor_vote_rows", {}) if isinstance(backend_receipt, dict) else {}
    )
    _check(
        isinstance(predictor_receipt, dict)
        and predictor_receipt.get("served_backend_verified") is False,
        "layer two: predictor backend receipt ceiling drift",
        failures,
    )
    redacted = layer_two.get("redacted_arm_preflight", {})
    _check(
        isinstance(redacted, dict)
        and redacted.get("decision") == "HOLD"
        and redacted.get("evaluated_targets") == 82
        and redacted.get("failed_targets") == 82,
        "layer two: redacted-arm HOLD gate drift",
        failures,
    )
    overlap = layer_two.get("worked_example_literal_overlap", {})
    overlap_aggregate = overlap.get("aggregate", {}) if isinstance(overlap, dict) else {}
    _check(
        isinstance(overlap_aggregate, dict)
        and overlap_aggregate.get("measured_missions") == 82
        and overlap_aggregate.get("missions_with_any_exact_non_id_output_literal") == 67,
        "layer two: worked-example literal-overlap diagnostic drift",
        failures,
    )

    _check(
        evidence_registry.get("schema_version") == EVIDENCE_SCHEMA,
        "evidence registry: unsupported schema",
        failures,
    )
    _check(
        evidence_registry.get("edges_authorising_a_bound") == 0,
        "evidence registry: an external edge now authorises a bound and needs review",
        failures,
    )
    profiles = evidence_registry.get("profiles", [])
    profile_counts = evidence_registry.get("profile_counts", {})
    _check(
        isinstance(profiles, list)
        and len(profiles) == 8
        and isinstance(profile_counts, dict)
        and profile_counts.get("collected_profiles") == 8
        and profile_counts.get("wired_capability_anchors") == 5
        and len(evidence_registry.get("edges", [])) == 15,
        "evidence registry: profile or edge denominator drift",
        failures,
    )
    osworld = [
        profile
        for profile in profiles
        if isinstance(profile, dict) and profile.get("id") == "osworld_v2_paper_v2"
    ]
    _check(
        len(osworld) == 1
        and osworld[0].get("granularity") == "item_level"
        and osworld[0].get("channel") == ["gui"],
        "evidence registry: OSWorld 2.0 profile missing or drifted",
        failures,
    )

    _check(rli_authority.get("schema_id") == RLI_SCHEMA, "RLI: unsupported schema", failures)
    _check(rli_authority.get("row_count") == 15, "RLI: canonical row count is not 15", failures)
    rli_rows = rli_authority.get("rows", [])
    rli_tsv = (
        "".join("\t".join(row) + "\n" for row in rli_rows).encode("utf-8")
        if isinstance(rli_rows, list)
        and all(
            isinstance(row, list)
            and len(row) == 5
            and all(isinstance(item, str) for item in row)
            for row in rli_rows
        )
        else b""
    )
    _check(
        len(rli_rows) == 15
        and len(rli_tsv) == rli_authority.get("canonical_tsv_bytes")
        and hashlib.sha256(rli_tsv).hexdigest()
        == rli_authority.get("canonical_tsv_sha256"),
        "RLI: canonical rows do not reproduce the embedded TSV receipt",
        failures,
    )
    rli_recovery = rli_authority.get("recovery_verification", {})
    _check(
        isinstance(rli_recovery, dict)
        and rli_recovery.get("status") == "EXACT_CANONICAL_MATCH"
        and rli_recovery.get("raw_capture_retained") is False
        and rli_recovery.get("raw_capture_sha256") is None,
        "RLI: recovery status or raw-page authority ceiling drift",
        failures,
    )

    _check(hh_witness.get("schema_version") == HH_SCHEMA, "HH: unsupported schema", failures)
    hh_recovery = hh_witness.get("recovery", {})
    _check(
        isinstance(hh_recovery, dict)
        and hh_recovery.get("relation_row_source")
        == "current_recovery_database_not_missing_historical_database"
        and hh_recovery.get("witness_class")
        == "logical_witness_for_exact_accepted_projection_replay"
        and hh_recovery.get("limitation")
        == "does_not_establish_historical_relation_row_identity_or_recover_historical_duckdb_bytes",
        "HH: logical-witness authority ceiling drift",
        failures,
    )
    _check(
        len(hh_witness.get("hh_occupation", [])) == 270
        and len(hh_witness.get("hh_market_signal", [])) == 270
        and len(hh_witness.get("occupation_activity", [])) == 2359,
        "HH: witness relation counts drift",
        failures,
    )

    if failures:
        raise ReportInputError("research completion gates failed:\n- " + "\n- ".join(failures))

    assert isinstance(settled, int) and isinstance(unsettled, int)
    return {
        "schema": REPORT_SCHEMA,
        "research_status": (
            "RESEARCH_COMPLETE_WITH_PARTIAL_IDENTIFICATION"
            if corrected["incomplete"]
            else "RESEARCH_COMPLETE"
        ),
        "publication_status": "HOLD_SEPARATE_GATE_NOT_CLEARED",
        "baseline": baseline,
        "final_snapshot": final_snapshot,
        "corrected": corrected,
        "layer_two": layer_two,
        "evidence_registry": evidence_registry,
        "rli_authority": rli_authority,
        "hh_witness": hh_witness,
        "settled": settled,
        "unsettled": unsettled,
        "third_readings": third_readings,
        "third_nonresponses": len(nonresponse_ids),
    }


def load_and_validate(paths: ReportPaths) -> dict[str, Any]:
    loaded: dict[str, dict[str, Any]] = {}
    for role, path in paths.items():
        if role == "computer_use_evidence_audit":
            try:
                path.read_bytes()
            except OSError as exc:
                raise ReportInputError(f"{role}: cannot read {path}: {exc}") from exc
            continue
        loaded[role] = _load_object(path, role)
    return validate_inputs(
        baseline=loaded["work_mode_baseline"],
        final_snapshot=loaded["work_mode_final"],
        corrected=loaded["work_mode_corrected"],
        layer_two=loaded["layer_two_freeze"],
        evidence_registry=loaded["evidence_registry"],
        rli_authority=loaded["rli_authority"],
        hh_witness=loaded["hh_logical_witness"],
    )


def _receipt_rows(paths: ReportPaths) -> list[dict[str, object]]:
    return [
        {
            "role": role,
            "path": _relative(path),
            "sha256": _file_sha256(path),
            "bytes": path.stat().st_size,
        }
        for role, path in paths.items()
    ]


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _range_text(value: list[float]) -> str:
    return f"{_pct(value[0])}–{_pct(value[1])}"


def _count_text(value: dict[str, Any]) -> str:
    return f"{value['passed']}/{value['total']} pass; {value['failed']} fail"


def _quote(value: object) -> str:
    return shlex.quote(str(value))


def render_report(
    summary: dict[str, Any], paths: ReportPaths, report_date: str, output_path: Path
) -> bytes:
    """Render deterministic UTF-8 Markdown from validated scalar evidence."""
    final_snapshot = summary["final_snapshot"]
    corrected = summary["corrected"]
    transition = corrected["transition_audit"]
    layer_two = summary["layer_two"]
    selection = layer_two["selection"]
    byte_outcome = layer_two["outcomes"]["byte_suite_checker"]
    semantic_outcome = layer_two["outcomes"]["semantic_hardened"]
    tool_mismatch = layer_two["requires_tool_access_mismatch"]
    overlap = layer_two["worked_example_literal_overlap"]["aggregate"]
    registry = summary["evidence_registry"]
    receipts = _receipt_rows(paths)
    status = summary["research_status"]
    labels = final_snapshot["partition_counts"]["label"]
    label_source = final_snapshot["partition_counts"]["label_source"]
    n_raters = final_snapshot["partition_counts"]["n_raters"]
    strict = corrected["digital_share_strict"]
    generous = corrected["digital_share_generous"]
    arm_delta = corrected["components"]["arm_transport"][
        "employment_weighted_material_effect"
    ]["delta_current_minus_historical"]
    directional = corrected["components"]["directional_not_triple_rated_forced_contested"]
    sampling = corrected["components"]["sampling_answered_attempts"]
    prompt = layer_two["prompt_receipt_assertion"]
    backend = layer_two["served_backend_receipt_assertion"]
    redacted = layer_two["redacted_arm_preflight"]
    hh_recovery = summary["hh_witness"]["recovery"]
    rli_recovery = summary["rli_authority"]["recovery_verification"]
    corpus_text = f"{EXPECTED_CORPUS:,}".replace(",", " ")

    command_args = " ".join(
        [
            "--baseline",
            _quote(_command_path(paths.baseline)),
            "--final-snapshot",
            _quote(_command_path(paths.final_snapshot)),
            "--corrected",
            _quote(_command_path(paths.corrected)),
            "--layer-two",
            _quote(_command_path(paths.layer_two)),
            "--evidence-registry",
            _quote(_command_path(paths.evidence_registry)),
            "--rli-authority",
            _quote(_command_path(paths.rli_authority)),
            "--hh-witness",
            _quote(_command_path(paths.hh_witness)),
            "--external-audit",
            _quote(_command_path(paths.external_audit)),
        ]
    )
    frozen_final = _quote(_command_path(paths.final_snapshot))
    frozen_corrected = _quote(_command_path(paths.corrected))
    report_output = _quote(_command_path(output_path))
    final_status = final_snapshot["snapshot_status"]
    freeze_completion_args = [
        "--third-rater-status",
        _quote(final_status["third_rater_status"]),
    ]
    for proof in final_status["third_rater_nonresponses"]:
        freeze_completion_args.extend(
            [
                "--third-rater-nonresponse",
                _quote(proof["activity_id"]),
                "--third-rater-request-model",
                _quote(proof["requested_model_id"]),
            ]
        )
    freeze_completion_text = " ".join(freeze_completion_args)
    if summary["third_nonresponses"]:
        collection_statement = (
            f"Последний оценщик вернул {summary['third_readings']:,} успешных work-mode меток "
            f"из {corpus_text}; сохранён {summary['third_nonresponses']} hash-bound explicit "
            "nonresponse точного маршрута. Метка не была подставлена: задача осталась "
            "unsettled. Receipt доказывает отсутствие валидной метки, но не per-attempt content "
            "outcome и не причину на стороне провайдера."
        )
    else:
        collection_statement = (
            f"Три запрошенных маршрута вернули успешную work-mode метку для последнего "
            f"оценщика по всем {corpus_text} задачам."
        )
    lines = [
        "---",
        f"schema: {REPORT_SCHEMA}",
        f"report_date: {report_date}",
        f"research_status: {status}",
        "publication_status: HOLD_SEPARATE_GATE_NOT_CLEARED",
        "generated: true",
        "---",
        "",
        "# Что исследование AllJobs действительно установило",
        "",
        f"**Статус исследования: `{status}`. Публичный релиз: `HOLD`.**",
        "",
        (
            f"{collection_statement} После сохранения расхождений и пропусков как "
            f"неопределённости settled остаются {summary['settled']:,}, unsettled — "
            f"{summary['unsettled']:,}. Это измерение ответов моделей об описаниях задач, а не "
            "подтверждение того, какую долю работы можно передать ИИ."
        ),
        "",
        "## Слой 1 — где происходит работа",
        "",
        "| Показатель | Значение |",
        "|---|---:|",
        f"| Corpus | {EXPECTED_CORPUS} |",
        f"| screen | {labels.get('screen', 0)} |",
        f"| mixed | {labels.get('mixed', 0)} |",
        f"| physical | {labels.get('physical', 0)} |",
        f"| unsettled | {summary['unsettled']} |",
        f"| Explicit third-rater nonresponses | {summary['third_nonresponses']} |",
        f"| Ровно три успешных bulk-rater ответа | {n_raters.get('3', 0)} |",
        f"| Adjudicated из ранее существовавшего входа | {label_source.get('adjudicated', 0)} |",
        "",
        "Employment-weighted partial-identification sensitivity ranges:",
        "",
        f"- strict (`screen`): **{_range_text(strict)}**;",
        f"- generous (`screen + mixed`): **{_range_text(generous)}**.",
        "",
        (
            f"Это `{corrected['range_kind']}`. Coverage ceiling: "
            f"`{corrected['coverage_ceiling']}`. Ни одна граница не выбрана как point estimate."
        ),
        "",
        "Неопределённости сохранены раздельно:",
        "",
        (
            f"- unanswered experiment attempts: partial identification; lost attempts "
            f"{corrected['lost_attempts']};"
        ),
        (
            f"- answered-attempt sampling: `{sampling['range_kind']}`; "
            f"`{sampling['coverage_ceiling']}`;"
        ),
        (
            f"- directional partition sensitivity: {directional['all_not_triple_rated_activities']} "
            "задач с менее чем тремя ответами принудительно рассматриваются как contested;"
        ),
        (
            "- historical/current arm transport остаётся отдельной диагностикой; изменение "
            f"strict endpoints = {arm_delta['digital_share_strict']}, generous endpoints = "
            f"{arm_delta['digital_share_generous']}."
        ),
        "",
        "Переход baseline → final:",
        "",
        f"- stratum 2×2: `{json.dumps(transition['stratum_2x2'], sort_keys=True)}`;",
        f"- settlement 2×2: `{json.dumps(transition['settlement_2x2'], sort_keys=True)}`;",
        (
            "- ранее settled, но теперь split-awaiting-adjudication: "
            f"{transition['previously_settled_to_split_awaiting_adjudication']}."
        ),
        "",
        "## Слой 2 — deterministic mission evidence",
        "",
        (
            f"Из {selection['bound_missions']} bound missions измерены "
            f"{selection['primary_measured_missions']}; у {selection['complete_vote_join']} есть "
            "полный vote join. Primary outcome намеренно не выбран."
        ),
        "",
        "| Outcome | Все измеренные | Complete vote join | Ceiling |",
        "|---|---:|---:|---|",
        (
            f"| Suite/domain checker | {_count_text(byte_outcome['all_answered'])} | "
            f"{_count_text(byte_outcome['complete_vote_join'])} | necessary deterministic "
            "conformance, not mission success |"
        ),
        (
            f"| Hardened semantic | {_count_text(semantic_outcome['all_answered'])} | "
            f"{_count_text(semantic_outcome['complete_vote_join'])} | compared decisions and "
            "memberships only; exempt prose unverified |"
        ),
        "",
        (
            f"Exclusions: {sum(item['count'] for item in selection['exclusions_by_primary_reason'].values())} "
            "mission rows по primary reason; ещё "
            f"{selection['complete_vote_join_exclusions_from_primary']['count']} measured missions "
            "не входят в complete-vote анализ."
        ),
        "",
        "Инструментальные ограничения, которые нельзя снять высокой долей pass:",
        "",
        (
            f"- {tool_mismatch['complete_measured_missions_with_any_endorsement']}/78 complete "
            "missions получили хотя бы один requires-tool endorsement, но measured arm не имел tools;"
        ),
        (
            f"- exact historical prompt bytes verified: "
            f"`{prompt['exact_historical_prompt_bytes_verified']}`; rendered hashes present: "
            f"{prompt['rendered_prompt_hashes_present']}/82;"
        ),
        (
            f"- measurement trial router receipts: "
            f"{backend['measurement_trials']['receipts_present']}/82, но это не независимая "
            "backend attestation; predictor vote receipts verified: false;"
        ),
        (
            f"- worked examples разделяют хотя бы один exact non-ID output literal в "
            f"{overlap['missions_with_any_exact_non_id_output_literal']}/"
            f"{overlap['measured_missions']} measured missions;"
        ),
        (
            f"- redacted-example arm: `{redacted['decision']}` — "
            f"{redacted['failed_targets']}/{redacted['evaluated_targets']} competence failures; "
            "запуска модели не было."
        ),
        "",
        "## Внешняя проверка computer-use",
        "",
        (
            "OSWorld 2.0 учтён как item-level GUI benchmark с 108 long-horizon workflows. "
            "Статья a16z используется как вторичный обзор, а не как первичная выборка. "
            f"В registry собрано {registry['profile_counts']['collected_profiles']} profiles и "
            f"{len(registry['edges'])} candidate edges; edges, способных authorise an AllJobs "
            f"bound: **{registry['edges_authorising_a_bound']}**."
        ),
        "",
        (
            "Следовательно, внешние данные уточняют дизайн successor study, но не задают "
            "верхнюю или нижнюю границу capability для задач AllJobs."
        ),
        "",
        "## Восстановленная authority и её предел",
        "",
        (
            f"- RLI: {summary['rli_authority']['row_count']} canonical rows, "
            f"`{rli_recovery['status']}`; raw page capture retained: "
            f"`{rli_recovery['raw_capture_retained']}`."
        ),
        (
            "- HH: current-recovery-database logical witness воспроизводит accepted projection; "
            f"relation row source = `{hh_recovery['relation_row_source']}`; limitation = "
            f"`{hh_recovery['limitation']}`."
        ),
        "",
        "## Input receipts",
        "",
        "| Role | Path | Bytes | SHA-256 |",
        "|---|---|---:|---|",
    ]
    lines.extend(
        f"| {row['role']} | `{row['path']}` | {row['bytes']} | `{row['sha256']}` |"
        for row in receipts
    )
    lines.extend(
        [
            "",
            "Embedded bindings:",
            "",
            f"- baseline snapshot payload: `{summary['baseline']['snapshot_payload_sha256']}`;",
            f"- final snapshot payload: `{final_snapshot['snapshot_payload_sha256']}`;",
            f"- transition audit payload: `{transition['audit_payload_sha256']}`;",
            f"- layer-two input set: `{layer_two['input_set_digest']}`.",
            "",
            "## Reproduction",
            "",
            "Run from `workforce-graph/` in the locked environment:",
            "",
            "```bash",
            "replay_dir=$(mktemp -d /tmp/alljobs-research-replay.XXXXXX)",
            "final_replay=\"$replay_dir/work-mode-final.json\"",
            "corrected_replay=\"$replay_dir/work-mode-corrected.json\"",
            (
                "uv run python scripts/freeze_work_mode_snapshot.py freeze "
                "--output \"$final_replay\" "
                f"--snapshot-date {final_snapshot['snapshot_date']} "
                f"--third-rater {EXPECTED_THIRD_RATER} {freeze_completion_text} "
                f"--baseline-snapshot {_quote(_command_path(paths.baseline))} "
                f"--expected-corpus-size {EXPECTED_CORPUS} --experiment-rater glm-5.2"
            ),
            f"cmp \"$final_replay\" {frozen_final}",
            (
                "uv run python scripts/correct_for_uncertainty.py "
                "--state-snapshot \"$final_replay\" "
                f"--baseline-snapshot {_quote(_command_path(paths.baseline))} --rater glm-5.2 "
                "--write \"$corrected_replay\""
            ),
            f"cmp \"$corrected_replay\" {frozen_corrected}",
            "uv run python scripts/freeze_layer_two.py --check",
            (
                "uv run python scripts/build_research_completion_report.py --check "
                f"{command_args} --report-date {report_date} --output {report_output}"
            ),
            "```",
            "",
            (
                "Повторная генерация snapshot/corrected-result должна выполняться в новые "
                "временные пути и сравниваться byte-for-byte: tracked evidence не "
                "перезаписывается для проверки."
            ),
            "",
            "## Claim ceiling и publication gate",
            "",
            (
                "Допустимая итоговая формулировка: исследование измерило ответы трёх "
                f"запрошенных model routes о {EXPECTED_CORPUS} work-task statements и сохранило "
                "несогласие, missingness, sampling и transport как отдельные источники "
                "неопределённости. Оно не проверило центральный capability/automation тезис "
                "из-за отсутствия независимого task-truth и переносимых внешних границ — не "
                "из-за доказанного отсутствия связи."
            ),
            "",
            (
                "`RESEARCH_COMPLETE` не означает `PUBLICATION_COMPLETE`. Лицензия, условия "
                "redistribution, absolute local paths, public remote и working-record treatment "
                "остаются отдельными блокерами в `PUBLICATION-READINESS.md`."
            ),
            "",
            (
                "Исторические отчёты `2026-08-08-vote-index-onet-corpus-EN.md` и "
                "`2026-08-08-индекс-голосов-российский-рынок-RU.md` не являются текущим "
                "источником чисел."
            ),
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def write_no_replace(path: Path, content: bytes) -> str:
    """Atomically publish once; an identical existing target is accepted unchanged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == content:
            return "unchanged"
        raise ReportInputError(f"refusing to replace existing non-identical report: {path}")
    with tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ReportInputError(f"competing non-identical report appeared at {path}")
        return "unchanged"
    finally:
        temporary.unlink(missing_ok=True)
    return "written"


def _path_options(function):
    options = [
        click.option("--baseline", type=click.Path(path_type=Path, exists=True), required=True),
        click.option(
            "--final-snapshot", type=click.Path(path_type=Path, exists=True), required=True
        ),
        click.option("--corrected", type=click.Path(path_type=Path, exists=True), required=True),
        click.option("--layer-two", type=click.Path(path_type=Path, exists=True), required=True),
        click.option(
            "--evidence-registry", type=click.Path(path_type=Path, exists=True), required=True
        ),
        click.option(
            "--rli-authority", type=click.Path(path_type=Path, exists=True), required=True
        ),
        click.option("--hh-witness", type=click.Path(path_type=Path, exists=True), required=True),
        click.option(
            "--external-audit", type=click.Path(path_type=Path, exists=True), required=True
        ),
    ]
    for option in reversed(options):
        function = option(function)
    return function


@click.command()
@_path_options
@click.option("--report-date", help="Explicit YYYY-MM-DD provenance date.")
@click.option("--output", type=click.Path(path_type=Path))
@click.option("--preflight", is_flag=True, help="Run every completion gate and never write.")
@click.option("--check", is_flag=True, help="Require the existing report to be byte-identical.")
def main(
    baseline: Path,
    final_snapshot: Path,
    corrected: Path,
    layer_two: Path,
    evidence_registry: Path,
    rli_authority: Path,
    hh_witness: Path,
    external_audit: Path,
    report_date: str | None,
    output: Path | None,
    preflight: bool,
    check: bool,
) -> None:
    """Validate frozen evidence and optionally build or check the final Markdown report."""
    if preflight and check:
        raise click.UsageError("--preflight and --check are mutually exclusive")
    if not preflight and (not report_date or output is None):
        raise click.UsageError("--report-date and --output are required unless --preflight is used")
    if report_date:
        try:
            date.fromisoformat(report_date)
        except ValueError as exc:
            raise click.UsageError("--report-date must be an ISO YYYY-MM-DD date") from exc
    paths = ReportPaths(
        baseline=baseline,
        final_snapshot=final_snapshot,
        corrected=corrected,
        layer_two=layer_two,
        evidence_registry=evidence_registry,
        rli_authority=rli_authority,
        hh_witness=hh_witness,
        external_audit=external_audit,
    )
    try:
        summary = load_and_validate(paths)
        if preflight:
            click.echo(f"PASS {summary['research_status']}; no output written")
            return
        assert report_date is not None and output is not None
        rendered = render_report(summary, paths, report_date, output)
        if check:
            if not output.exists() or output.read_bytes() != rendered:
                raise ReportInputError(f"report is missing or stale: {output}")
            click.echo(f"PASS byte-identical: {output}")
            return
        disposition = write_no_replace(output, rendered)
        click.echo(f"{disposition}: {output} ({len(rendered)} bytes)")
    except ReportInputError as exc:
        raise click.ClickException(f"HOLD: {exc}") from exc


if __name__ == "__main__":
    main()
