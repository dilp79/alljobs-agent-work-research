from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Classification = Literal["TEMPLATE_SAFE", "NEEDS_RULE", "REMAP"]


@dataclass(frozen=True)
class Phase2BProfileAssignment:
    mission_id: str
    category: str
    classification: Classification
    profile_id: str


@dataclass(frozen=True)
class Phase2BRemapProfile:
    mission_id: str
    current_activity_id: str
    current_decision_id: str
    planned_decision_id: str
    proposed_activity_id: str
    proposed_title: str
    profile_id: str


CATEGORY_ORDER = (
    "data_reconciliation",
    "draft_generation",
    "escalation_preparation",
    "exception_handling",
    "followup_scheduling",
    "information_retrieval",
    "intake_classification",
    "policy_interpretation",
    "quality_verification",
    "record_preparation",
)

PILOT_MISSION_IDS = frozenset(
    {
        "sbov1-data_reconciliation-01",
        "sbov1-draft_generation-05",
        "sbov1-escalation_preparation-11",
        "sbov1-exception_handling-08",
        "sbov1-followup_scheduling-05",
        "sbov1-information_retrieval-02",
        "sbov1-intake_classification-11",
        "sbov1-policy_interpretation-08",
        "sbov1-quality_verification-06",
        "sbov1-record_preparation-09",
    }
)

# This is the reviewed 48-row semantic-audit assignment. The generator consumes
# these mission IDs directly; it never selects an operator from activity-title text.
_TEMPLATE_SAFE_SUFFIXES = {
    "data_reconciliation": ("02", "03", "04", "07", "09", "10", "11"),
    "draft_generation": ("02", "06", "07", "09"),
    "escalation_preparation": ("03", "05", "06", "08"),
    "exception_handling": ("02", "03", "04", "07"),
    "followup_scheduling": ("01", "08"),
    "information_retrieval": ("03", "04", "05", "06", "09", "10"),
    "intake_classification": ("03", "04", "06", "07"),
    "policy_interpretation": ("01", "02", "03", "05", "07"),
    "quality_verification": ("02", "03", "07", "10", "11", "12"),
    "record_preparation": ("01", "02", "03", "04", "05", "11"),
}

# This is the reviewed 52-row repair-memo assignment. Repeated profile names are
# intentional; each resulting profile is still mission-bound and self-contained.
_NEEDS_RULE_PROFILES = {
    "sbov1-data_reconciliation-05": "source-truth-validation",
    "sbov1-data_reconciliation-08": "staged-correction",
    "sbov1-data_reconciliation-12": "performance-criteria",
    "sbov1-draft_generation-01": "faithful-transcription",
    "sbov1-draft_generation-03": "chart-table-result-summary",
    "sbov1-draft_generation-04": "support-training-document",
    "sbov1-draft_generation-08": "document-review",
    "sbov1-draft_generation-10": "agenda-packet",
    "sbov1-draft_generation-11": "controlled-office-form",
    "sbov1-draft_generation-12": "multi-genre-ood",
    "sbov1-escalation_preparation-01": "status-to-trigger",
    "sbov1-escalation_preparation-02": "status-to-trigger",
    "sbov1-escalation_preparation-04": "test-evidence",
    "sbov1-escalation_preparation-07": "recommendation-options",
    "sbov1-escalation_preparation-09": "chart-report",
    "sbov1-escalation_preparation-10": "status-to-trigger",
    "sbov1-escalation_preparation-12": "fictional-safety-incident",
    "sbov1-exception_handling-01": "query-generation",
    "sbov1-exception_handling-05": "test-root-cause",
    "sbov1-exception_handling-06": "quantitative-reliability",
    "sbov1-exception_handling-09": "technical-solution",
    "sbov1-exception_handling-10": "user-response-draft",
    "sbov1-exception_handling-11": "network-metric",
    "sbov1-exception_handling-12": "before-after-fix-verification",
    "sbov1-followup_scheduling-06": "consent-pending-status",
    "sbov1-followup_scheduling-09": "attendance-optimization",
    "sbov1-followup_scheduling-10": "bounded-event-resource",
    "sbov1-followup_scheduling-11": "bounded-event-resource",
    "sbov1-information_retrieval-01": "cached-external-source",
    "sbov1-information_retrieval-07": "multi-source-intent-synthesis",
    "sbov1-information_retrieval-08": "record-search",
    "sbov1-information_retrieval-11": "query-disambiguation",
    "sbov1-intake_classification-01": "security-labels",
    "sbov1-intake_classification-02": "code-list-mapping",
    "sbov1-intake_classification-05": "numeric-threshold",
    "sbov1-intake_classification-08": "code-list-mapping",
    "sbov1-intake_classification-09": "supplied-physical-measurements",
    "sbov1-intake_classification-10": "library-taxonomy",
    "sbov1-intake_classification-12": "company-taxonomy",
    "sbov1-policy_interpretation-04": "fictional-hr-law",
    "sbov1-policy_interpretation-09": "complaint-response",
    "sbov1-policy_interpretation-10": "cost-availability",
    "sbov1-policy_interpretation-11": "structured-spec-blueprint",
    "sbov1-policy_interpretation-12": "official-audience-boundary",
    "sbov1-quality_verification-01": "staged-correction",
    "sbov1-quality_verification-04": "record-completeness",
    "sbov1-quality_verification-05": "code-static-compatibility",
    "sbov1-quality_verification-08": "log-thresholds",
    "sbov1-quality_verification-09": "efficiency-criteria",
    "sbov1-record_preparation-06": "operational-form",
    "sbov1-record_preparation-07": "computation-proofread",
    "sbov1-record_preparation-12": "shipping-measurement-ood",
}

