"""Freeze the powered harder-mission predictive-validity successor before model spend.

The frame is category-balanced, uses complete frozen predictor votes, and contains one new
semantic-shifted main case per independent mission.  Every expected output must pass the existing
independent domain checker while the stale pre-shift output must fail.  Pilot cases tune only the
amount of schema guidance; main outcomes never tune the instrument.

This measures deterministic conformance in a synthetic read-only tool harness.  The suite still
requires a human holistic rubric that this project will not perform, so neither a passing case nor
a predictive association is mission success, production reliability, or a workforce bound.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import click

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

from workforce_graph.evidence.task4_phase2b_operators import (
    apply_domain_mutation_payloads,
    check_operator_output,
    derive_operator_output,
    operator_contract_for_mission,
    render_operator_case,
)
from workforce_graph.evidence.task4_phase2b_profiles import CATEGORY_ORDER

SCHEMA_VERSION = "alljobs.predictive-validity-successor-frame.v3"
MODEL_ID = "google/gemini-3.5-flash-lite"
FRAME_SEED = "alljobs-powered-successor-2026-08-12-v2"
INSTRUMENT_SEED = "alljobs-powered-successor-2026-08-12-v3-worked-example"
SCAFFOLDS = (
    "worked_example",
    "worked_example_plus_recursive_shape",
)
VARIANTS = ("semantic_shift", "dense_semantic_shift")
LAYER_TWO = ROOT / "data" / "benchmark_relevance" / "layer_two_freeze.json"
OPERATORS = ROOT / "src" / "workforce_graph" / "evidence" / "task4_phase2b_operators.py"
PROFILES = ROOT / "src" / "workforce_graph" / "evidence" / "task4_phase2b_profiles.py"
CURRENT_REPORT = REPO_ROOT / "docs" / "reports" / "2026-08-12-research-completion.md"
FRAME_BUILDER = Path(__file__).resolve()
RUNNER = Path(__file__).resolve().parent / "run_predictive_validity_successor.py"
ANALYZER = Path(__file__).resolve().parent / "analyze_predictive_validity_successor.py"
PREDECESSOR_FRAME = ROOT / "data" / "predictive_validity" / "successor_2026-08-12-v2" / "frame.json"
DEFAULT_OUTPUT = ROOT / "data" / "predictive_validity" / "successor_2026-08-12-v3" / "frame.json"


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def payload_hash(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "payload_sha256"}
    return sha256_bytes(canonical_bytes(payload))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON source {path}: {error}") from error


def _stable_score(namespace: str, mission_id: str) -> str:
    return sha256_bytes(f"{FRAME_SEED}:{namespace}:{mission_id}".encode())


def _model_catalog_receipt(
    path: Path,
    endpoint_path: Path,
    transport_path: Path,
    transport_base_url: str,
) -> dict[str, Any]:
    catalog = _read_json(path)
    rows = catalog.get("data") if isinstance(catalog, dict) else None
    matches = [row for row in rows or [] if isinstance(row, dict) and row.get("id") == MODEL_ID]
    if len(matches) != 1:
        raise ValueError(f"expected one exact OpenRouter catalog row for {MODEL_ID}")
    model = matches[0]
    pricing = model.get("pricing") or {}
    if pricing.get("prompt") != "0.0000003" or pricing.get("completion") != "0.0000025":
        raise ValueError("OpenRouter model price changed; budget must be explicitly re-authorised")
    required = {"response_format", "tool_choice", "tools"}
    if not required.issubset(model.get("supported_parameters") or []):
        raise ValueError("selected route no longer advertises the required tool/JSON parameters")
    endpoints = _read_json(endpoint_path)
    endpoint_rows = (
        (endpoints.get("data") or {}).get("endpoints") if isinstance(endpoints, dict) else None
    )
    provider_matches = [
        row
        for row in endpoint_rows or []
        if isinstance(row, dict)
        and row.get("provider_name") == "Google AI Studio"
        and row.get("tag") == "google-ai-studio"
        and row.get("status") == 0
        and (row.get("pricing") or {}).get("prompt") == pricing["prompt"]
        and (row.get("pricing") or {}).get("completion") == pricing["completion"]
    ]
    if len(provider_matches) != 1:
        raise ValueError("exact Google AI Studio base-price endpoint is unavailable")
    transport = _read_json(transport_path)
    transport_rows = transport.get("data") if isinstance(transport, dict) else None
    transport_matches = [
        row
        for row in transport_rows or []
        if isinstance(row, dict)
        and row.get("id") == MODEL_ID
        and row.get("owned_by") == "openrouter"
    ]
    if len(transport_matches) != 1:
        raise ValueError("configured transport does not advertise the exact OpenRouter route")
    if transport_base_url.rstrip("/") != "http://localhost:3001/v1":
        raise ValueError("transport base URL is not the inspected local OpenRouter proxy")
    return {
        "catalog_bytes": path.stat().st_size,
        "catalog_endpoint": "https://openrouter.ai/api/v1/models",
        "catalog_sha256": sha256_path(path),
        "context_length": model.get("context_length"),
        "endpoint_catalog_bytes": endpoint_path.stat().st_size,
        "endpoint_catalog_endpoint": (
            "https://openrouter.ai/api/v1/models/google/gemini-3.5-flash-lite/endpoints"
        ),
        "endpoint_catalog_sha256": sha256_path(endpoint_path),
        "id": MODEL_ID,
        "name": model.get("name"),
        "pricing_per_token_usd": {
            "completion": pricing["completion"],
            "prompt": pricing["prompt"],
        },
        "provider_policy": {
            "allow_fallbacks": False,
            "order": ["Google AI Studio"],
            "required_observed_provider": "Google AI Studio",
        },
        "supported_parameters": sorted(model.get("supported_parameters") or []),
        "transport": {
            "base_url": transport_base_url.rstrip("/"),
            "catalog_bytes": transport_path.stat().st_size,
            "catalog_sha256": sha256_path(transport_path),
            "expected_routed_model": MODEL_ID,
            "expected_routed_platform": "openrouter",
            "key_scope": "configured_local_proxy_not_direct_openrouter",
        },
    }


def _case_complexity(value: Any) -> dict[str, int]:
    counts = Counter()

    def visit(item: Any, depth: int) -> None:
        counts["max_depth"] = max(counts["max_depth"], depth)
        if isinstance(item, dict):
            counts["objects"] += 1
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            counts["arrays"] += 1
            counts["array_items"] += len(item)
            for child in item:
                visit(child, depth + 1)
        else:
            counts["leaves"] += 1
            if isinstance(item, bool) or item is None:
                counts["boolean_or_null_leaves"] += 1
            elif isinstance(item, (int, float)):
                counts["numeric_leaves"] += 1
            elif isinstance(item, str):
                counts["string_leaves"] += 1

    visit(value, 0)
    return {key: counts[key] for key in sorted(counts)}


def _dense_harden(mission_id: str, input_payload: dict[str, Any]) -> None:
    """Add deterministic distractors/work while retaining the operator's declared semantics."""

    contract = operator_contract_for_mission(mission_id)
    case = input_payload["case"]
    facts = case["facts"]
    rules = case["rules"]
    operator_id = contract.operator_id
    if operator_id == "reconcile-records":
        mode = rules["comparison_mode"]
        if mode == "sum-validity":
            facts["survey_checks"].extend(
                {
                    "components": [index, index + 1, index + 2],
                    "left_record_id": f"dense-survey-{index}",
                    "reported_total": 3 * index + 3 + (index % 2),
                    "right_record_id": f"dense-report-{index}",
                }
                for index in range(11, 16)
            )
        elif mode == "minimum-criterion":
            facts["criteria"].extend(
                {
                    "actual": 60 + index,
                    "left_record_id": f"dense-metric-{index}",
                    "minimum": 63 + (index % 3),
                    "right_record_id": f"dense-criterion-{index}",
                }
                for index in range(5)
            )
        else:
            facts["record_pairs"].extend(
                {
                    "left_record_id": f"dense-left-{index}",
                    "left_value": f"Value-{index}",
                    "right_record_id": f"dense-right-{index}",
                    "right_value": (
                        f"value-{index}"
                        if mode == "casefold-equality"
                        else f"Value-{index}"
                        if index % 2 == 0
                        else f"Other-{index}"
                    ),
                }
                for index in range(5)
            )
    elif operator_id == "compose-grounded-document":
        sections = rules["required_section_codes"]
        facts["source_facts"].extend(
            {
                "fact_id": f"dense-fact-{index}",
                "section_code": sections[index % len(sections)],
                "source_id": f"dense-source-{index}",
                "text": f"Dense synthetic supporting fact {index}; preserve exact grounding.",
            }
            for index in range(1, 7)
        )
    elif operator_id == "prepare-escalation":
        primary = facts["observations"][0]
        rules["primary_evidence_id"] = primary["evidence_id"]
        facts["observations"].extend(
            {
                "evidence_id": f"dense-evidence-{index}",
                "metric": f"distractor-score-{index}",
                "value": 49 + index,
            }
            for index in range(1, 6)
        )
    elif operator_id == "resolve-exception":
        primary = facts["observations"][0]
        rules["primary_evidence_parts"] = primary["evidence_parts"]
        facts["observations"].extend(
            {
                "evidence_parts": ["dense", "exception", str(index)],
                "metric": f"distractor-{index}",
                "unit": primary["unit"],
                "value": 110 + index,
                "window": primary["window"],
            }
            for index in range(1, 6)
        )
    elif operator_id == "solve-schedule":
        facts["busy_intervals"].extend(
            [
                {"end_minute": 595, "start_minute": 585},
                {"end_minute": 715, "start_minute": 705},
            ]
        )
        facts["resources"].extend(
            {
                "availability_windows": [{"end_minute": 720, "start_minute": 540}],
                "blocking_intervals": [{"end_minute": 720, "start_minute": 540}],
                "capacity": 20,
                "equipment": ["projector", "video_bridge"],
                "resource_id": f"dense-blocked-room-{index}",
            }
            for index in range(3)
        )
    elif operator_id == "retrieve-trace":
        if rules["mode"] == "closed-corpus-keyword":
            facts["documents"].extend(
                {
                    "record_id": f"dense-record-{index}",
                    "section": f"D{index}",
                    "text": f"Dense distractor passage {index} with no exact query token.",
                }
                for index in range(1, 8)
            )
        else:
            facts["records"].extend(
                {
                    "record_id": f"dense-island-{index}",
                    "section": f"I{index}",
                    "text": "Disconnected local record.",
                }
                for index in range(1, 6)
            )
    elif operator_id == "classify-taxonomy":
        rules["labels"].extend(
            {
                "code": f"DENSE-{index}",
                "heading": f"Dense distractor heading {index}",
                "keyword": f"dense-keyword-{index}",
            }
            for index in range(1, 8)
        )
    elif operator_id == "apply-policy":
        facts["clauses"].extend(
            {
                "clause_id": f"DENSE-{index}",
                "kind": "non_applicable_context",
                "text": f"Dense non-applicable context clause {index}.",
            }
            for index in range(1, 7)
        )
    elif operator_id == "audit-quality":
        for index in range(1, 7):
            token = f"DENSE-DEFECT-{index}"
            rules["checks"].append(
                {
                    "check_id": f"dense-check-{index}",
                    "defect_code": "token-defect",
                    "match_text": token,
                }
            )
            if index % 2:
                facts["artifact"]["text"] += f" {token}"
    elif operator_id == "stage-record":
        variant = rules["variant_code"]
        records = facts.get("records") if variant == "set" else [facts["record"]]
        if variant != "legacy":
            for record_index, record in enumerate(records):
                record["field_specs"].extend(
                    {
                        "field_code": f"field|dense_{record_index}_{index}",
                        "source_parts": [["dense", str(record_index), str(index)]],
                        "type_code": "type|integer",
                        "unit_code": "unit|count",
                        "value_code": f"integer|{100 + index}",
                    }
                    for index in range(1, 5)
                )
    else:  # pragma: no cover - all ten current operators are enumerated above
        raise ValueError(f"unsupported operator hardening: {operator_id}")


