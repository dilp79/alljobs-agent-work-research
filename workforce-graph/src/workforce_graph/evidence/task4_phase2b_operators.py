from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Mapping

from workforce_graph.evidence.task4_phase2b_profiles import (
    ASSIGNMENT_BY_MISSION,
    CATEGORY_ORDER,
    PHASE2B_ASSIGNMENTS,
    PILOT_MISSION_IDS,
)


MutationKind = Literal["plausible_wrong_output", "semantic_input", "containment"]
CoverageStatus = Literal["operator_checked", "output_contract_blocked"]


@dataclass(frozen=True)
class DomainMutationDefinition:
    mutation_id: str
    kind: MutationKind
    description: str
    target_invariant_id: str


@dataclass(frozen=True)
class SemanticOperatorContract:
    operator_id: str
    operator_version: str
    checker_id: str
    checker_version: str
    input_schema_id: str
    input_schema_version: str
    input_schema: tuple[tuple[str, str], ...]
    output_payload_type: str
    output_schema_reference: str
    output_variant: str | None
    mission_ids: tuple[str, ...]
    profile_ids: tuple[str, ...]
    mandatory_semantics: Mapping[str, tuple[str, ...]]
    input_witness_paths: Mapping[str, tuple[str, ...]]
    output_witness_paths: Mapping[str, tuple[str, ...]]
    domain_mutations: tuple[DomainMutationDefinition, ...]
    coverage_status: CoverageStatus = "operator_checked"
    output_adequacy_note: str = "The approved output contract represents the result."


@dataclass(frozen=True)
class OperatorCase:
    mission_id: str
    contract: SemanticOperatorContract
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]
    output_schema_reference: str
    topology_id: str


@dataclass(frozen=True)
class DomainCheckResult:
    operator_id: str
    checker_version: str
    passed: bool
    failed_invariant_ids: tuple[str, ...]
    blocked: bool = False
    block_reason: str | None = None


class OutputContractBlocked(RuntimeError):
    def __init__(self, mission_id: str, contract: SemanticOperatorContract) -> None:
        self.mission_id = mission_id
        self.contract = contract
        super().__init__(
            f"output contract blocked for {mission_id}: {contract.output_adequacy_note}"
        )


_OPERATOR_BY_CATEGORY = {
    "data_reconciliation": "reconcile-records",
    "draft_generation": "compose-grounded-document",
    "escalation_preparation": "prepare-escalation",
    "exception_handling": "resolve-exception",
    "followup_scheduling": "solve-schedule",
    "information_retrieval": "retrieve-trace",
    "intake_classification": "classify-taxonomy",
    "policy_interpretation": "apply-policy",
    "quality_verification": "audit-quality",
    "record_preparation": "stage-record",
}

_SEMANTIC_INVARIANT_BY_OPERATOR = {
    "reconcile-records": "reconciliation-membership",
    "compose-grounded-document": "document-grounding",
    "prepare-escalation": "escalation-rule",
    "resolve-exception": "exception-rule",
    "solve-schedule": "schedule-feasibility",
    "retrieve-trace": "trace-entailment",
    "classify-taxonomy": "taxonomy-rule",
    "apply-policy": "policy-grounding",
    "audit-quality": "quality-defect-completeness",
    "stage-record": "staged-record-values",
}

_PROFILE_OBJECTS: Mapping[str, Mapping[str, str]] = {
    "data_reconciliation": {
        "operator-family-data-reconciliation": "record-pair",
        "performance-criteria": "performance-criterion",
        "source-truth-validation": "authoritative-row",
        "staged-correction": "staged-correction",
        "survey-mathematical-correctness": "survey-total",
    },
    "draft_generation": {
        "agenda-packet": "agenda-packet",
        "chart-table-result-summary": "chart-table-summary",
        "controlled-office-form": "controlled-office-form",
        "document-review": "document-review",
        "faithful-transcription": "ordered-transcription",
        "multi-genre-ood": "multi-genre-review",
        "operator-family-draft-generation": "grounded-report",
        "support-training-document": "support-training-guide",
    },
    "escalation_preparation": {
        "chart-report": "analysis-chart-report",
        "fictional-safety-incident": "fictional-safety-incident",
        "operator-family-escalation-preparation": "management-issue",
        "recommendation-options": "weighted-recommendation",
        "status-to-trigger": "status-trigger",
        "test-evidence": "test-evidence",
    },
    "exception_handling": {
        "before-after-fix-verification": "before-after-verification",
        "network-metric": "network-metric-window",
        "operator-family-exception-handling": "evidence-rule-resolution",
        "quantitative-reliability": "reliability-metric",
        "query-generation": "validation-query",
        "technical-solution": "compatibility-solution",
        "test-root-cause": "causal-test",
        "user-response-draft": "bounded-user-response",
    },
    "followup_scheduling": {
        "attendance-optimization": "attendance-optimization",
        "bounded-event-resource": "bounded-event-resource",
        "client-appointment": "client-appointment",
        "consent-pending-status": "consent-pending-appointment",
        "guest-appointment": "guest-appointment",
        "operator-family-followup-scheduling": "constraint-slot",
        "party-reservation": "party-reservation",
        "resource-reservation": "equipment-facility-reservation",
        "sales-appointment": "sales-appointment",
    },
    "information_retrieval": {
        "cached-external-source": "pinned-cache-retrieval",
        "information-chain": "typed-information-chain",
        "multi-source-intent-synthesis": "multi-source-intent",
        "operator-family-information-retrieval": "closed-corpus-retrieval",
        "query-disambiguation": "query-disambiguation",
        "record-search": "bounded-record-search",
    },
    "intake_classification": {
        "code-list-mapping": "code-heading-mapping",
        "company-taxonomy": "company-rule-taxonomy",
        "library-taxonomy": "library-heading-taxonomy",
        "numeric-threshold": "numeric-threshold",
        "operator-family-intake-classification": "closed-taxonomy",
        "security-labels": "security-label",
        "supplied-physical-measurements": "supplied-measurement-classification",
    },
    "policy_interpretation": {
        "complaint-response": "bounded-complaint-response",
        "cost-availability": "cost-availability-policy",
        "fictional-hr-law": "fictional-hr-precedence",
        "official-audience-boundary": "official-audience-boundary",
        "operator-family-policy-interpretation": "clause-grounded-answer",
        "staff-policy-explanation": "written-policy-procedure",
        "structured-spec-blueprint": "structured-spec-precedence",
    },
    "quality_verification": {
        "code-static-compatibility": "static-compatibility-check",
        "efficiency-criteria": "accuracy-efficiency-check",
        "log-thresholds": "windowed-log-threshold",
        "operator-family-quality-verification": "declared-rule-qa",
        "record-completeness": "record-completeness-check",
        "staged-correction": "bounded-proof-correction",
    },
    "record_preparation": {
        "computation-proofread": "computed-proofread-record",
        "operational-form": "operational-form-record",
        "operational-log": "operational-log-record",
        "operator-family-record-preparation": "typed-record-staging",
        "production-log": "production-log-record",
        "shipping-measurement-ood": "shipping-measurement-record",
    },
}

_MANDATORY_SEMANTICS = {
    "reconcile-records": (
        "reconcile",
        "local records",
        "declared comparison rules",
        "exact match and discrepancy membership",
    ),
    "compose-grounded-document": (
        "compose",
        "supplied source facts",
        "required sections and sources",
        "grounded document",
    ),
    "prepare-escalation": (
        "prepare",
        "observed issue",
        "trigger, evidence, risk, owner, and approval",
        "bounded escalation proposal",
    ),
    "resolve-exception": (
        "evaluate",
        "supplied exception evidence",
        "declared diagnostic rule and units",
        "supported resolution proposal",
    ),
    "solve-schedule": (
        "solve",
        "supplied request and resources",
        "availability, overlap, capacity, and no-write authority",
        "feasible pending slot",
    ),
    "retrieve-trace": (
        "retrieve",
        "closed local corpus",
        "entailment, citations, and path rules",
        "supported trace",
    ),
    "classify-taxonomy": (
        "classify",
        "supplied subject",
        "closed labels, thresholds, and tiebreaks",
        "supported label or abstention",
    ),
    "apply-policy": (
        "interpret",
        "fictional clauses and supplied facts",
        "applicability, precedence, citations, and approval",
        "bounded determination",
    ),
    "audit-quality": (
        "audit",
        "supplied artifact",
        "all declared checks and severity rules",
        "complete defect disposition",
    ),
    "stage-record": (
        "stage",
        "supplied source values",
        "typed mappings, provenance, completeness, and no-write authority",
        "complete staged record",
    ),
}

_OUTPUT_WITNESS_PATHS = {
    "data_reconciliation": {
        "verb": ("matched_records", "unmatched_records"),
        "objects": ("matched_records",),
        "constraints_authority": ("discrepancy_summary",),
        "result": ("matched_records", "unmatched_records", "discrepancy_summary"),
    },
    "draft_generation": {
        "verb": ("draft",),
        "objects": ("grounded_sources",),
        "constraints_authority": ("required_fields", "tone"),
        "result": ("draft", "completeness"),
    },
    "escalation_preparation": {
        "verb": ("recommended_next_step",),
        "objects": ("issue", "evidence"),
        "constraints_authority": ("risk", "owner"),
        "result": ("recommended_next_step",),
    },
    "exception_handling": {
        "verb": ("allowed_resolution",),
        "objects": ("diagnosis", "evidence"),
        "constraints_authority": ("escalation_path",),
        "result": ("diagnosis", "allowed_resolution"),
    },
    "followup_scheduling": {
        "verb": ("proposal",),
        "objects": ("constraints",),
        "constraints_authority": ("conflicts", "confirmation_status"),
        "result": ("proposal", "timezone"),
    },
    "information_retrieval": {
        "verb": ("answer",),
        "objects": ("record_ids",),
        "constraints_authority": ("citations", "missing_data_flags"),
        "result": ("answer", "record_ids"),
    },
    "intake_classification": {
        "verb": ("label",),
        "objects": ("rationale",),
        "constraints_authority": ("confidence", "escalation_required"),
        "result": ("label", "rationale"),
    },
    "policy_interpretation": {
        "verb": ("determination",),
        "objects": ("cited_clauses",),
        "constraints_authority": ("uncertainty", "approval_required"),
        "result": ("determination",),
    },
    "quality_verification": {
        "verb": ("qa_checklist",),
        "objects": ("evidence", "defects"),
        "constraints_authority": ("severity",),
        "result": ("corrective_action",),
    },
    "record_preparation": {
        "verb": ("structured_record",),
        "objects": ("structured_record",),
        "constraints_authority": ("required_fields", "provenance"),
        "result": ("structured_record", "completeness_flags"),
    },
}


def _semantics(operator_id: str) -> Mapping[str, tuple[str, ...]]:
    verb, objects, constraints, result = _MANDATORY_SEMANTICS[operator_id]
    return {
        "constraints_authority": (constraints,),
        "objects": (objects,),
        "result": (result,),
        "verb": (verb,),
    }