REMAP_PROFILES = (
    Phase2BRemapProfile(
        mission_id="sbov1-data_reconciliation-06",
        current_activity_id="dfada218e30a584ff5782ad87c87884f",
        current_decision_id="decision-sbov1-data_reconciliation-06-001",
        planned_decision_id="decision-sbov1-data_reconciliation-06-002",
        proposed_activity_id="ba663b441ec61cbf110806897d4c7a8c",
        proposed_title="Verify the mathematical correctness of newly collected survey data.",
        profile_id="survey-mathematical-correctness",
    ),
    Phase2BRemapProfile(
        mission_id="sbov1-followup_scheduling-02",
        current_activity_id="9c15ec67e91f5be1fe536a08fc133b12",
        current_decision_id="decision-sbov1-followup_scheduling-02-001",
        planned_decision_id="decision-sbov1-followup_scheduling-02-002",
        proposed_activity_id="46d780064f04314853e1adb39e9022ca",
        proposed_title="Schedule guest appointments.",
        profile_id="guest-appointment",
    ),
    Phase2BRemapProfile(
        mission_id="sbov1-followup_scheduling-03",
        current_activity_id="ea57d0e8b31f5afb6d53cc0cb76ae656",
        current_decision_id="decision-sbov1-followup_scheduling-03-001",
        planned_decision_id="decision-sbov1-followup_scheduling-03-002",
        proposed_activity_id="9b883392af6f708c0120efe7eea9f380",
        proposed_title="Schedule client appointments.",
        profile_id="client-appointment",
    ),
    Phase2BRemapProfile(
        mission_id="sbov1-followup_scheduling-04",
        current_activity_id="19716e90438c51a30c11c5725a9acdb2",
        current_decision_id="decision-sbov1-followup_scheduling-04-001",
        planned_decision_id="decision-sbov1-followup_scheduling-04-002",
        proposed_activity_id="2a70b86a74560a452a33ac684a164a2c",
        proposed_title="Schedule parties and take reservations.",
        profile_id="party-reservation",
    ),
    Phase2BRemapProfile(
        mission_id="sbov1-followup_scheduling-07",
        current_activity_id="4406530171ea6a9675560035deb1ac15",
        current_decision_id="decision-sbov1-followup_scheduling-07-001",
        planned_decision_id="decision-sbov1-followup_scheduling-07-002",
        proposed_activity_id="75c02dcedeb9d62e3037f592ceb80010",
        proposed_title=(
            "Schedule appointments for sales representatives to meet with prospective "
            "customers or for customers to attend sales presentations."
        ),
        profile_id="sales-appointment",
    ),
    Phase2BRemapProfile(
        mission_id="sbov1-followup_scheduling-12",
        current_activity_id="a47476d393fb181e4b71ffeb5956f1e3",
        current_decision_id="decision-sbov1-followup_scheduling-12-001",
        planned_decision_id="decision-sbov1-followup_scheduling-12-002",
        proposed_activity_id="215b11ce4fc83843e6445d1b4fd74af9",
        proposed_title="Reserve audio-visual equipment and facilities, such as meeting rooms.",
        profile_id="resource-reservation",
    ),
    Phase2BRemapProfile(
        mission_id="sbov1-information_retrieval-12",
        current_activity_id="8668cb5a9e96b09bc8f32e7716698cfb",
        current_decision_id="decision-sbov1-information_retrieval-12-001",
        planned_decision_id="decision-sbov1-information_retrieval-12-002",
        proposed_activity_id="47cf5d8928b1f2053bdfcce102e1abd6",
        proposed_title="Examine records to locate links in chains of evidence or information.",
        profile_id="information-chain",
    ),
    Phase2BRemapProfile(
        mission_id="sbov1-policy_interpretation-06",
        current_activity_id="292780ecee57e756df05a27872d7830b",
        current_decision_id="decision-sbov1-policy_interpretation-06-001",
        planned_decision_id="decision-sbov1-policy_interpretation-06-002",
        proposed_activity_id="1792178f48175fdb8c4414b97c87f678",
        proposed_title=(
            "Explain company policies and procedures to staff using oral or written communication."
        ),
        profile_id="staff-policy-explanation",
    ),
    Phase2BRemapProfile(
        mission_id="sbov1-record_preparation-08",
        current_activity_id="c72ca974a56e2519c0007ab99aec2d86",
        current_decision_id="decision-sbov1-record_preparation-08-001",
        planned_decision_id="decision-sbov1-record_preparation-08-002",
        proposed_activity_id="6e9213977f5bd0fb8fefa86066cfe63c",
        proposed_title="Compile and record operational data on forms or in log books.",
        profile_id="operational-log",
    ),
    Phase2BRemapProfile(
        mission_id="sbov1-record_preparation-10",
        current_activity_id="5276ad90cabd6f4e0062f752de001615",
        current_decision_id="decision-sbov1-record_preparation-10-001",
        planned_decision_id="decision-sbov1-record_preparation-10-002",
        proposed_activity_id="eae2e6e0809d84b55edb356ebaaee98a",
        proposed_title="Record production data, and maintain production logs.",
        profile_id="production-log",
    ),
)