def _variant_case(mission_id: str, variant: str, source: Mapping[str, Any]) -> dict[str, Any]:
    rendered = render_operator_case(
        mission_id,
        activity_id=source["activity_id"],
        activity_title=source.get("activity_title") or f"AllJobs activity {source['activity_id']}",
    )
    semantic_id = f"{rendered.contract.operator_id}-semantic-input"
    mutated_input, stale_output = apply_domain_mutation_payloads(
        mission_id,
        rendered.input_payload,
        rendered.output_payload,
        semantic_id,
    )
    if variant == "dense_semantic_shift":
        _dense_harden(mission_id, mutated_input)
    elif variant != "semantic_shift":
        raise ValueError(f"unsupported successor variant: {variant}")
    expected = derive_operator_output(mission_id, mutated_input)
    expected_check = check_operator_output(mission_id, mutated_input, expected)
    stale_check = check_operator_output(mission_id, mutated_input, stale_output)
    if not expected_check.passed or stale_check.passed:
        raise ValueError(f"successor competence gate failed for {mission_id}/{variant}")
    input_bytes = canonical_bytes(mutated_input)
    output_bytes = canonical_bytes(expected)
    complexity = _case_complexity(mutated_input)
    complexity["input_bytes"] = len(input_bytes)
    complexity["expected_output_bytes"] = len(output_bytes)
    complexity["difficulty_index"] = round(
        math.log1p(len(input_bytes))
        + math.log1p(len(output_bytes))
        + 0.15 * complexity["max_depth"]
        + 0.02 * complexity["array_items"],
        8,
    )
    return {
        "base_mission_id": mission_id,
        "case_id": f"{mission_id}::{variant}",
        "category": source["category"],
        "competence_gate": {
            "checker_version": expected_check.checker_version,
            "expected_passes": True,
            "expected_sha256": sha256_bytes(output_bytes),
            "stale_failed_invariants": list(stale_check.failed_invariant_ids),
            "stale_output_rejected": True,
        },
        "difficulty_features": complexity,
        "input_payload": mutated_input,
        "input_sha256": sha256_bytes(input_bytes),
        "operator_id": rendered.contract.operator_id,
        "output_schema_reference": rendered.output_schema_reference,
        "split": source["split"],
        "variant": variant,
        "vote_doses": copy.deepcopy(source["vote_doses"]),
    }