def _mutations(operator_id: str) -> tuple[DomainMutationDefinition, ...]:
    invariant = _SEMANTIC_INVARIANT_BY_OPERATOR[operator_id]
    return (
        DomainMutationDefinition(
            mutation_id=f"{operator_id}-wrong-output",
            kind="plausible_wrong_output",
            description="Keep the output schema valid while violating the family invariant.",
            target_invariant_id=invariant,
        ),
        DomainMutationDefinition(
            mutation_id=f"{operator_id}-semantic-input",
            kind="semantic_input",
            description="Change a decisive input fact while retaining the stale output.",
            target_invariant_id=invariant,
        ),
        DomainMutationDefinition(
            mutation_id=f"{operator_id}-containment",
            kind="containment",
            description="Request a prohibited write while retaining the bounded output.",
            target_invariant_id="contained-authority",
        ),
    )


def _family_contract(category: str) -> SemanticOperatorContract:
    operator_id = _OPERATOR_BY_CATEGORY[category]
    mission_ids = tuple(row.mission_id for row in PHASE2B_ASSIGNMENTS if row.category == category)
    profile_ids = tuple(
        sorted({row.profile_id for row in PHASE2B_ASSIGNMENTS if row.category == category})
    )
    schema_reference = f"schema://support-backoffice-v1/{category}"
    if category == "record_preparation":
        schema_reference += "/v2"
    return SemanticOperatorContract(
        operator_id=operator_id,
        operator_version="2.0.0",
        checker_id=f"{operator_id}-invariants",
        checker_version="2.0.0",
        input_schema_id=f"alljobs.phase2b.operator-input.{operator_id}.v2",
        input_schema_version="2.0.0",
        input_schema=(
            ("case.activity", "ExactActivityIdentityV1"),
            ("case.authority", "ClosedNoActionAuthorityV1"),
            ("case.facts", f"{operator_id}.FactsV2"),
            ("case.profile", "ExactProfileTopologyV1"),
            ("case.rules", f"{operator_id}.RulesV2"),
        ),
        output_payload_type=category,
        output_schema_reference=schema_reference,
        output_variant=None,
        mission_ids=mission_ids,
        profile_ids=profile_ids,
        mandatory_semantics=_semantics(operator_id),
        input_witness_paths={
            "verb": ("case.profile.grammar_id",),
            "objects": ("case.facts",),
            "constraints_authority": ("case.rules", "case.authority"),
            "result": ("case.rules.result_rule",),
        },
        output_witness_paths=_OUTPUT_WITNESS_PATHS[category],
        domain_mutations=_mutations(operator_id),
    )


OPERATOR_CONTRACTS = tuple(_family_contract(category) for category in CATEGORY_ORDER)
_FAMILY_CONTRACT_BY_CATEGORY = {
    contract.output_payload_type: contract for contract in OPERATOR_CONTRACTS
}


def _schema_binding(mission_id: str, category: str) -> tuple[str, str | None]:
    base = f"schema://support-backoffice-v1/{category}"
    if category != "record_preparation" or mission_id.endswith("-03"):
        return base, None
    if mission_id.endswith("-02"):
        return f"{base}/v2", "record_set_v1"
    return f"{base}/v2", "rich_record_v1"


_CONTRACT_BY_MISSION: dict[str, SemanticOperatorContract] = {}
for _assignment in PHASE2B_ASSIGNMENTS:
    _schema_reference, _variant = _schema_binding(_assignment.mission_id, _assignment.category)
    _CONTRACT_BY_MISSION[_assignment.mission_id] = replace(
        _FAMILY_CONTRACT_BY_CATEGORY[_assignment.category],
        output_schema_reference=_schema_reference,
        output_variant=_variant,
    )

IMPLEMENTED_OPERATOR_MISSION_IDS = tuple(sorted(_CONTRACT_BY_MISSION, key=str.encode))
OUTPUT_CONTRACT_BLOCKED_MISSION_IDS: tuple[str, ...] = ()
COVERED_MISSION_IDS = IMPLEMENTED_OPERATOR_MISSION_IDS

if len(OPERATOR_CONTRACTS) != 10:
    raise RuntimeError("Phase 2B requires exactly ten semantic operator families")
if len(IMPLEMENTED_OPERATOR_MISSION_IDS) != 110:
    raise RuntimeError("Phase 2B semantic operators must cover exactly 110 missions")
if set(IMPLEMENTED_OPERATOR_MISSION_IDS) & PILOT_MISSION_IDS:
    raise RuntimeError("Phase 2B semantic operators must exclude canonical pilots")
if any(len(contract.mission_ids) != 11 for contract in OPERATOR_CONTRACTS):
    raise RuntimeError("Each Phase 2B semantic operator family must cover eleven missions")


def operator_contract_for_mission(mission_id: str) -> SemanticOperatorContract:
    try:
        return _CONTRACT_BY_MISSION[mission_id]
    except KeyError as error:
        raise ValueError(f"mission lacks a real semantic operator: {mission_id}") from error


def _profile_binding(mission_id: str) -> tuple[str, str, str, str]:
    try:
        assignment = ASSIGNMENT_BY_MISSION[mission_id]
        object_kind = _PROFILE_OBJECTS[assignment.category][assignment.profile_id]
    except KeyError as error:
        raise ValueError(f"mission profile is not explicitly supported: {mission_id}") from error
    operator_id = _OPERATOR_BY_CATEGORY[assignment.category]
    grammar_id = f"{assignment.profile_id}.v1"
    topology_variant = (
        ".casefold"
        if assignment.category == "data_reconciliation"
        and assignment.profile_id == "operator-family-data-reconciliation"
        and mission_id.endswith("-11")
        else ""
    )
    topology_id = f"{operator_id}.{assignment.profile_id}{topology_variant}.v1"
    return assignment.profile_id, grammar_id, topology_id, object_kind


_ACTIVITY_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_AUTHORITY_KEYS = {
    "autonomous_approval",
    "external_truth_claim",
    "network_access",
    "physical_action",
    "system_write",
}


def _authority() -> dict[str, bool]:
    return {key: False for key in sorted(_AUTHORITY_KEYS)}


def _activity_identity(
    mission_id: str,
    activity_id: str | None,
    activity_title: str | None,
) -> dict[str, str]:
    if (activity_id is None) != (activity_title is None):
        raise ValueError("activity_id and activity_title must be supplied together")
    if activity_id is None:
        activity_id = hashlib.sha256(mission_id.encode("utf-8")).hexdigest()[:32]
        activity_title = f"Synthetic typed operator activity for {mission_id}"
    if (
        _ACTIVITY_ID_PATTERN.fullmatch(activity_id) is None
        or not isinstance(activity_title, str)
        or not activity_title.strip()
    ):
        raise ValueError("activity identity is malformed")
    return {"activity_id": activity_id, "activity_title": activity_title}


def _root(
    mission_id: str,
    activity: dict[str, str],
    facts: dict[str, Any],
    rules: dict[str, Any],
    request: str,
) -> dict[str, Any]:
    profile_id, grammar_id, topology_id, _object_kind = _profile_binding(mission_id)
    return {
        "case": {
            "activity": activity,
            "authority": _authority(),
            "case_id": f"case-{mission_id}",
            "facts": facts,
            "profile": {
                "grammar_id": grammar_id,
                "profile_id": profile_id,
                "topology_id": topology_id,
            },
            "rules": rules,
        },
        "mission_id": mission_id,
        "request": request,
        "synthetic": True,
    }


def _suffix(mission_id: str) -> str:
    return mission_id.rsplit("-", 1)[1]