def _category_from_mission(mission_id: str) -> str:
    return mission_id.removeprefix("sbov1-").rsplit("-", 1)[0]


def _build_assignments() -> tuple[Phase2BProfileAssignment, ...]:
    rows: list[Phase2BProfileAssignment] = []
    for category in CATEGORY_ORDER:
        rows.extend(
            Phase2BProfileAssignment(
                mission_id=f"sbov1-{category}-{suffix}",
                category=category,
                classification="TEMPLATE_SAFE",
                profile_id=f"operator-family-{category.replace('_', '-')}",
            )
            for suffix in _TEMPLATE_SAFE_SUFFIXES[category]
        )
    rows.extend(
        Phase2BProfileAssignment(
            mission_id=mission_id,
            category=_category_from_mission(mission_id),
            classification="NEEDS_RULE",
            profile_id=profile_id,
        )
        for mission_id, profile_id in _NEEDS_RULE_PROFILES.items()
    )
    rows.extend(
        Phase2BProfileAssignment(
            mission_id=remap.mission_id,
            category=_category_from_mission(remap.mission_id),
            classification="REMAP",
            profile_id=remap.profile_id,
        )
        for remap in REMAP_PROFILES
    )
    return tuple(sorted(rows, key=lambda row: row.mission_id.encode("utf-8")))


PHASE2B_ASSIGNMENTS = _build_assignments()
ASSIGNMENT_BY_MISSION = {row.mission_id: row for row in PHASE2B_ASSIGNMENTS}
REMAP_BY_MISSION = {row.mission_id: row for row in REMAP_PROFILES}

if len(PHASE2B_ASSIGNMENTS) != 110 or len(ASSIGNMENT_BY_MISSION) != 110:
    raise RuntimeError("Phase 2B reviewed assignment registry must contain exactly 110 rows")
if sum(row.classification == "TEMPLATE_SAFE" for row in PHASE2B_ASSIGNMENTS) != 48:
    raise RuntimeError("Phase 2B TEMPLATE_SAFE registry count drifted")
if sum(row.classification == "NEEDS_RULE" for row in PHASE2B_ASSIGNMENTS) != 52:
    raise RuntimeError("Phase 2B NEEDS_RULE registry count drifted")
if sum(row.classification == "REMAP" for row in PHASE2B_ASSIGNMENTS) != 10:
    raise RuntimeError("Phase 2B REMAP registry count drifted")
if any(
    sum(row.category == category for row in PHASE2B_ASSIGNMENTS) != 11
    for category in CATEGORY_ORDER
):
    raise RuntimeError("Phase 2B category assignment count drifted")
if set(ASSIGNMENT_BY_MISSION) & PILOT_MISSION_IDS:
    raise RuntimeError("Phase 2B registry must not contain a canonical pilot mission")