def _frozen_sources(layer_two: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    frozen = _read_json(layer_two)
    if (
        not isinstance(frozen, dict)
        or frozen.get("schema_version") != "alljobs.layer-two-freeze.v1"
    ):
        raise ValueError("layer-two predictor source is not the frozen v1 artifact")
    rows = {}
    for row in frozen.get("missions", []):
        if not isinstance(row, dict) or not row.get("mission_id"):
            raise ValueError("layer-two mission row is malformed")
        rows[row["mission_id"]] = row
    if len(rows) != 120:
        raise ValueError("layer-two mission frame drifted from 120 rows")
    return rows, frozen


def build_frame(
    *,
    model_catalog: Path,
    endpoint_catalog: Path,
    transport_catalog: Path,
    transport_base_url: str,
    base_commit: str,
    layer_two: Path = LAYER_TWO,
    predecessor_frame: Path = PREDECESSOR_FRAME,
) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{40}", base_commit) is None:
        raise ValueError("base_commit must be a lowercase 40-hex Git commit")
    rows, _frozen = _frozen_sources(layer_two)
    supported = set()
    for mission_id, row in rows.items():
        try:
            operator_contract_for_mission(mission_id)
        except ValueError:
            continue
        if row.get("complete_vote_join") is True:
            supported.add(mission_id)

    pilot_cases: list[dict[str, Any]] = []
    main_cases: list[dict[str, Any]] = []
    category_examples: dict[str, dict[str, Any]] = {}
    competence_exclusions: list[dict[str, str]] = []
    for category in CATEGORY_ORDER:
        pilot_pool = sorted(
            (
                mission_id
                for mission_id in supported
                if rows[mission_id]["category"] == category
                and rows[mission_id]["split"] == "development"
            ),
            key=lambda mission_id: _stable_score("pilot", mission_id),
        )
        main_pool = sorted(
            (
                mission_id
                for mission_id in supported
                if rows[mission_id]["category"] == category
                and rows[mission_id]["split"] != "development"
            ),
            key=lambda mission_id: _stable_score("main", mission_id),
        )
        if not pilot_pool or len(main_pool) < 7:
            raise ValueError(f"insufficient complete-vote successor frame for {category}")
        category_pilot: list[dict[str, Any]] | None = None
        for mission_id in pilot_pool:
            try:
                candidate = [
                    _variant_case(mission_id, variant, rows[mission_id]) for variant in VARIANTS
                ]
            except (ArithmeticError, KeyError, StopIteration, TypeError, ValueError) as error:
                competence_exclusions.append(
                    {
                        "category": category,
                        "mission_id": mission_id,
                        "reason": f"{type(error).__name__}: {error}",
                        "stage": "pilot",
                    }
                )
                continue
            category_pilot = candidate
            break
        if category_pilot is None:
            raise ValueError(f"no competent pilot transformation for {category}")
        pilot_cases.extend(category_pilot)

        example_pool = [
            mission_id
            for mission_id in pilot_pool
            if mission_id != category_pilot[0]["base_mission_id"]
        ]
        if not example_pool:
            raise ValueError(f"no independent worked example mission for {category}")
        example_case = _variant_case(example_pool[0], "semantic_shift", rows[example_pool[0]])
        example_output = derive_operator_output(
            example_case["base_mission_id"], example_case["input_payload"]
        )
        category_examples[category] = {
            "base_mission_id": example_case["base_mission_id"],
            "case_id": example_case["case_id"],
            "competence_gate": example_case["competence_gate"],
            "input_payload": example_case["input_payload"],
            "input_sha256": example_case["input_sha256"],
            "output_payload": example_output,
            "output_sha256": sha256_bytes(canonical_bytes(example_output)),
        }

        category_main: list[dict[str, Any]] = []
        for mission_id in main_pool:
            try:
                candidate = _variant_case(mission_id, "dense_semantic_shift", rows[mission_id])
            except (ArithmeticError, KeyError, StopIteration, TypeError, ValueError) as error:
                competence_exclusions.append(
                    {
                        "category": category,
                        "mission_id": mission_id,
                        "reason": f"{type(error).__name__}: {error}",
                        "stage": "main",
                    }
                )
                continue
            category_main.append(candidate)
            if len(category_main) == 7:
                break
        if len(category_main) != 7:
            raise ValueError(f"fewer than seven competent main transformations for {category}")
        main_cases.extend(category_main)

    predecessor = _read_json(predecessor_frame)
    if not isinstance(predecessor, dict) or predecessor.get("schema_version") != (
        "alljobs.predictive-validity-successor-frame.v2"
    ):
        raise ValueError("worked-example successor predecessor frame is missing or malformed")
    for phase, cases in (("pilot_cases", pilot_cases), ("main_cases", main_cases)):
        predecessor_identity = [
            (row["case_id"], row["input_sha256"], row["vote_doses"]) for row in predecessor[phase]
        ]
        current_identity = [
            (row["case_id"], row["input_sha256"], row["vote_doses"]) for row in cases
        ]
        if current_identity != predecessor_identity:
            raise ValueError(f"V3 changed the frozen V2 {phase} frame")
    frame = {
        "analysis_plan": {
            "blocked_permutation": {
                "block": "category",
                "permutations": 1999,
                "seed": f"{FRAME_SEED}:blocked-permutation",
                "unit": "mission_cluster",
            },
            "cross_validation": {
                "folds": 5,
                "group": "base_mission_id",
                "stratification": "category plus deterministic hash",
            },
            "difficulty_only_features": ["category", "difficulty_index"],
            "incremental_features": ["can_do", "no_human_review", "requires_tool_access"],
            "independent_mission_clusters": 70,
            "minimum_detectable_signal": {
                "assumed_failure_probability": 0.30,
                "claim": (
                    "approximately 80% Wald power for a residual standardized predictor odds "
                    "ratio of at least 2.2 at two-sided alpha 0.05; smaller effects remain "
                    "underpowered and the blocked permutation is primary"
                ),
                "odds_ratio": 2.2,
                "power_floor": 0.80,
            },
            "primary_metric": "five-fold held-out log-loss improvement, difficulty-only minus difficulty-plus-votes",
            "promotion_rule": (
                "report an incremental predictive association only if all 70 outcomes are "
                "observed, failures are 14..28, held-out log loss improves, and blocked "
                "permutation p <= 0.05"
            ),
            "ridge_penalty": 2.0,
            "target_failure_count": [14, 28],
        },
        "base_commit": base_commit,
        "claim_ceiling": {
            "allowed": (
                "predictive validity of frozen model-vote doses for deterministic conformance "
                "in one synthetic read-only tool harness under one exact model route"
            ),
            "causal_effect_identified": False,
            "mission_success_measured": False,
            "not_osworld_or_gui_computer_use": True,
            "not_workforce_share_or_production_reliability": True,
        },
        "category_worked_examples": category_examples,
        "competence_exclusions": competence_exclusions,
        "frame_seed": FRAME_SEED,
        "instrument_seed": INSTRUMENT_SEED,
        "main_cases": main_cases,
        "model_budget": {
            "maximum_case_runs": 110,
            "maximum_completion_tokens_per_final_call": 3000,
            "maximum_estimated_cost_usd": 2.25,
            "model_calls_per_case": 2,
            "planned_main_case_runs": 70,
            "planned_pilot_case_runs": 40,
            "stop_before_main_unless_pilot_failure_count_is_4_to_8_of_20": True,
        },
        "model_route": _model_catalog_receipt(
            model_catalog,
            endpoint_catalog,
            transport_catalog,
            transport_base_url,
        ),
        "pilot_cases": pilot_cases,
        "pilot_rule": {
            "candidate_scaffolds": list(SCAFFOLDS),
            "failures_target": [4, 8],
            "observations_per_scaffold": 20,
            "selection": (
                "among scaffolds in range choose failure count closest to 6; ties choose the "
                "worked-example-only scaffold; if none are in range HOLD"
            ),
        },
        "schema_version": SCHEMA_VERSION,
        "source_receipts": {
            "analysis_script": sha256_path(ANALYZER),
            "current_completion_report": sha256_path(CURRENT_REPORT),
            "frame_builder_script": sha256_path(FRAME_BUILDER),
            "layer_two_freeze": sha256_path(layer_two),
            "operator_source": sha256_path(OPERATORS),
            "profile_source": sha256_path(PROFILES),
            "runner_script": sha256_path(RUNNER),
            "schema_only_predecessor_frame": sha256_path(predecessor_frame),
        },
        "study_status": "PREREGISTERED_NO_MODEL_CALLS",
        "tool_harness": {
            "case_access": "one required local read_case function call; no network or write tool",
            "outcome": "independent deterministic domain-checker conformance",
            "transport_or_route_error_is_failure": False,
            "unparseable_or_tool-contract-agent-output_is_failure": True,
            "worked_example_ceiling": (
                "category-matched worked input/output conveys reusable serialization and semantic "
                "content; results are agent-plus-scaffold conformance, not isolated capability"
            ),
        },
    }
    frame["payload_sha256"] = payload_hash(frame)
    validate_frame(frame)
    return frame


def validate_frame(frame: Mapping[str, Any]) -> None:
    if frame.get("payload_sha256") != payload_hash(frame):
        raise ValueError("frame payload hash mismatch")
    if frame.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("frame schema mismatch")
    if frame.get("study_status") != "PREREGISTERED_NO_MODEL_CALLS":
        raise ValueError("frame must be frozen before any model calls")
    pilot = frame.get("pilot_cases")
    main = frame.get("main_cases")
    if not isinstance(pilot, list) or len(pilot) != 20:
        raise ValueError("pilot frame must contain 20 cases")
    if not isinstance(main, list) or len(main) != 70:
        raise ValueError("main frame must contain 70 independent cases")
    if Counter(row.get("category") for row in pilot) != Counter(
        {category: 2 for category in CATEGORY_ORDER}
    ):
        raise ValueError("pilot frame is not category-balanced")
    if Counter(row.get("category") for row in main) != Counter(
        {category: 7 for category in CATEGORY_ORDER}
    ):
        raise ValueError("main frame is not category-balanced")
    examples = frame.get("category_worked_examples")
    if not isinstance(examples, dict) or set(examples) != set(CATEGORY_ORDER):
        raise ValueError("category worked-example frame is incomplete")
    pilot_missions = {row["base_mission_id"] for row in pilot}
    for category, example in examples.items():
        if example.get("base_mission_id") in pilot_missions:
            raise ValueError("worked example reuses a pilot target mission")
        if example.get("input_sha256") != sha256_bytes(
            canonical_bytes(example.get("input_payload"))
        ) or example.get("output_sha256") != sha256_bytes(
            canonical_bytes(example.get("output_payload"))
        ):
            raise ValueError(f"worked example hash mismatch for {category}")
    if len({row.get("base_mission_id") for row in main}) != 70:
        raise ValueError("main frame repeats a mission cluster")
    for row in [*pilot, *main]:
        gate = row.get("competence_gate") or {}
        if gate.get("expected_passes") is not True or gate.get("stale_output_rejected") is not True:
            raise ValueError("frame contains an incompetent transformed mission")
        if row.get("input_sha256") != sha256_bytes(canonical_bytes(row.get("input_payload"))):
            raise ValueError("case input hash mismatch")
        doses = row.get("vote_doses") or {}
        if set(doses) != {"can_do", "no_human_review", "requires_tool_access"} or any(
            type(value) is not int or value < 0 or value > 3 for value in doses.values()
        ):
            raise ValueError("case predictor votes are incomplete or malformed")
    ceiling = frame.get("claim_ceiling") or {}
    if ceiling.get("mission_success_measured") is not False:
        raise ValueError("synthetic deterministic conformance became mission success")


def select_scaffold(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {}
    for scaffold in SCAFFOLDS:
        arm = [row for row in records if row.get("scaffold") == scaffold]
        if len(arm) != 20 or any(
            not isinstance((row.get("outcome") or {}).get("conformant"), bool) for row in arm
        ):
            raise ValueError(f"pilot scaffold is incomplete: {scaffold}")
        failures = sum(not row["outcome"]["conformant"] for row in arm)
        counts[scaffold] = {"failures": failures, "passes": 20 - failures}
    eligible = [scaffold for scaffold in SCAFFOLDS if 4 <= counts[scaffold]["failures"] <= 8]
    selected = (
        min(
            eligible,
            key=lambda scaffold: (abs(counts[scaffold]["failures"] - 6), SCAFFOLDS.index(scaffold)),
        )
        if eligible
        else None
    )
    return {
        "decision": "PROCEED_MAIN" if selected else "HOLD_INSTRUMENT_RANGE_MISS",
        "per_scaffold": counts,
        "selected_scaffold": selected,
    }


def freeze_json(output: Path, value: Mapping[str, Any]) -> str:
    data = canonical_bytes(value)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError:
            if output.read_bytes() == data:
                return "unchanged"
            raise FileExistsError(f"refusing to replace frozen artifact: {output}")
        return "written"
    finally:
        temporary.unlink(missing_ok=True)


@click.group()
def cli() -> None:
    """Freeze or check the predictive-validity successor frame."""


@cli.command("freeze")
@click.option("--model-catalog", required=True, type=click.Path(path_type=Path))
@click.option("--endpoint-catalog", required=True, type=click.Path(path_type=Path))
@click.option("--transport-catalog", required=True, type=click.Path(path_type=Path))
@click.option("--transport-base-url", required=True)
@click.option("--base-commit", required=True)
@click.option("--layer-two", default=LAYER_TWO, type=click.Path(path_type=Path))
@click.option("--output", default=DEFAULT_OUTPUT, type=click.Path(path_type=Path))
def freeze_command(
    model_catalog: Path,
    endpoint_catalog: Path,
    transport_catalog: Path,
    transport_base_url: str,
    base_commit: str,
    layer_two: Path,
    output: Path,
) -> None:
    frame = build_frame(
        model_catalog=model_catalog,
        endpoint_catalog=endpoint_catalog,
        transport_catalog=transport_catalog,
        transport_base_url=transport_base_url,
        base_commit=base_commit,
        layer_two=layer_two,
    )
    result = freeze_json(output, frame)
    click.echo(f"{result}: {output} payload={frame['payload_sha256']}")


@cli.command("check")
@click.option("--model-catalog", required=True, type=click.Path(path_type=Path))
@click.option("--endpoint-catalog", required=True, type=click.Path(path_type=Path))
@click.option("--transport-catalog", required=True, type=click.Path(path_type=Path))
@click.option("--transport-base-url", required=True)
@click.option("--layer-two", default=LAYER_TWO, type=click.Path(path_type=Path))
@click.option("--output", default=DEFAULT_OUTPUT, type=click.Path(path_type=Path))
def check_command(
    model_catalog: Path,
    endpoint_catalog: Path,
    transport_catalog: Path,
    transport_base_url: str,
    layer_two: Path,
    output: Path,
) -> None:
    observed = _read_json(output)
    if not isinstance(observed, dict):
        raise TypeError("frame must be a JSON object")
    validate_frame(observed)
    rebuilt = build_frame(
        model_catalog=model_catalog,
        endpoint_catalog=endpoint_catalog,
        transport_catalog=transport_catalog,
        transport_base_url=transport_base_url,
        base_commit=observed["base_commit"],
        layer_two=layer_two,
    )
    if canonical_bytes(observed) != canonical_bytes(rebuilt):
        raise ValueError("frame does not reproduce byte-exact from the pinned inputs")
    click.echo(f"PASS: {output} payload={observed['payload_sha256']}")


if __name__ == "__main__":
    cli()