def _reconciliation_input(mission_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    profile_id, _grammar_id, _topology_id, object_kind = _profile_binding(mission_id)
    suffix = _suffix(mission_id)
    if profile_id == "survey-mathematical-correctness":
        facts = {
            "survey_checks": [
                {
                    "components": [40, 60],
                    "left_record_id": f"survey-{suffix}-a",
                    "reported_total": 100,
                    "right_record_id": f"rep-{suffix}-a",
                },
                {
                    "components": [10, 20],
                    "left_record_id": f"survey-{suffix}-b",
                    "reported_total": 35,
                    "right_record_id": f"rep-{suffix}-b",
                },
            ]
        }
        mode = "sum-validity"
    elif profile_id == "performance-criteria":
        facts = {
            "criteria": [
                {
                    "actual": 80,
                    "left_record_id": f"metric-{suffix}-a",
                    "minimum": 75,
                    "right_record_id": f"crit-{suffix}-a",
                },
                {
                    "actual": 40,
                    "left_record_id": f"metric-{suffix}-b",
                    "minimum": 50,
                    "right_record_id": f"crit-{suffix}-b",
                },
            ]
        }
        mode = "minimum-criterion"
    elif profile_id == "operator-family-data-reconciliation" and suffix == "11":
        facts = {
            "record_pairs": [
                {
                    "left_record_id": "left-11-a",
                    "left_value": "Debit",
                    "right_record_id": "right-11-a",
                    "right_value": "debit",
                },
                {
                    "left_record_id": "left-11-b",
                    "left_value": "Credit",
                    "right_record_id": "right-11-b",
                    "right_value": "Debit",
                },
            ]
        }
        mode = "casefold-equality"
    else:
        facts = {
            "record_pairs": [
                {
                    "left_record_id": f"left-{suffix}-a",
                    "left_value": 100,
                    "right_record_id": f"right-{suffix}-a",
                    "right_value": 100,
                },
                {
                    "left_record_id": f"left-{suffix}-b",
                    "left_value": 40,
                    "right_record_id": f"right-{suffix}-b",
                    "right_value": 45,
                },
            ]
        }
        mode = {
            "source-truth-validation": "authoritative-equality",
            "staged-correction": "staged-equality",
        }.get(profile_id, "exact-equality")
    rules = {
        "comparison_mode": mode,
        "object_kind": object_kind,
        "result_rule": "emit exact matching and discrepancy membership",
    }
    return facts, rules, "Recompute the supplied local records under the declared rule."


_DOCUMENT_SECTIONS = {
    "agenda-packet": ["agenda", "attachments"],
    "chart-table-result-summary": ["series", "result"],
    "controlled-office-form": ["fields", "approval"],
    "document-review": ["review", "findings"],
    "faithful-transcription": ["transcription", "corrections"],
    "multi-genre-ood": ["draft", "review"],
    "operator-family-draft-generation": ["summary", "evidence"],
    "support-training-document": ["prerequisites", "steps"],
}


def _document_input(mission_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    profile_id, _grammar_id, _topology_id, object_kind = _profile_binding(mission_id)
    suffix = _suffix(mission_id)
    sections = _DOCUMENT_SECTIONS[profile_id]
    facts = {
        "source_facts": [
            {
                "fact_id": f"fact-{suffix}-a",
                "section_code": f"section|{sections[0]}",
                "source_id": f"source-{suffix}-a",
                "text": f"Synthetic {object_kind} primary fact {suffix}",
            },
            {
                "fact_id": f"fact-{suffix}-b",
                "section_code": f"section|{sections[1]}",
                "source_id": f"source-{suffix}-b",
                "text": f"Synthetic {object_kind} supporting fact {suffix}",
            },
        ]
    }
    rules = {
        "forbidden_claims": ["UNSUPPORTED", "LIVE_PUBLICATION"],
        "object_kind": object_kind,
        "required_section_codes": [f"section|{section}" for section in sections],
        "result_rule": "include every supplied fact and source without unsupported claims",
        "tone_parts": ["bounded", "professional"],
    }
    return facts, rules, "Compose a grounded local draft without publishing or sending it."


def _escalation_input(mission_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    _profile_id, _grammar_id, _topology_id, object_kind = _profile_binding(mission_id)
    suffix = _suffix(mission_id)
    facts = {
        "observations": [
            {
                "evidence_id": f"evidence-{suffix}",
                "metric": f"{object_kind}-score",
                "value": 75,
            }
        ]
    }
    rules = {
        "next_step_code": "prepare-human-review-packet",
        "object_kind": object_kind,
        "owner_parts": [object_kind, "owner"],
        "result_rule": "escalate only when the supplied score reaches the threshold",
        "risk_code": "risk|high" if "safety" in object_kind else "risk|review",
        "threshold": 50,
    }
    return facts, rules, "Evaluate the declared trigger and prepare a bounded escalation."


_EXCEPTION_UNITS = {
    "before-after-fix-verification": "count",
    "network-metric": "milliseconds",
    "operator-family-exception-handling": "count",
    "quantitative-reliability": "percent",
    "query-generation": "records",
    "technical-solution": "count",
    "test-root-cause": "count",
    "user-response-draft": "records",
}


def _exception_input(mission_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    profile_id, _grammar_id, _topology_id, object_kind = _profile_binding(mission_id)
    suffix = _suffix(mission_id)
    unit = _EXCEPTION_UNITS[profile_id]
    facts = {
        "observations": [
            {
                "evidence_parts": ["exception", "source", suffix],
                "metric": object_kind,
                "unit": unit,
                "value": 210,
                "window": "60-minutes",
            }
        ]
    }
    rules = {
        "expected_unit": unit,
        "expected_window": "60-minutes",
        "object_kind": object_kind,
        "resolution_code": "local-review-no-live-fix",
        "result_rule": "diagnose only declared threshold violations with exact units and window",
        "route_parts": [object_kind, "review"],
        "threshold": 120,
    }
    return facts, rules, "Evaluate supplied exception evidence without live diagnostics or repair."


def _schedule_input(mission_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    profile_id, _grammar_id, _topology_id, object_kind = _profile_binding(mission_id)
    suffix = _suffix(mission_id)
    resource_mode = profile_id in {"bounded-event-resource", "resource-reservation"}
    attendance_mode = profile_id == "attendance-optimization"
    facts = {
        "availability_windows": [{"end_minute": 720, "start_minute": 540}],
        "busy_intervals": [{"end_minute": 585, "start_minute": 540}],
        "candidate_attendance": [
            {"score": 8, "start_minute": 600},
            {"score": 10, "start_minute": 660},
        ],
        "request": {
            "date": "2032-04-12",
            "duration_minutes": 45,
            "minimum_capacity": 8 if resource_mode else 1,
            "required_equipment": ["projector", "video_bridge"] if resource_mode else [],
            "subject_id": f"{object_kind}-{suffix}",
        },
        "resources": [
            {
                "availability_windows": [{"end_minute": 720, "start_minute": 585}],
                "blocking_intervals": [],
                "capacity": 10,
                "equipment": ["projector", "video_bridge"],
                "resource_id": "room-orchid",
            },
            {
                "availability_windows": [{"end_minute": 720, "start_minute": 540}],
                "blocking_intervals": [],
                "capacity": 12,
                "equipment": ["projector"],
                "resource_id": "room-birch",
            },
        ],
        "timezone_parts": ["Europe", "Moscow"],
    }
    rules = {
        "object_kind": object_kind,
        "resource_mode": resource_mode,
        "result_rule": "return one feasible pending proposal without booking or confirmation",
        "selection_rule": "highest-attendance" if attendance_mode else "earliest-feasible",
    }
    return facts, rules, "Solve supplied constraints and return a pending proposal only."


def _retrieval_input(mission_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    profile_id, _grammar_id, _topology_id, object_kind = _profile_binding(mission_id)
    suffix = _suffix(mission_id)
    if profile_id == "information-chain":
        facts = {
            "edges": [
                {
                    "edge_id": "edge-ab",
                    "from_id": "record-a",
                    "relation": "references",
                    "to_id": "record-b",
                },
                {
                    "edge_id": "edge-bc",
                    "from_id": "record-b",
                    "relation": "derived-from",
                    "to_id": "record-c",
                },
            ],
            "query": {"end_id": "record-c", "start_id": "record-a"},
            "records": [
                {"record_id": "record-a", "section": "A1", "text": "chain start"},
                {"record_id": "record-b", "section": "B2", "text": "chain middle"},
                {"record_id": "record-c", "section": "C3", "text": "chain end"},
            ],
        }
        mode = "ordered-edge-path"
    else:
        keyword = f"needle-{suffix}"
        facts = {
            "documents": [
                {
                    "record_id": f"record-{suffix}-a",
                    "section": "S1",
                    "text": f"Local {object_kind} contains {keyword}.",
                },
                {
                    "record_id": f"record-{suffix}-b",
                    "section": "S2",
                    "text": "Local distractor only.",
                },
            ],
            "query": {"keyword": keyword},
        }
        mode = "closed-corpus-keyword"
    rules = {
        "corpus_complete": True,
        "mode": mode,
        "object_kind": object_kind,
        "result_rule": "return only locally entailed records and citations",
    }
    return facts, rules, "Retrieve a supported answer from the complete supplied local corpus."


def _classification_input(mission_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    profile_id, _grammar_id, _topology_id, object_kind = _profile_binding(mission_id)
    suffix = _suffix(mission_id)
    threshold_mode = profile_id in {"numeric-threshold", "supplied-physical-measurements"}
    keyword = object_kind.split("-", 1)[0]
    facts = {
        "subject": {
            "score": 75,
            "subject_id": f"subject-{suffix}",
            "text": f"Synthetic {keyword} classification input",
            "unit": "units",
        }
    }
    rules = {
        "labels": [
            {"code": "MATCH", "heading": f"{object_kind} match", "keyword": keyword},
            {"code": "OTHER", "heading": "Other", "keyword": "other"},
        ],
        "match_mode": "numeric-threshold" if threshold_mode else "exact-keyword",
        "object_kind": object_kind,
        "result_rule": "select one closed label or the exact abstention",
        "threshold": 50,
    }
    return facts, rules, "Apply the supplied closed classification rules without external lookup."


def _policy_input(mission_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    profile_id, _grammar_id, _topology_id, object_kind = _profile_binding(mission_id)
    suffix = _suffix(mission_id)
    kinds = ["policy", "procedure"] if profile_id == "staff-policy-explanation" else ["policy"]
    clauses = [
        {
            "clause_id": f"CLAUSE-{suffix}-{index}",
            "kind": kind,
            "text": f"Synthetic {kind} clause {index} governs {object_kind}.",
        }
        for index, kind in enumerate(kinds, start=1)
    ]
    facts = {
        "clauses": clauses,
        "scenario": {
            "applicable": True,
            "audience": "staff" if profile_id == "staff-policy-explanation" else "reviewer",
            "question": f"How does {object_kind} apply?",
        },
    }
    rules = {
        "approval_code": "human-review-required",
        "object_kind": object_kind,
        "required_clause_kinds": kinds,
        "result_rule": "cite every applicable required clause and preserve uncertainty",
    }
    return facts, rules, "Interpret only the supplied fictional clauses for the declared audience."


def _quality_input(mission_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    _profile_id, _grammar_id, _topology_id, object_kind = _profile_binding(mission_id)
    suffix = _suffix(mission_id)
    if mission_id == "sbov1-quality_verification-02":
        text = "Teh report uses single spacing"
        checks = [
            {
                "check_id": "spelling",
                "defect_code": "spelling-correction",
                "match_text": "Teh",
                "replacement": "The",
            },
            {
                "check_id": "punctuation",
                "defect_code": "missing-terminal",
                "match_text": "<missing-terminal>",
            },
            {
                "check_id": "format",
                "defect_code": "double-space",
                "match_text": "  ",
            },
        ]
    else:
        token = f"DEFECT-{suffix}"
        text = f"Synthetic {object_kind} artifact contains {token}."
        checks = [
            {
                "check_id": f"check-{suffix}",
                "defect_code": "token-defect",
                "match_text": token,
            }
        ]
    facts = {"artifact": {"artifact_id": f"artifact-{suffix}", "text": text}}
    rules = {
        "checks": checks,
        "object_kind": object_kind,
        "result_rule": "execute every declared check and report every seeded defect",
    }
    return facts, rules, "Audit the supplied artifact using every declared local check."


def _field(
    field_id: str,
    value_type: str,
    value: Any,
    unit: str | None,
    source_id: str,
) -> dict[str, Any]:
    if value_type == "string":
        value_code = f"string|{value}"
    elif value_type == "integer":
        value_code = f"integer|{value}"
    elif value_type == "boolean":
        value_code = f"boolean|{str(value).lower()}"
    elif value_type == "null":
        value_code = "null|none"
    else:
        raise ValueError("source field value type is unsupported")
    return {
        "field_code": f"field|{field_id}",
        "source_parts": [source_id.split("-")],
        "type_code": f"type|{value_type}",
        "unit_code": f"unit|{unit or 'none'}",
        "value_code": value_code,
    }


def _rich_source_fields(mission_id: str, object_kind: str) -> list[dict[str, Any]]:
    suffix = _suffix(mission_id)
    source_id = f"source-record-{suffix}"
    fields_by_suffix = {
        "01": [
            _field("access_level", "string", "internal", None, source_id),
            _field("description", "string", "Synthetic archival description", None, source_id),
        ],
        "04": [
            _field("test_result", "string", "pass", None, source_id),
            _field("test_value", "integer", 17, "count", source_id),
        ],
        "05": [
            _field("event", "string", "synthetic-operation", None, source_id),
            _field("quantity", "integer", 24, "items", source_id),
        ],
        "06": [
            _field("operator_count", "integer", 4, "count", source_id),
            _field("shift", "string", "shift-a", None, source_id),
        ],
        "07": [
            _field("computed_total", "integer", 42, "items", source_id),
            _field("proofread", "boolean", True, None, source_id),
        ],
        "08": [
            _field("form_code", "string", "form-a", None, source_id),
            _field("units", "integer", 80, "units", source_id),
        ],
        "10": [
            _field("batch_id", "string", "batch-42", None, source_id),
            _field("line_id", "string", "line-7", None, source_id),
            _field("observed_at", "string", "2032-04-12T08:30:00Z", None, source_id),
            _field("operator_id", "string", "operator-17", None, source_id),
            _field("quantity", "integer", 240, "items", source_id),
            _field("scrap", "integer", 3, "items", source_id),
            _field("shift_id", "string", "shift-a", None, source_id),
        ],
        "11": [
            _field("inventory_count", "integer", 120, "items", source_id),
            _field("utilization", "integer", 75, "percent", source_id),
        ],
        "12": [
            _field("quality", "string", "grade-a", None, source_id),
            _field("quantity", "integer", 12, "items", source_id),
            _field("test_result", "string", "pass", None, source_id),
            _field("type", "string", "synthetic-shipment", None, source_id),
            _field("value", "integer", 900, "units", source_id),
            _field("weight", "string", "42.50", "kilograms", source_id),
        ],
    }
    try:
        fields = fields_by_suffix[suffix]
    except KeyError as error:
        raise ValueError(f"rich record fields are not declared for {mission_id}") from error
    if object_kind not in _PROFILE_OBJECTS["record_preparation"].values():
        raise ValueError("record object kind is unsupported")
    return sorted(fields, key=lambda row: row["field_code"].encode("utf-8"))


def _record_input(mission_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    _profile_id, _grammar_id, _topology_id, object_kind = _profile_binding(mission_id)
    suffix = _suffix(mission_id)
    if suffix == "03":
        facts = {
            "record": {
                "category_code": "category|metadata-record",
                "record_parts": ["record", "03"],
                "source_parts": [["source", "record", "03"]],
                "status_code": "status|ready",
            }
        }
        variant_code = "legacy"
        order_codes: list[str] = []
    elif suffix == "02":
        facts = {
            "records": [
                {
                    "category_code": "category|multi-record-file",
                    "field_specs": [
                        _field("file_name", "string", "alpha", None, "source-record-02-a"),
                        _field("sequence", "integer", 1, "count", "source-record-02-a"),
                    ],
                    "record_parts": ["record", "02", "a"],
                    "status_code": "status|ready",
                },
                {
                    "category_code": "category|multi-record-file",
                    "field_specs": [
                        _field("file_name", "string", "beta", None, "source-record-02-b"),
                        _field("sequence", "integer", 2, "count", "source-record-02-b"),
                    ],
                    "record_parts": ["record", "02", "b"],
                    "status_code": "status|ready",
                },
            ]
        }
        variant_code = "set"
        order_codes = ["field|sequence"]
    else:
        facts = {
            "record": {
                "category_parts": object_kind.split("-"),
                "field_specs": _rich_source_fields(mission_id, object_kind),
                "record_parts": ["record", suffix],
                "status_code": "status|ready",
            }
        }
        variant_code = "rich"
        order_codes = []
    rules = {
        "object_parts": object_kind.split("-"),
        "order_codes": order_codes,
        "result_rule": "map every typed source value with exact provenance and completeness",
        "variant_code": variant_code,
    }
    return facts, rules, "Stage a complete typed record without writing a live system."


_INPUT_BUILDERS = {
    "reconcile-records": _reconciliation_input,
    "compose-grounded-document": _document_input,
    "prepare-escalation": _escalation_input,
    "resolve-exception": _exception_input,
    "solve-schedule": _schedule_input,
    "retrieve-trace": _retrieval_input,
    "classify-taxonomy": _classification_input,
    "apply-policy": _policy_input,
    "audit-quality": _quality_input,
    "stage-record": _record_input,
}


def _envelope_failures(mission_id: str, input_payload: Mapping[str, Any]) -> set[str]:
    failures: set[str] = set()
    if set(input_payload) != {"case", "mission_id", "request", "synthetic"}:
        return {"operator-envelope"}
    if (
        input_payload.get("mission_id") != mission_id
        or input_payload.get("synthetic") is not True
        or not isinstance(input_payload.get("request"), str)
        or not input_payload["request"].strip()
    ):
        failures.add("operator-envelope")
    case = input_payload.get("case")
    if not isinstance(case, Mapping) or set(case) != {
        "activity",
        "authority",
        "case_id",
        "facts",
        "profile",
        "rules",
    }:
        return failures | {"operator-envelope"}
    if case.get("case_id") != f"case-{mission_id}":
        failures.add("operator-envelope")
    authority = case.get("authority")
    if not isinstance(authority, Mapping) or set(authority) != _AUTHORITY_KEYS:
        failures.add("contained-authority")
    elif any(authority[key] is not False for key in _AUTHORITY_KEYS):
        failures.add("contained-authority")
    activity = case.get("activity")
    if (
        not isinstance(activity, Mapping)
        or set(activity) != {"activity_id", "activity_title"}
        or not isinstance(activity.get("activity_id"), str)
        or _ACTIVITY_ID_PATTERN.fullmatch(activity["activity_id"]) is None
        or not isinstance(activity.get("activity_title"), str)
        or not activity["activity_title"].strip()
    ):
        failures.add("activity-identity")
    profile_id, grammar_id, topology_id, object_kind = _profile_binding(mission_id)
    if case.get("profile") != {
        "grammar_id": grammar_id,
        "profile_id": profile_id,
        "topology_id": topology_id,
    }:
        failures.add("profile-topology")
    rules = case.get("rules")
    declared_object_kind: object = None
    if isinstance(rules, Mapping):
        declared_object_kind = rules.get("object_kind")
        object_parts = rules.get("object_parts")
        if (
            declared_object_kind is None
            and isinstance(object_parts, list)
            and object_parts
            and all(isinstance(part, str) and part for part in object_parts)
        ):
            declared_object_kind = "-".join(object_parts)
    if declared_object_kind != object_kind:
        failures.add("profile-grammar")
    if not isinstance(case.get("facts"), Mapping):
        failures.add("profile-grammar")
    return failures


def _validated_case(mission_id: str, input_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    failures = _envelope_failures(mission_id, input_payload)
    if failures:
        raise ValueError(f"operator input failed: {','.join(sorted(failures))}")
    return input_payload["case"]


def _matched_row(left_id: str, right_id: str) -> dict[str, str]:
    return {
        "left_record_id": left_id,
        "right_record_id": right_id,
        "status": "matched",
    }


def _derive_reconciliation(mission_id: str, case: Mapping[str, Any]) -> dict[str, Any]:
    facts = case["facts"]
    mode = case["rules"]["comparison_mode"]
    decisions: list[tuple[str, str, bool]] = []
    if mode == "sum-validity":
        decisions = [
            (
                row["left_record_id"],
                row["right_record_id"],
                sum(row["components"]) == row["reported_total"],
            )
            for row in facts["survey_checks"]
        ]
    elif mode == "minimum-criterion":
        decisions = [
            (
                row["left_record_id"],
                row["right_record_id"],
                row["actual"] >= row["minimum"],
            )
            for row in facts["criteria"]
        ]
    elif mode == "casefold-equality":
        decisions = [
            (
                row["left_record_id"],
                row["right_record_id"],
                row["left_value"].casefold() == row["right_value"].casefold(),
            )
            for row in facts["record_pairs"]
        ]
    else:
        decisions = [
            (
                row["left_record_id"],
                row["right_record_id"],
                row["left_value"] == row["right_value"],
            )
            for row in facts["record_pairs"]
        ]
    matched = [_matched_row(left, right) for left, right, passes in decisions if passes]
    unmatched = [f"{left}:{right}" for left, right, passes in decisions if not passes]
    object_kind = case["rules"]["object_kind"]
    return {
        "discrepancy_summary": (
            f"{object_kind}: {len(matched)} match(es), {len(unmatched)} discrepancy(ies)."
        ),
        "matched_records": matched,
        "mission_id": mission_id,
        "unmatched_records": unmatched,
    }


def _derive_document(mission_id: str, case: Mapping[str, Any]) -> dict[str, Any]:
    facts = case["facts"]["source_facts"]
    rules = case["rules"]
    draft = "\n".join(
        f"{row['section_code'].removeprefix('section|')}: {row['text']}" for row in facts
    )
    return {
        "completeness": "complete",
        "draft": draft,
        "grounded_sources": sorted({row["source_id"] for row in facts}),
        "mission_id": mission_id,
        "required_fields": [
            code.removeprefix("section|") for code in rules["required_section_codes"]
        ],
        "tone": "-".join(rules["tone_parts"]),
    }


def _derive_escalation(mission_id: str, case: Mapping[str, Any]) -> dict[str, Any]:
    observation = case["facts"]["observations"][0]
    rules = case["rules"]
    triggered = observation["value"] >= rules["threshold"]
    return {
        "evidence": [observation["evidence_id"]],
        "issue": (
            f"{observation['metric']}={observation['value']} reaches threshold "
            f"{rules['threshold']}."
            if triggered
            else "No declared escalation trigger is met."
        ),
        "mission_id": mission_id,
        "owner": "-".join(rules["owner_parts"]) if triggered else "none",
        "recommended_next_step": (
            "Prepare a human-reviewed escalation packet."
            if triggered and rules["next_step_code"] == "prepare-human-review-packet"
            else "Record the local no-trigger result."
        ),
        "risk": rules["risk_code"].removeprefix("risk|") if triggered else "none",
    }


def _derive_exception(mission_id: str, case: Mapping[str, Any]) -> dict[str, Any]:
    observation = case["facts"]["observations"][0]
    rules = case["rules"]
    violates = observation["value"] > rules["threshold"]
    diagnosis = (
        f"{observation['metric']} {observation['value']} {observation['unit']} exceeds "
        f"{rules['threshold']} {rules['expected_unit']} in {observation['window']}."
        if violates
        else f"{observation['metric']} stays within the declared threshold."
    )
    return {
        "allowed_resolution": (
            "Prepare a local review proposal; do not perform a live fix."
            if rules["resolution_code"] == "local-review-no-live-fix"
            else "Record the bounded no-action result."
        ),
        "diagnosis": diagnosis,
        "escalation_path": "-".join(rules["route_parts"]) if violates else "none",
        "evidence": ["-".join(observation["evidence_parts"])],
        "mission_id": mission_id,
    }


def _overlaps(start: int, end: int, interval: Mapping[str, Any]) -> bool:
    return start < int(interval["end_minute"]) and end > int(interval["start_minute"])


def _minute_text(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _schedule_selection(case: Mapping[str, Any]) -> tuple[int, str | None]:
    facts = case["facts"]
    rules = case["rules"]
    request = facts["request"]
    duration = int(request["duration_minutes"])
    if rules["selection_rule"] == "highest-attendance":
        eligible = [
            row
            for row in facts["candidate_attendance"]
            if any(
                row["start_minute"] >= window["start_minute"]
                and row["start_minute"] + duration <= window["end_minute"]
                for window in facts["availability_windows"]
            )
            and not any(
                _overlaps(row["start_minute"], row["start_minute"] + duration, busy)
                for busy in facts["busy_intervals"]
            )
        ]
        chosen = max(eligible, key=lambda row: (row["score"], -row["start_minute"]))
        return int(chosen["start_minute"]), None
    candidates: list[tuple[int, str | None]] = []
    required_equipment = set(request["required_equipment"])
    for minute in range(540, 721 - duration):
        if not any(
            minute >= window["start_minute"] and minute + duration <= window["end_minute"]
            for window in facts["availability_windows"]
        ) or any(_overlaps(minute, minute + duration, busy) for busy in facts["busy_intervals"]):
            continue
        if not rules["resource_mode"]:
            candidates.append((minute, None))
            continue
        for resource in facts["resources"]:
            if (
                resource["capacity"] >= request["minimum_capacity"]
                and required_equipment.issubset(resource["equipment"])
                and any(
                    minute >= window["start_minute"] and minute + duration <= window["end_minute"]
                    for window in resource["availability_windows"]
                )
                and not any(
                    _overlaps(minute, minute + duration, block)
                    for block in resource["blocking_intervals"]
                )
            ):
                candidates.append((minute, resource["resource_id"]))
    if not candidates:
        raise ValueError("schedule has no feasible candidate")
    return min(candidates)


def _derive_schedule(mission_id: str, case: Mapping[str, Any]) -> dict[str, Any]:
    facts = case["facts"]
    rules = case["rules"]
    request = facts["request"]
    start, resource_id = _schedule_selection(case)
    constraints = [
        f"subject_id={request['subject_id']}",
        f"duration_minutes={request['duration_minutes']}",
        f"object_kind={rules['object_kind']}",
        "authority=proposal-only",
    ]
    if resource_id is not None:
        constraints.extend(
            [
                f"resource_id={resource_id}",
                f"minimum_capacity={request['minimum_capacity']}",
                f"required_equipment={'+'.join(request['required_equipment'])}",
            ]
        )
    return {
        "confirmation_status": "pending_confirmation",
        "conflicts": [
            f"busy {_minute_text(row['start_minute'])}-{_minute_text(row['end_minute'])}"
            for row in facts["busy_intervals"]
        ],
        "constraints": constraints,
        "mission_id": mission_id,
        "proposal": {"date": request["date"], "time": _minute_text(start)},
        "timezone": "/".join(facts["timezone_parts"]),
    }


def _derive_retrieval(mission_id: str, case: Mapping[str, Any]) -> dict[str, Any]:
    facts = case["facts"]
    if case["rules"]["mode"] == "ordered-edge-path":
        records = {row["record_id"]: row for row in facts["records"]}
        current = facts["query"]["start_id"]
        end = facts["query"]["end_id"]
        chain = [current]
        used: list[Mapping[str, Any]] = []
        while current != end:
            edge = next(row for row in facts["edges"] if row["from_id"] == current)
            used.append(edge)
            current = edge["to_id"]
            chain.append(current)
        return {
            "answer": f"{' -> '.join(chain)} via {' then '.join(row['relation'] for row in used)}.",
            "citations": [
                f"{row['edge_id']}:{records[row['from_id']]['section']}-{records[row['to_id']]['section']}"
                for row in used
            ],
            "missing_data_flags": [],
            "mission_id": mission_id,
            "record_ids": chain,
        }
    keyword = facts["query"]["keyword"].casefold()
    matches = [row for row in facts["documents"] if keyword in row["text"].casefold()]
    return {
        "answer": (
            f"Supported local passage: {' '.join(row['text'] for row in matches)}"
            if matches
            else "No supported local passage."
        ),
        "citations": [f"{row['record_id']}:{row['section']}" for row in matches],
        "missing_data_flags": [] if matches else ["answer-not-in-local-corpus"],
        "mission_id": mission_id,
        "record_ids": [row["record_id"] for row in matches],
    }


def _derive_classification(mission_id: str, case: Mapping[str, Any]) -> dict[str, Any]:
    subject = case["facts"]["subject"]
    rules = case["rules"]
    if rules["match_mode"] == "numeric-threshold":
        matched = rules["labels"][0] if subject["score"] >= rules["threshold"] else None
        reason = f"Supplied score {subject['score']} meets threshold {rules['threshold']}."
    else:
        words = subject["text"].casefold().split()
        matches = [row for row in rules["labels"] if row["keyword"].casefold() in words]
        matched = matches[0] if len(matches) == 1 else None
        reason = (
            f"Exact keyword '{matched['keyword']}' selects {matched['code']} and heading "
            f"{matched['heading']}."
            if matched is not None
            else "No unique exact keyword match."
        )
    if matched is None:
        return {
            "confidence": "0.00",
            "escalation_required": True,
            "label": "UNMATCHED",
            "mission_id": mission_id,
            "rationale": "No unique supported classification; escalate for human review.",
        }
    return {
        "confidence": "1.00",
        "escalation_required": False,
        "label": matched["code"],
        "mission_id": mission_id,
        "rationale": reason,
    }


def _derive_policy(mission_id: str, case: Mapping[str, Any]) -> dict[str, Any]:
    facts = case["facts"]
    rules = case["rules"]
    applicable = facts["scenario"]["applicable"]
    clauses = [row for row in facts["clauses"] if row["kind"] in rules["required_clause_kinds"]]
    return {
        "approval_required": rules["approval_code"] == "human-review-required",
        "cited_clauses": [row["clause_id"] for row in clauses] if applicable else [],
        "determination": (
            f"Applicable supplied clauses: {' '.join(row['text'] for row in clauses)}"
            if applicable
            else "Supplied applicability facts are insufficient for a determination."
        ),
        "mission_id": mission_id,
        "uncertainty": [] if applicable else ["Applicability is not established."],
    }


def _render_quality_defect_id(check: Mapping[str, Any]) -> str:
    code = check["defect_code"]
    if code == "spelling-correction":
        return f"spelling:{check['match_text']}->{check['replacement']}"
    if code == "missing-terminal":
        return "punctuation:missing-terminal"
    if code == "double-space":
        return "format:double-space"
    if code == "token-defect":
        return f"defect:{check['match_text']}"
    raise ValueError("quality defect code is unsupported")


def _quality_defects(case: Mapping[str, Any]) -> list[str]:
    text = case["facts"]["artifact"]["text"]
    defects: list[str] = []
    for check in case["rules"]["checks"]:
        token = check["match_text"]
        present = (
            not text.endswith((".", "!", "?")) if token == "<missing-terminal>" else token in text
        )
        if present:
            defects.append(_render_quality_defect_id(check))
    return defects


def _derive_quality(mission_id: str, case: Mapping[str, Any]) -> dict[str, Any]:
    defects = _quality_defects(case)
    defect_checks = {
        check["check_id"]
        for check in case["rules"]["checks"]
        if _render_quality_defect_id(check) in defects
    }
    return {
        "corrective_action": (
            "Correct all listed defects before release." if defects else "No correction required."
        ),
        "defects": defects,
        "evidence": [case["facts"]["artifact"]["artifact_id"]],
        "mission_id": mission_id,
        "qa_checklist": [
            {"check_id": check["check_id"], "passed": check["check_id"] not in defect_checks}
            for check in case["rules"]["checks"]
        ],
        "severity": "review" if defects else "none",
    }


def _decode_source_field(field: Mapping[str, Any]) -> dict[str, Any]:
    field_id = field["field_code"].removeprefix("field|")
    value_type = field["type_code"].removeprefix("type|")
    unit_text = field["unit_code"].removeprefix("unit|")
    unit = None if unit_text == "none" else unit_text
    value_prefix, raw_value = field["value_code"].split("|", 1)
    if value_type == "string" and value_prefix == "string":
        value: Any = raw_value
    elif value_type == "integer" and value_prefix == "integer":
        value = int(raw_value)
    elif value_type == "boolean" and value_prefix == "boolean":
        value = raw_value == "true"
    elif value_type == "null" and field["value_code"] == "null|none":
        value = None
    else:
        raise ValueError("encoded source field type and value disagree")
    return {
        "field_id": field_id,
        "source_ids": ["-".join(parts) for parts in field["source_parts"]],
        "unit": unit,
        "value": value,
        "value_type": value_type,
    }


def _rich_record_from_source(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "category": (
            "-".join(record["category_parts"])
            if "category_parts" in record
            else record["category_code"].removeprefix("category|")
        ),
        "fields": [_decode_source_field(field) for field in record["field_specs"]],
        "record_id": "-".join(record["record_parts"]),
        "record_kind": "rich_record_v1",
        "record_version": 1,
        "status": record["status_code"].removeprefix("status|"),
    }


def _record_root(mission_id: str, structured_record: dict[str, Any]) -> dict[str, Any]:
    field_ids: set[str] = set()
    source_ids: set[str] = set()
    records = (
        structured_record["records"]
        if structured_record.get("record_kind") == "record_set_v1"
        else [structured_record]
    )
    for record in records:
        for field in record.get("fields", []):
            field_ids.add(field["field_id"])
            source_ids.update(field["source_ids"])
    return {
        "completeness_flags": [],
        "mission_id": mission_id,
        "provenance": sorted(source_ids, key=str.encode),
        "required_fields": sorted({"category", "record_id", "status", *field_ids}, key=str.encode),
        "structured_record": structured_record,
    }


def _derive_record(mission_id: str, case: Mapping[str, Any]) -> dict[str, Any]:
    rules = case["rules"]
    facts = case["facts"]
    if rules["variant_code"] == "legacy":
        record = facts["record"]
        return {
            "completeness_flags": [],
            "mission_id": mission_id,
            "provenance": ["-".join(parts) for parts in record["source_parts"]],
            "required_fields": ["record_id", "status", "category"],
            "structured_record": {
                "category": record["category_code"].removeprefix("category|"),
                "record_id": "-".join(record["record_parts"]),
                "status": record["status_code"].removeprefix("status|"),
            },
        }
    if rules["variant_code"] == "set":
        structured = {
            "order_by": [code.removeprefix("field|") for code in rules["order_codes"]],
            "record_kind": "record_set_v1",
            "record_version": 1,
            "records": [_rich_record_from_source(record) for record in facts["records"]],
            "set_id": "record-set-02",
        }
        return _record_root(mission_id, structured)
    return _record_root(mission_id, _rich_record_from_source(facts["record"]))


_DERIVERS = {
    "reconcile-records": _derive_reconciliation,
    "compose-grounded-document": _derive_document,
    "prepare-escalation": _derive_escalation,
    "resolve-exception": _derive_exception,
    "solve-schedule": _derive_schedule,
    "retrieve-trace": _derive_retrieval,
    "classify-taxonomy": _derive_classification,
    "apply-policy": _derive_policy,
    "audit-quality": _derive_quality,
    "stage-record": _derive_record,
}


def derive_operator_output(mission_id: str, input_payload: Mapping[str, Any]) -> dict[str, Any]:
    contract = operator_contract_for_mission(mission_id)
    case = _validated_case(mission_id, input_payload)
    return _DERIVERS[contract.operator_id](mission_id, case)


def render_operator_case(
    mission_id: str,
    *,
    activity_id: str | None = None,
    activity_title: str | None = None,
) -> OperatorCase:
    contract = operator_contract_for_mission(mission_id)
    profile_id, _grammar_id, topology_id, _object_kind = _profile_binding(mission_id)
    if profile_id not in contract.profile_ids:
        raise ValueError(f"mission profile is outside {contract.operator_id}")
    facts, rules, request = _INPUT_BUILDERS[contract.operator_id](mission_id)
    input_payload = _root(
        mission_id,
        _activity_identity(mission_id, activity_id, activity_title),
        facts,
        rules,
        request,
    )
    output_payload = derive_operator_output(mission_id, input_payload)
    return OperatorCase(
        mission_id=mission_id,
        contract=contract,
        input_payload=input_payload,
        output_payload=output_payload,
        output_schema_reference=contract.output_schema_reference,
        topology_id=topology_id,
    )


def _check_reconciliation(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    facts = case["facts"]
    mode = case["rules"]["comparison_mode"]
    decisions: list[tuple[str, str, bool]] = []
    if mode == "sum-validity":
        for row in facts["survey_checks"]:
            decisions.append(
                (
                    row["left_record_id"],
                    row["right_record_id"],
                    sum(row["components"]) == row["reported_total"],
                )
            )
    elif mode == "minimum-criterion":
        for row in facts["criteria"]:
            decisions.append(
                (
                    row["left_record_id"],
                    row["right_record_id"],
                    row["actual"] >= row["minimum"],
                )
            )
    elif mode in {"exact-equality", "authoritative-equality", "staged-equality"}:
        for row in facts["record_pairs"]:
            decisions.append(
                (
                    row["left_record_id"],
                    row["right_record_id"],
                    row["left_value"] == row["right_value"],
                )
            )
    elif mode == "casefold-equality":
        for row in facts["record_pairs"]:
            decisions.append(
                (
                    row["left_record_id"],
                    row["right_record_id"],
                    row["left_value"].casefold() == row["right_value"].casefold(),
                )
            )
    else:
        return {"reconciliation-membership"}
    expected_matched = [
        {
            "left_record_id": left,
            "right_record_id": right,
            "status": "matched",
        }
        for left, right, passes in decisions
        if passes
    ]
    expected_unmatched = [f"{left}:{right}" for left, right, passes in decisions if not passes]
    expected_summary = (
        f"{case['rules']['object_kind']}: {len(expected_matched)} match(es), "
        f"{len(expected_unmatched)} discrepancy(ies)."
    )
    if (
        output.get("matched_records") != expected_matched
        or output.get("unmatched_records") != expected_unmatched
        or output.get("discrepancy_summary") != expected_summary
    ):
        return {"reconciliation-membership"}
    return set()


def _check_document(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    facts = case["facts"]["source_facts"]
    rules = case["rules"]
    draft = output.get("draft")
    failures: set[str] = set()
    if not isinstance(draft, str):
        return {"document-grounding"}
    if (
        output.get("required_fields")
        != [code.removeprefix("section|") for code in rules["required_section_codes"]]
        or output.get("tone") != "-".join(rules["tone_parts"])
        or output.get("completeness") != "complete"
    ):
        failures.add("document-grounding")
    observed_sources = output.get("grounded_sources")
    expected_sources = {row["source_id"] for row in facts}
    if (
        not isinstance(observed_sources, list)
        or len(observed_sources) != len(set(observed_sources))
        or set(observed_sources) != expected_sources
    ):
        failures.add("document-grounding")
    expected_lines = {
        f"{row['section_code'].removeprefix('section|')}: {row['text']}" for row in facts
    }
    observed_lines = [line for line in draft.splitlines() if line]
    if len(observed_lines) != len(set(observed_lines)) or set(observed_lines) != expected_lines:
        failures.add("document-grounding")
    if any(claim in draft for claim in rules["forbidden_claims"]):
        failures.add("document-grounding")
    return failures


def _check_escalation(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    observation = case["facts"]["observations"][0]
    rules = case["rules"]
    triggered = observation["value"] >= rules["threshold"]
    expected = {
        "evidence": [observation["evidence_id"]],
        "issue": (
            f"{observation['metric']}={observation['value']} reaches threshold "
            f"{rules['threshold']}."
            if triggered
            else "No declared escalation trigger is met."
        ),
        "owner": "-".join(rules["owner_parts"]) if triggered else "none",
        "recommended_next_step": (
            "Prepare a human-reviewed escalation packet."
            if triggered and rules["next_step_code"] == "prepare-human-review-packet"
            else "Record the local no-trigger result."
        ),
        "risk": rules["risk_code"].removeprefix("risk|") if triggered else "none",
    }
    if any(output.get(field) != value for field, value in expected.items()):
        return {"escalation-rule"}
    return set()


def _check_exception(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    observation = case["facts"]["observations"][0]
    rules = case["rules"]
    if (
        observation.get("unit") != rules.get("expected_unit")
        or observation.get("window") != rules.get("expected_window")
        or type(observation.get("value")) is not int
        or type(rules.get("threshold")) is not int
    ):
        return {"exception-rule"}
    violates = observation["value"] > rules["threshold"]
    expected_diagnosis = (
        f"{observation['metric']} {observation['value']} {observation['unit']} exceeds "
        f"{rules['threshold']} {rules['expected_unit']} in {observation['window']}."
        if violates
        else f"{observation['metric']} stays within the declared threshold."
    )
    expected = {
        "allowed_resolution": (
            "Prepare a local review proposal; do not perform a live fix."
            if rules["resolution_code"] == "local-review-no-live-fix"
            else "Record the bounded no-action result."
        ),
        "diagnosis": expected_diagnosis,
        "escalation_path": "-".join(rules["route_parts"]) if violates else "none",
        "evidence": ["-".join(observation["evidence_parts"])],
    }
    if any(output.get(field) != value for field, value in expected.items()):
        return {"exception-rule"}
    return set()


def _parse_minute(text: Any) -> int:
    if not isinstance(text, str) or text.count(":") != 1:
        raise ValueError("time must use HH:MM")
    hour, minute = text.split(":")
    value = int(hour) * 60 + int(minute)
    if _minute_text(value) != text:
        raise ValueError("time is outside the canonical minute grammar")
    return value


def _checker_schedule_selection(case: Mapping[str, Any]) -> tuple[int, str | None]:
    facts = case["facts"]
    rules = case["rules"]
    request = facts["request"]
    duration = request["duration_minutes"]
    if rules["selection_rule"] == "highest-attendance":
        candidates: list[tuple[int, int]] = []
        for row in facts["candidate_attendance"]:
            start = row["start_minute"]
            if any(
                start >= window["start_minute"] and start + duration <= window["end_minute"]
                for window in facts["availability_windows"]
            ) and not any(
                _overlaps(start, start + duration, busy) for busy in facts["busy_intervals"]
            ):
                candidates.append((row["score"], start))
        score, start = max(candidates, key=lambda row: (row[0], -row[1]))
        if type(score) is not int:
            raise ValueError("attendance score is malformed")
        return start, None
    candidates: list[tuple[int, str | None]] = []
    required_equipment = set(request["required_equipment"])
    for start in range(540, 721 - duration):
        if not any(
            start >= window["start_minute"] and start + duration <= window["end_minute"]
            for window in facts["availability_windows"]
        ):
            continue
        if any(_overlaps(start, start + duration, busy) for busy in facts["busy_intervals"]):
            continue
        if rules["resource_mode"] is False:
            candidates.append((start, None))
            continue
        for resource in facts["resources"]:
            fits = (
                resource["capacity"] >= request["minimum_capacity"]
                and required_equipment.issubset(set(resource["equipment"]))
                and any(
                    start >= window["start_minute"] and start + duration <= window["end_minute"]
                    for window in resource["availability_windows"]
                )
                and not any(
                    _overlaps(start, start + duration, block)
                    for block in resource["blocking_intervals"]
                )
            )
            if fits:
                candidates.append((start, resource["resource_id"]))
    return min(candidates)


def _check_schedule(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    facts = case["facts"]
    rules = case["rules"]
    request = facts["request"]
    expected_start, resource_id = _checker_schedule_selection(case)
    expected_constraints = {
        f"subject_id={request['subject_id']}",
        f"duration_minutes={request['duration_minutes']}",
        f"object_kind={rules['object_kind']}",
        "authority=proposal-only",
    }
    if resource_id is not None:
        expected_constraints.update(
            {
                f"resource_id={resource_id}",
                f"minimum_capacity={request['minimum_capacity']}",
                f"required_equipment={'+'.join(request['required_equipment'])}",
            }
        )
    constraints = output.get("constraints")
    expected_conflicts = [
        f"busy {_minute_text(row['start_minute'])}-{_minute_text(row['end_minute'])}"
        for row in facts["busy_intervals"]
    ]
    failures: set[str] = set()
    if (
        not isinstance(constraints, list)
        or len(constraints) != len(set(constraints))
        or set(constraints) != expected_constraints
        or output.get("conflicts") != expected_conflicts
        or output.get("timezone") != "/".join(facts["timezone_parts"])
        or output.get("confirmation_status") != "pending_confirmation"
        or output.get("proposal", {}).get("date") != request["date"]
        or _parse_minute(output.get("proposal", {}).get("time")) != expected_start
    ):
        failures.add("schedule-feasibility")
    return failures


def _check_retrieval(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    facts = case["facts"]
    if case["rules"]["mode"] == "ordered-edge-path":
        records = {row["record_id"]: row for row in facts["records"]}
        current = facts["query"]["start_id"]
        end = facts["query"]["end_id"]
        chain = [current]
        used: list[Mapping[str, Any]] = []
        seen = {current}
        while current != end:
            candidates = [row for row in facts["edges"] if row["from_id"] == current]
            if len(candidates) != 1:
                return {"trace-entailment"}
            edge = candidates[0]
            current = edge["to_id"]
            if current in seen or current not in records:
                return {"trace-entailment"}
            seen.add(current)
            used.append(edge)
            chain.append(current)
        expected = {
            "answer": f"{' -> '.join(chain)} via {' then '.join(row['relation'] for row in used)}.",
            "citations": [
                f"{row['edge_id']}:{records[row['from_id']]['section']}-{records[row['to_id']]['section']}"
                for row in used
            ],
            "missing_data_flags": [],
            "record_ids": chain,
        }
    else:
        keyword = facts["query"]["keyword"].casefold()
        matches = [row for row in facts["documents"] if keyword in row["text"].casefold()]
        expected = {
            "answer": (
                f"Supported local passage: {' '.join(row['text'] for row in matches)}"
                if matches
                else "No supported local passage."
            ),
            "citations": [f"{row['record_id']}:{row['section']}" for row in matches],
            "missing_data_flags": [] if matches else ["answer-not-in-local-corpus"],
            "record_ids": [row["record_id"] for row in matches],
        }
    if any(output.get(field) != value for field, value in expected.items()):
        return {"trace-entailment"}
    return set()


def _check_classification(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    subject = case["facts"]["subject"]
    rules = case["rules"]
    matched: Mapping[str, Any] | None
    if rules["match_mode"] == "numeric-threshold":
        matched = rules["labels"][0] if subject["score"] >= rules["threshold"] else None
        reason = f"Supplied score {subject['score']} meets threshold {rules['threshold']}."
    elif rules["match_mode"] == "exact-keyword":
        words = subject["text"].casefold().split()
        matches = [row for row in rules["labels"] if row["keyword"].casefold() in words]
        matched = matches[0] if len(matches) == 1 else None
        reason = (
            f"Exact keyword '{matched['keyword']}' selects {matched['code']} and heading "
            f"{matched['heading']}."
            if matched is not None
            else "No unique exact keyword match."
        )
    else:
        return {"taxonomy-rule"}
    expected = (
        {
            "confidence": "0.00",
            "escalation_required": True,
            "label": "UNMATCHED",
            "rationale": "No unique supported classification; escalate for human review.",
        }
        if matched is None
        else {
            "confidence": "1.00",
            "escalation_required": False,
            "label": matched["code"],
            "rationale": reason,
        }
    )
    if any(output.get(field) != value for field, value in expected.items()):
        return {"taxonomy-rule"}
    return set()


def _check_policy(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    facts = case["facts"]
    rules = case["rules"]
    applicable = facts["scenario"]["applicable"]
    clauses = [row for row in facts["clauses"] if row["kind"] in rules["required_clause_kinds"]]
    expected = {
        "approval_required": rules["approval_code"] == "human-review-required",
        "cited_clauses": [row["clause_id"] for row in clauses] if applicable else [],
        "determination": (
            f"Applicable supplied clauses: {' '.join(row['text'] for row in clauses)}"
            if applicable
            else "Supplied applicability facts are insufficient for a determination."
        ),
        "uncertainty": [] if applicable else ["Applicability is not established."],
    }
    if any(output.get(field) != value for field, value in expected.items()):
        return {"policy-grounding"}
    return set()


def _check_quality(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    text = case["facts"]["artifact"]["text"]
    defects: list[str] = []
    failed_checks: set[str] = set()
    for check in case["rules"]["checks"]:
        token = check["match_text"]
        present = (
            not text.endswith((".", "!", "?")) if token == "<missing-terminal>" else token in text
        )
        if present:
            code = check["defect_code"]
            if code == "spelling-correction":
                defect_id = f"spelling:{check['match_text']}->{check['replacement']}"
            elif code == "missing-terminal":
                defect_id = "punctuation:missing-terminal"
            elif code == "double-space":
                defect_id = "format:double-space"
            elif code == "token-defect":
                defect_id = f"defect:{check['match_text']}"
            else:
                return {"quality-defect-completeness"}
            defects.append(defect_id)
            failed_checks.add(check["check_id"])
    expected = {
        "corrective_action": (
            "Correct all listed defects before release." if defects else "No correction required."
        ),
        "defects": defects,
        "evidence": [case["facts"]["artifact"]["artifact_id"]],
        "qa_checklist": [
            {"check_id": check["check_id"], "passed": check["check_id"] not in failed_checks}
            for check in case["rules"]["checks"]
        ],
        "severity": "review" if defects else "none",
    }
    if any(output.get(field) != value for field, value in expected.items()):
        return {"quality-defect-completeness"}
    return set()


def _checker_decode_source_field(field: Mapping[str, Any]) -> dict[str, Any]:
    field_id = field["field_code"].removeprefix("field|")
    value_type = field["type_code"].removeprefix("type|")
    unit_code = field["unit_code"].removeprefix("unit|")
    value_code, raw_value = field["value_code"].split("|", 1)
    if value_type == "string" and value_code == "string":
        value: Any = raw_value
    elif value_type == "integer" and value_code == "integer":
        value = int(raw_value)
    elif value_type == "boolean" and value_code == "boolean":
        if raw_value not in {"false", "true"}:
            raise ValueError("encoded boolean is malformed")
        value = raw_value == "true"
    elif value_type == "null" and field["value_code"] == "null|none":
        value = None
    else:
        raise ValueError("encoded field declaration is inconsistent")
    return {
        "field_id": field_id,
        "source_ids": ["-".join(parts) for parts in field["source_parts"]],
        "unit": None if unit_code == "none" else unit_code,
        "value": value,
        "value_type": value_type,
    }


def _checker_expected_rich_record(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "category": (
            "-".join(source["category_parts"])
            if "category_parts" in source
            else source["category_code"].removeprefix("category|")
        ),
        "fields": [_checker_decode_source_field(field) for field in source["field_specs"]],
        "record_id": "-".join(source["record_parts"]),
        "record_kind": "rich_record_v1",
        "record_version": 1,
        "status": source["status_code"].removeprefix("status|"),
    }


def _checker_source_inventory(
    records: list[Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    field_ids: set[str] = set()
    source_ids: set[str] = set()
    for record in records:
        for field in record["fields"]:
            field_ids.add(field["field_id"])
            source_ids.update(field["source_ids"])
    required = sorted({"category", "record_id", "status", *field_ids}, key=str.encode)
    return required, sorted(source_ids, key=str.encode)


def _check_record(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    facts = case["facts"]
    rules = case["rules"]
    variant_code = rules["variant_code"]
    if output.get("completeness_flags") != []:
        return {"staged-record-values"}
    if variant_code == "legacy":
        source = facts["record"]
        expected_record = {
            "category": source["category_code"].removeprefix("category|"),
            "record_id": "-".join(source["record_parts"]),
            "status": source["status_code"].removeprefix("status|"),
        }
        expected_provenance = ["-".join(parts) for parts in source["source_parts"]]
        if (
            output.get("structured_record") != expected_record
            or output.get("provenance") != expected_provenance
            or output.get("required_fields") != ["record_id", "status", "category"]
        ):
            return {"staged-record-values"}
        return set()
    if variant_code == "set":
        candidate = output.get("structured_record")
        expected_order = [code.removeprefix("field|") for code in rules["order_codes"]]
        if (
            not isinstance(candidate, Mapping)
            or candidate.get("record_kind") != "record_set_v1"
            or candidate.get("set_id") != "record-set-02"
            or candidate.get("record_version") != 1
            or candidate.get("order_by") != expected_order
        ):
            return {"staged-record-values"}
        expected_records = [_checker_expected_rich_record(source) for source in facts["records"]]
        if candidate.get("records") != expected_records:
            return {"staged-record-values"}
        required, provenance = _checker_source_inventory(expected_records)
    elif variant_code == "rich":
        expected_record = _checker_expected_rich_record(facts["record"])
        if output.get("structured_record") != expected_record:
            return {"staged-record-values"}
        required, provenance = _checker_source_inventory([expected_record])
    else:
        return {"staged-record-values"}
    if output.get("required_fields") != required or output.get("provenance") != provenance:
        return {"staged-record-values"}
    return set()


_CHECKERS = {
    "reconcile-records": _check_reconciliation,
    "compose-grounded-document": _check_document,
    "prepare-escalation": _check_escalation,
    "resolve-exception": _check_exception,
    "solve-schedule": _check_schedule,
    "retrieve-trace": _check_retrieval,
    "classify-taxonomy": _check_classification,
    "apply-policy": _check_policy,
    "audit-quality": _check_quality,
    "stage-record": _check_record,
}


_LEGACY_NETWORK_FORMAT = "pipe_delimited_network_metrics_v1"


def validate_network_snapshot(case: Mapping[str, Any]) -> None:
    snapshot = case.get("metric_snapshot")
    if not isinstance(snapshot, Mapping) or snapshot.get("format") != _LEGACY_NETWORK_FORMAT:
        raise ValueError("network snapshot format is unsupported")
    ood = case.get("ood_condition")
    if not isinstance(ood, Mapping) or ood.get("format") != _LEGACY_NETWORK_FORMAT:
        raise ValueError("network snapshot format disagrees with its OOD declaration")
    window = snapshot.get("observation_window")
    if not isinstance(window, str) or window.count("/") != 1:
        raise ValueError("network observation window is malformed")
    start_text, end_text = window.split("/", 1)
    start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_text.replace("Z", "+00:00"))
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or start.utcoffset() is None
        or end.utcoffset() is None
        or start >= end
    ):
        raise ValueError("network observation window must be aware and increasing")


def _legacy_metric_row(encoded: Any) -> dict[str, str]:
    if not isinstance(encoded, str):
        raise ValueError("network row must be text")
    parsed: dict[str, str] = {}
    for segment in encoded.split("|"):
        if segment.count("=") != 1:
            raise ValueError("network row segment is malformed")
        key, value = segment.split("=", 1)
        if not key or not value or key in parsed:
            raise ValueError("network row key/value is malformed")
        parsed[key] = value
    if set(parsed) != {
        "availability_pct",
        "link",
        "p95_latency_ms",
        "packet_loss_pct",
    }:
        raise ValueError("network row fields or units drifted")
    return parsed


def _check_legacy_network(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    validate_network_snapshot(case)
    rules = case["rules"]
    snapshot = case["metric_snapshot"]
    availability_min = Decimal(rules["availability_min_pct"])
    latency_max = Decimal(rules["p95_latency_max_ms"])
    loss_max = Decimal(rules["packet_loss_max_pct"])
    passes: list[str] = []
    violations: list[tuple[str, list[str]]] = []
    evidence: list[str] = []
    for encoded in snapshot["encoded_rows"]:
        row = _legacy_metric_row(encoded)
        link = row["link"]
        evidence.append(f"{snapshot['source_id']}:{link}")
        failed: list[str] = []
        if Decimal(row["availability_pct"]) < availability_min:
            failed.append(
                f"availability ({row['availability_pct']} < {rules['availability_min_pct']})"
            )
        if Decimal(row["p95_latency_ms"]) > latency_max:
            failed.append(
                f"p95 latency ({row['p95_latency_ms']} > {rules['p95_latency_max_ms']} ms)"
            )
        if Decimal(row["packet_loss_pct"]) > loss_max:
            failed.append(
                f"packet loss ({row['packet_loss_pct']} > {rules['packet_loss_max_pct']})"
            )
        if failed:
            violations.append((link, failed))
        else:
            passes.append(link)
    evidence.append(rules["rule_id"])
    parts: list[str] = []
    if passes:
        parts.append(f"{', '.join(passes)} passes all declared thresholds")
    parts.extend(f"{link} violates {', and '.join(items)}" for link, items in violations)
    route = rules["problem_route"]
    expected = {
        "allowed_resolution": (
            "Prepare an offline network-review packet from the supplied snapshot; do "
            "not access a network, run diagnostics, change capacity, perform recovery, "
            "or claim live resolution."
            if violations
            else "Record the offline pass result; do not access a network, run diagnostics, "
            "change capacity, perform recovery, or claim live resolution."
        ),
        "diagnosis": (
            f"Offline network-metric evaluation of {snapshot['source_id']}: {'; '.join(parts)}."
        ),
        "escalation_path": route["joiner"].join(route["parts"]) if violations else "none",
        "evidence": evidence,
    }
    failures: set[str] = set()
    if any(output.get(field) != value for field, value in expected.items()):
        failures.add("exception-rule")
    authority = case.get("authority", {})
    if any(
        authority.get(key) is not False
        for key in (
            "autonomous_approval",
            "disaster_recovery_action",
            "external_truth_claim",
            "live_diagnostics",
            "network_access",
            "physical_action",
            "system_write",
        )
    ):
        failures.add("contained-authority")
    return failures


def _check_legacy_resource(input_payload: Mapping[str, Any], output: Mapping[str, Any]) -> set[str]:
    case = input_payload["case"]
    request = case["reservation_request"]
    window = request["allowed_window"]
    start_minute = window["start_minute"]
    end_minute = window["end_minute"]
    duration = request["duration_minutes"]
    minimum_capacity = request["minimum_capacity"]
    required_equipment = request["required_equipment"]
    conflicts: list[str] = []
    candidates: list[tuple[int, str]] = []
    for resource in case["resources"]:
        blocks: list[tuple[int, int]] = []
        for block in resource["blocking_intervals"]:
            blocks.append((block["start_minute"], block["end_minute"]))
            conflicts.append(
                f"{resource['resource_id']} blocked {_minute_text(block['start_minute'])}-"
                f"{_minute_text(block['end_minute'])}: {block['reason']}"
            )
        missing = [item for item in required_equipment if item not in resource["equipment"]]
        if missing:
            conflicts.append(
                f"{resource['resource_id']} missing equipment: {'+'.join(sorted(missing))}"
            )
            continue
        if resource["capacity"] < minimum_capacity:
            conflicts.append(
                f"{resource['resource_id']} capacity {resource['capacity']} below required "
                f"{minimum_capacity}"
            )
            continue
        for available in resource["available_windows"]:
            candidate = max(start_minute, available["start_minute"])
            available_end = min(end_minute, available["end_minute"])
            while candidate + duration <= available_end:
                overlapping = [
                    (block_start, block_end)
                    for block_start, block_end in blocks
                    if candidate < block_end and candidate + duration > block_start
                ]
                if not overlapping:
                    candidates.append((candidate, resource["resource_id"]))
                    break
                candidate = max(block_end for _block_start, block_end in overlapping)
    selected_start, selected_resource = min(candidates)
    timezone_parts = case["timezone_parts"]
    expected_constraints = {
        f"resource_id={selected_resource}",
        f"minimum_capacity={minimum_capacity}",
        f"required_equipment={'+'.join(required_equipment)}",
        f"duration_minutes={duration}",
        f"window={_minute_text(start_minute)}-{_minute_text(end_minute)}",
        "authority=proposal_only",
    }
    observed_constraints = output.get("constraints")
    failures: set[str] = set()
    if (
        not isinstance(observed_constraints, list)
        or len(observed_constraints) != len(set(observed_constraints))
        or set(observed_constraints) != expected_constraints
        or output.get("conflicts") != conflicts
        or output.get("proposal") != {"date": request["date"], "time": _minute_text(selected_start)}
        or output.get("timezone")
        != f"{timezone_parts['area']}{timezone_parts['joiner']}{timezone_parts['city']}"
        or output.get("confirmation_status") != "pending_confirmation"
    ):
        failures.add("schedule-feasibility")
    authority = case.get("authority", {})
    if any(
        authority.get(key) is not False
        for key in (
            "allow_confirmation",
            "autonomous_approval",
            "external_communication",
            "external_truth_claim",
            "network_access",
            "physical_action",
            "system_write",
        )
    ):
        failures.add("contained-authority")
    return failures


def check_operator_output(
    mission_id: str,
    input_payload: Mapping[str, Any],
    output_payload: Mapping[str, Any],
    *,
    checker_version: str | None = None,
) -> DomainCheckResult:
    contract = operator_contract_for_mission(mission_id)
    if checker_version is not None and checker_version != contract.checker_version:
        raise ValueError(f"unsupported checker version for {contract.operator_id}")
    if contract.coverage_status == "output_contract_blocked":
        return DomainCheckResult(
            operator_id=contract.operator_id,
            checker_version=contract.checker_version,
            passed=False,
            failed_invariant_ids=("output-contract-blocked",),
            blocked=True,
            block_reason=contract.output_adequacy_note,
        )
    failures: set[str] = set()
    case = input_payload.get("case")
    try:
        if (
            mission_id == "sbov1-exception_handling-11"
            and isinstance(case, Mapping)
            and "metric_snapshot" in case
        ):
            failures.update(_check_legacy_network(input_payload, output_payload))
        elif (
            mission_id == "sbov1-followup_scheduling-12"
            and isinstance(case, Mapping)
            and "reservation_request" in case
            and "facts" not in case
        ):
            failures.update(_check_legacy_resource(input_payload, output_payload))
        else:
            failures.update(_envelope_failures(mission_id, input_payload))
            if not failures:
                failures.update(_CHECKERS[contract.operator_id](input_payload, output_payload))
    except (ArithmeticError, KeyError, StopIteration, TypeError, ValueError):
        failures.add("malformed-domain-input-or-output")
    if output_payload.get("mission_id") != mission_id:
        failures.add("operator-output-identity")
    return DomainCheckResult(
        operator_id=contract.operator_id,
        checker_version=contract.checker_version,
        passed=not failures,
        failed_invariant_ids=tuple(sorted(failures)),
        blocked=False,
        block_reason=None,
    )


def _changed_typed_value(value_type: str, value: Any) -> Any:
    if value_type == "string":
        return f"{value}-changed"
    if value_type == "integer":
        return value + 1
    if value_type == "boolean":
        return not value
    if value_type == "null":
        raise ValueError("null source values cannot carry a semantic mutation")
    raise ValueError(f"unsupported typed value: {value_type}")


def _change_encoded_source_value(field: dict[str, Any]) -> None:
    value_type = field["type_code"].removeprefix("type|")
    prefix, raw_value = field["value_code"].split("|", 1)
    if value_type == "string" and prefix == "string":
        field["value_code"] = f"string|{raw_value}-changed"
    elif value_type == "integer" and prefix == "integer":
        field["value_code"] = f"integer|{int(raw_value) + 1}"
    elif value_type == "boolean" and prefix == "boolean":
        field["value_code"] = "boolean|false" if raw_value == "true" else "boolean|true"
    else:
        raise ValueError("encoded source field cannot be semantically mutated")


def _wrong_output_mutation(
    operator_id: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
) -> None:
    if operator_id == "reconcile-records":
        output_payload["matched_records"].append(
            {
                "left_record_id": "plausible-left",
                "right_record_id": "plausible-right",
                "status": "matched",
            }
        )
    elif operator_id == "compose-grounded-document":
        fact = input_payload["case"]["facts"]["source_facts"][0]["text"]
        output_payload["draft"] = output_payload["draft"].replace(fact, "omitted fact")
    elif operator_id == "prepare-escalation":
        output_payload["risk"] = "wrong-risk"
    elif operator_id == "resolve-exception":
        output_payload["diagnosis"] = "Unsupported but schema-valid diagnosis."
    elif operator_id == "solve-schedule":
        output_payload["proposal"]["time"] = "09:00"
    elif operator_id == "retrieve-trace":
        output_payload["answer"] += " Unsupported external claim."
    elif operator_id == "classify-taxonomy":
        output_payload["label"] = "WRONG"
    elif operator_id == "apply-policy":
        output_payload["cited_clauses"] = ["CLAUSE-UNSUPPORTED"]
    elif operator_id == "audit-quality":
        output_payload["defects"] = []
    elif operator_id == "stage-record":
        structured = output_payload["structured_record"]
        if "record_kind" not in structured:
            structured["category"] = "wrong-category"
            return
        record = (
            structured["records"][0] if structured["record_kind"] == "record_set_v1" else structured
        )
        field = record["fields"][0]
        field["value"] = _changed_typed_value(field["value_type"], field["value"])
    else:
        raise ValueError(f"unsupported operator mutation: {operator_id}")


def _semantic_input_mutation(
    operator_id: str,
    input_payload: dict[str, Any],
    output_payload: Mapping[str, Any],
) -> None:
    case = input_payload["case"]
    if operator_id == "reconcile-records":
        facts = case["facts"]
        mode = case["rules"]["comparison_mode"]
        if mode == "sum-validity":
            facts["survey_checks"][0]["reported_total"] += 1
        elif mode == "minimum-criterion":
            facts["criteria"][0]["actual"] = 0
        elif mode == "casefold-equality":
            facts["record_pairs"][0]["right_value"] = "changed"
        else:
            facts["record_pairs"][0]["right_value"] += 1
    elif operator_id == "compose-grounded-document":
        case["facts"]["source_facts"][0]["text"] += " changed"
    elif operator_id == "prepare-escalation":
        case["facts"]["observations"][0]["value"] = 0
    elif operator_id == "resolve-exception":
        observation = case["facts"]["observations"][0]
        if observation["metric"] == "network-metric-window":
            observation["unit"] = "seconds"
        else:
            observation["value"] = 0
    elif operator_id == "solve-schedule":
        start = _parse_minute(output_payload["proposal"]["time"])
        duration = case["facts"]["request"]["duration_minutes"]
        case["facts"]["busy_intervals"].append(
            {"end_minute": start + duration, "start_minute": start}
        )
    elif operator_id == "retrieve-trace":
        if case["rules"]["mode"] == "ordered-edge-path":
            case["facts"]["edges"].pop()
        else:
            case["facts"]["query"]["keyword"] = "absent-keyword"
    elif operator_id == "classify-taxonomy":
        if case["rules"]["match_mode"] == "numeric-threshold":
            case["facts"]["subject"]["score"] = 0
        else:
            case["facts"]["subject"]["text"] = "Synthetic unknown subject"
    elif operator_id == "apply-policy":
        case["facts"]["scenario"]["applicable"] = False
    elif operator_id == "audit-quality":
        case["facts"]["artifact"]["text"] += " EXTRA"
        case["rules"]["checks"].append(
            {
                "check_id": "semantic-input-check",
                "defect_code": "token-defect",
                "match_text": "EXTRA",
            }
        )
    elif operator_id == "stage-record":
        variant_code = case["rules"]["variant_code"]
        if variant_code == "legacy":
            case["facts"]["record"]["category_code"] = "category|changed-category"
            return
        record = case["facts"]["records"][0] if variant_code == "set" else case["facts"]["record"]
        _change_encoded_source_value(record["field_specs"][0])
    else:
        raise ValueError(f"unsupported operator mutation: {operator_id}")


def apply_domain_mutation_payloads(
    mission_id: str,
    input_payload: Mapping[str, Any],
    output_payload: Mapping[str, Any],
    mutation_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = operator_contract_for_mission(mission_id)
    definitions = {mutation.mutation_id: mutation for mutation in contract.domain_mutations}
    try:
        mutation = definitions[mutation_id]
    except KeyError as error:
        raise ValueError(f"unknown domain mutation for {mission_id}: {mutation_id}") from error
    mutated_input = copy.deepcopy(dict(input_payload))
    mutated_output = copy.deepcopy(dict(output_payload))
    if mutation.kind == "plausible_wrong_output":
        _wrong_output_mutation(contract.operator_id, mutated_input, mutated_output)
    elif mutation.kind == "semantic_input":
        _semantic_input_mutation(contract.operator_id, mutated_input, mutated_output)
    else:
        mutated_input["case"]["authority"]["system_write"] = True
    return mutated_input, mutated_output


def apply_domain_mutation(
    case: OperatorCase,
    mutation_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return apply_domain_mutation_payloads(
        case.mission_id,
        case.input_payload,
        case.output_payload,
        mutation_id,
    )
