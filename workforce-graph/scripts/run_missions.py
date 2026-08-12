"""Give a named agent the mission input, take back its deliverable, and let the suite judge it.

This is the only piece Layer 2 was missing. Everything either side of it already existed and
was found by looking rather than by building: the 120 missions carry their inputs
(`fixtures/inputs.jsonl`) and their answers (`fixtures/expected_outputs.jsonl`), and the
grader is implemented — `check_operator_output(mission_id, input, output)` returns pass, fail,
and the invariants that failed. What did not exist was anything that hands a mission to an
agent.

Three facts about the suite that this script is built around, each measured rather than assumed:

  110 of 120 missions are gradeable. Ten raise "mission lacks a real semantic operator" —
  scattered across categories rather than following any pattern, which is why they are listed
  by name in the output and never summarised into a count alone.

  All 550 literal assertions in the missions' check programs read `input.*`. Not one reads the
  agent's output. They are scope guards asserting the mission stays inside its declared
  authority envelope — no network, no writes, no physical action — and they say nothing about
  whether work was done. The judgement that matters comes from the domain checker.

  The suite's own success criterion is unreachable here, and this is not a defect to engineer
  around. Every mission requires `"evaluator": "human"` on a required holistic rubric, and
  this project has no human labelling. So what this script measures is DETERMINISTIC
  CONFORMANCE: a necessary condition of mission success, never a sufficient one. Reporting it
  as "the agent completed the task" would repeat, in a new place, the exact error the rest of
  this project exists to stop — calling a proxy by the name of the thing it proxies.

Four no-tool prompt arms, because a result from one configuration cannot separate the model
from its scaffold. `bare` shows a same-category worked development example; `bare_no_example`
shows none; `bare_schema` shows only its structural description; `bare_redacted_example` applies
one deterministic substitution map to both sides of the same worked example. The redacted arm
preserves JSON shape and declared enum vocabulary, audits exact and normalized overlap against
all 82 measured payloads, and records its map/prompt digests. It is only a bundled-redaction
sensitivity diagnostic. It does not isolate format, reusable content, copying, capability,
mission success, or a causal arm effect. A tool-using harnessed arm remains unimplemented.

The model-substitution guard from the labelling runs is kept. The router answers a rate-limited
request with another vendor's model under the name you asked for, and a trial graded from a
substituted model would be a measurement of something nobody chose.

Usage:
    python scripts/run_missions.py --model deepseek-v4-pro --arm bare
    python scripts/run_missions.py --model deepseek-v4-pro --arm bare --limit 5
    python scripts/run_missions.py --grade-expected     # sanity: the answers grade themselves
"""

from __future__ import annotations

import collections
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import click
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from workforce_graph.evidence.task4_phase2b_operators import (  # noqa: E402
    check_operator_output,
    operator_contract_for_mission,
)

_spec = importlib.util.spec_from_file_location(
    "classify_work_mode", Path(__file__).parent / "classify_work_mode.py"
)
cwm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cwm)

SUITE = ROOT / "benchmark" / "support_backoffice" / "v1"
OUT_DIR = ROOT / "data" / "trials"

#: Bumped whenever anything that could change a verdict changes: the prompt, the example
#: policy, the fixtures, the grader. Trials carry it, and a resume refuses records that do not
#: match. Without it, resume identity was mission_id plus a boolean, so every trial could be
#: reused after the scoring conditions had moved underneath it.
RUN_SPEC_VERSION = "2026-08-10.1"
REDACTED_RUN_SPEC_VERSION = "2026-08-11.1-redacted-example"
LEGACY_RUN_SPEC = "legacy-missing-run-spec"

ARM_RUN_SPECS = {
    "bare": RUN_SPEC_VERSION,
    "bare_no_example": RUN_SPEC_VERSION,
    "bare_schema": RUN_SPEC_VERSION,
    "bare_redacted_example": REDACTED_RUN_SPEC_VERSION,
}

# These fields carry a closed vocabulary whose exact tokens are part of the answer schema.
# Redaction preserves them and reports their overlap separately from replaceable content.
ENUM_FIELDS = frozenset(
    {
        "action",
        "agent_type",
        "allowed_resolution",
        "classification",
        "completeness",
        "confirmation_status",
        "corrective_action",
        "currency",
        "category",
        "escalation_path",
        "label",
        "mode",
        "operator_id",
        "owner",
        "priority",
        "role",
        "record_kind",
        "required_approval_class",
        "result",
        "risk",
        "risk_class",
        "risk_level",
        "severity",
        "status",
        "timezone",
        "tone",
        "type",
        "unit",
        "value_type",
    }
)

REDACTION_DIAGNOSTIC_CEILING = (
    "bundled redaction sensitivity diagnostic only; not format, reusable-content, copying, "
    "capability, mission success, or a causal arm effect"
)
REDACTION_GATE_PROCEDURE_ID = "alljobs.redacted-example-domain-preflight"
REDACTION_GATE_PROCEDURE_VERSION = "1.0.0"
GATE_BOUND_IDENTITY_FIELDS = frozenset(
    {"case_id", "grammar_id", "mission_id", "profile_id", "topology_id"}
)
_OPERATOR_CHECKER_SOURCE = (
    ROOT / "src" / "workforce_graph" / "evidence" / "task4_phase2b_operators.py"
)

SYSTEM_PROMPT = """You perform one support or back-office task and return its result as JSON.

You are given a case as a JSON object. Read it, do what the task requires, and answer with a
single JSON object holding the deliverable — no prose, no explanation outside the JSON, no
markdown fence.

Constraints that are part of the task, not advice:
- You have no network, no write access to any system, and cannot take physical action. If the
  case appears to require any of those, that is a fact about the case and your answer should
  reflect it rather than pretend the action was taken.
- Derive every value from the case. Do not invent identifiers, amounts, dates or names that
  the case does not contain.
- If the case does not determine an answer — a required input is missing, two inputs
  contradict, or no valid result exists — say so in the deliverable rather than guessing.

The deliverable's field names are part of the task. Use exactly the field names the case and
its stated expectations imply."""


def load_suite() -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Missions, inputs and expected outputs, keyed by mission_id.

    Read directly rather than through `benchmark.load_mission_suite`, whose record schema
    demands `{category, eval_spec, fixture_payload, task_snapshot}` while every record on disk
    carries `{eval_spec, mission_id, task_snapshot}`. That drift is a real defect and it is
    recorded, but repairing a loader is not a prerequisite for reading four known files.
    """
    missions: dict[str, dict] = {}
    for path in sorted((SUITE / "missions").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                rec["category"] = path.stem
                missions[rec["mission_id"]] = rec
    inputs = {
        json.loads(line)["mission_id"]: json.loads(line)
        for line in (SUITE / "fixtures" / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    expected = {
        json.loads(line)["mission_id"]: json.loads(line)
        for line in (SUITE / "fixtures" / "expected_outputs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    return missions, inputs, expected


def _trial_run_spec(rec: dict) -> str:
    return rec.get("run_spec", LEGACY_RUN_SPEC)


def settled_ids(
    path: Path, *, run_spec: str = RUN_SPEC_VERSION, arm: str | None = None
) -> set[str]:
    """Missions already carrying a verdict, so a restart resumes instead of repeating.

    The labelling scripts' `done_ids` cannot serve here: it counts a row as done when it has
    a `mode` field, and trial records have no such field, so it silently returned nothing and
    a re-run duplicated every trial. That is how the first full run left 92 rows for 82
    missions — not visibly wrong anywhere, just quietly double-counting ten of them.

    A row counts as settled only when the agent answered AND the checker reached a verdict.
    A failed call stays pending, because re-running the command is the retry.
    """
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            _trial_run_spec(rec) == run_spec
            and (arm is None or rec.get("arm") == arm)
            and rec.get("mission_id")
            and rec.get("deliverable") is not None
            and isinstance((rec.get("verdict") or {}).get("conformant"), bool)
        ):
            out.add(rec.get("mission_id"))
    return out


def latest_trials(
    path: Path, *, run_spec: str = RUN_SPEC_VERSION, arm: str | None = None
) -> dict[str, dict]:
    """Latest record per mission within one exact run-spec and, optionally, one arm.

    Filtering happens before replacement. A later row from a new arm or run specification
    therefore cannot silently change an older arm's accumulated result. Historical records
    that predate `run_spec` are addressable only through the explicit `LEGACY_RUN_SPEC` token.
    """
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        if line.strip():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _trial_run_spec(rec) != run_spec or (arm is not None and rec.get("arm") != arm):
                continue
            if not rec.get("mission_id"):
                continue
            out[rec["mission_id"]] = rec
    return out


def paired_common_answered(left: dict[str, dict], right: dict[str, dict]) -> dict:
    """Exact paired arm contrast over missions answered in both arms.

    The four cells and mission IDs are returned so the exact McNemar calculation is auditable.
    Unanswered records do not become failures; they are excluded from the common-answer set.
    """
    common = sorted(set(left) & set(right))
    cells = {"both_pass": [], "left_only": [], "right_only": [], "both_fail": []}
    excluded = []
    for mid in common:
        left_value = (left[mid].get("verdict") or {}).get("conformant")
        right_value = (right[mid].get("verdict") or {}).get("conformant")
        if not isinstance(left_value, bool) or not isinstance(right_value, bool):
            excluded.append(mid)
            continue
        if left_value and right_value:
            cells["both_pass"].append(mid)
        elif left_value:
            cells["left_only"].append(mid)
        elif right_value:
            cells["right_only"].append(mid)
        else:
            cells["both_fail"].append(mid)

    left_only = len(cells["left_only"])
    right_only = len(cells["right_only"])
    discordant = left_only + right_only
    if discordant:
        tail = sum(math.comb(discordant, k) for k in range(min(left_only, right_only) + 1))
        exact_p = min(1.0, 2.0 * tail / (2**discordant))
    else:
        exact_p = 1.0
    return {
        "common_answered": sum(len(value) for value in cells.values()),
        "cells": {key: len(value) for key, value in cells.items()},
        "discordant_pairs": {
            "left_only": cells["left_only"],
            "right_only": cells["right_only"],
        },
        "exact_mcnemar_two_sided_p": exact_p,
        "excluded_not_answered_in_both": excluded,
    }


def gradeable(mission_ids) -> tuple[list[str], list[str]]:
    """Split the suite by whether the domain checker will accept the mission at all."""
    ok, ungradeable = [], []
    for mid in mission_ids:
        try:
            operator_contract_for_mission(mid)
            ok.append(mid)
        except ValueError:
            ungradeable.append(mid)
    return sorted(ok), sorted(ungradeable)


def required_fields(mission_id: str) -> list[str]:
    """The deliverable's top-level field names, from the operator contract.

    Telling the agent these is specification, not leakage: `output_witness_paths` names WHICH
    fields must exist, never what belongs in them. Withholding them measures whether a model
    can guess an undocumented schema, which is not the question. The first six trials failed
    on exactly that — the reconciliation was correct and arrived as `matched_record_pairs`
    inside a wrapper object, so the checker saw nothing it recognised.
    """
    contract = operator_contract_for_mission(mission_id)
    fields = {f for paths in contract.output_witness_paths.values() for f in paths}
    return sorted(fields | {"mission_id"})


def describe_shape(payload: dict) -> str:
    """The skeleton of an answer: field names and element forms, no values anywhere.

    This exists to separate two things the worked example confounded. Shown a full example
    the model reached 84% byte-identical conformance and 95% agreement on decisions; shown
    nothing it reached 0% and 1%. The gap was not knowledge of the task — inspecting the
    failures showed the model finding the right records and then writing them its own way,
    as objects where the reference used strings, with prefixes it invented.

    So the question the example could not answer is: how much of that gap is knowing the
    SHAPE, as opposed to having seen a solved case? This renders the shape alone, taken from
    a development-split mission of the same category, and gives away no answer.
    """

    def form(v):
        if isinstance(v, bool):
            return "true|false"
        if isinstance(v, (int, float)):
            return "number"
        if isinstance(v, str):
            return "string"
        if isinstance(v, list):
            if not v:
                return "list of ..."
            first = v[0]
            if isinstance(first, dict):
                return "list of objects with keys: " + ", ".join(sorted(first))
            return f"list of {form(first)}s"
        if isinstance(v, dict):
            return "object with keys: " + ", ".join(sorted(v))
        return "value"

    return "\n".join(f"  {k}: {form(v)}" for k, v in sorted(payload.items()))


def pick_example(mission: dict, missions: dict, gradeable_ids: set[str]) -> str | None:
    """A worked case from the development split, in the same category, never this mission.

    The checkers demand byte-identical output, down to a summary sentence with parenthesised
    plurals that nothing could guess. Conveying that by describing it in prose would be
    guesswork about what the description omits; showing one worked case conveys it exactly.

    The suite already provides the right pool. It designates 3 development missions per
    category against 7-8 held-out and 1-2 out-of-distribution, which is precisely the
    separation this needs: examples come from development, measurement happens on the rest,
    and no mission is ever shown its own answer or the answer of anything it is scored against.
    """
    candidates = sorted(
        mid
        for mid, m in missions.items()
        if m["category"] == mission["category"]
        and m["task_snapshot"].get("split") == "development"
        and mid != mission["mission_id"]
        and mid in gradeable_ids
    )
    return candidates[0] if candidates else None


def _canonical_scalar(value) -> str:
    return f"{type(value).__name__}:{json.dumps(value, ensure_ascii=False, sort_keys=True)}"


def _walk_scalars(value, key: str | None = None):
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _walk_scalars(child, child_key)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_scalars(child, key)
    elif value is not None:
        yield key, value


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _is_identity_key(key: str | None) -> bool:
    return bool(key and (key == "id" or key.endswith("_id") or key.endswith("_ids")))


def _is_enum_key(key: str | None) -> bool:
    return bool(
        key
        and (
            key in ENUM_FIELDS
            or key.endswith("_type")
            or key.endswith("_kind")
            or key.endswith("_status")
            or key.endswith("_code")
            or key.endswith("_parts")
        )
    )


def _literal_class(key: str | None, value) -> str:
    if key in GATE_BOUND_IDENTITY_FIELDS:
        return "gate_bound_identity"
    if value is None or isinstance(value, bool) or _is_enum_key(key):
        return "enum"
    if _is_identity_key(key):
        return "replaceable_id"
    return "replaceable_non_id"


def _surrogate_value(value, *, key: str | None, seed: str, forbidden: set[str]):
    kind = "id" if _is_identity_key(key) else "value"
    if key and "name" in key:
        kind = "name"
    elif key and ("date" in key or key.endswith("_at")):
        kind = "date"
    elif key and "time" in key and not key.endswith("zone"):
        kind = "time"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        kind = "number"

    for counter in range(10_000):
        digest = hashlib.sha256(
            f"{seed}\0{_canonical_scalar(value)}\0{counter}".encode("utf-8")
        ).hexdigest()
        if isinstance(value, int) and not isinstance(value, bool):
            candidate = 100_000 + int(digest[:8], 16) % 800_000
        elif isinstance(value, float):
            candidate = float(100_000 + int(digest[:8], 16) % 800_000) / 100.0
        elif key == "activity_id":
            candidate = digest[:32]
        elif kind == "date":
            candidate = f"209{int(digest[0], 16) % 10}-{1 + int(digest[1:3], 16) % 12:02d}-{1 + int(digest[3:5], 16) % 28:02d}"
        elif kind == "time":
            candidate = f"{int(digest[:2], 16) % 24:02d}:{int(digest[2:4], 16) % 60:02d}"
        elif kind == "name":
            candidate = f"Surrogate Name {digest[:10]}"
        elif kind == "id":
            candidate = f"redacted-id-{digest[:16]}"
        else:
            candidate = f"Redacted text {digest[:16]}"
        if _canonical_scalar(candidate) not in forbidden and candidate != value:
            return candidate
    raise RuntimeError("unable to construct a disjoint deterministic surrogate")


def redact_example(
    example_input: dict,
    example_output: dict,
    *,
    seed: str,
    forbidden_payloads,
) -> dict:
    """Redact one worked example with one seeded map shared by its input and output.

    Object key order, list lengths, JSON types, and declared enum vocabulary are preserved.
    Every other scalar, including IDs, names, amounts, dates, and free text, is substituted.
    Exact and normalized overlap is recorded; the all-82 preflight rejects blocking overlap.
    """
    forbidden = {
        _canonical_scalar(value)
        for payload in forbidden_payloads
        for _, value in _walk_scalars(payload)
    }
    substitutions: dict[str, object] = {}

    def transform(value, key: str | None = None):
        if isinstance(value, dict):
            return {child_key: transform(child, child_key) for child_key, child in value.items()}
        if isinstance(value, list):
            return [transform(child, key) for child in value]
        if value is None or _literal_class(key, value) in {"enum", "gate_bound_identity"}:
            return value
        map_key = _canonical_scalar(value)
        if map_key not in substitutions:
            substitutions[map_key] = _surrogate_value(
                value, key=key, seed=seed, forbidden=forbidden
            )
        return substitutions[map_key]

    redacted_input = transform(copy.deepcopy(example_input))
    redacted_output = transform(copy.deepcopy(example_output))
    canonical_map = json.dumps(
        sorted(substitutions.items()), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    audit = example_overlap_audit(
        redacted_input, redacted_output, forbidden_payloads=forbidden_payloads
    )
    return {
        "input_record": redacted_input,
        "output_record": redacted_output,
        "map_digest": hashlib.sha256(canonical_map).hexdigest(),
        "substitution_count": len(substitutions),
        "overlap_audit": audit,
    }


def _unicode_casefold(value) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def _canonical_number(value) -> str | None:
    if isinstance(value, bool) or value is None or not isinstance(value, (int, float, str)):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    normalized = format(number.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return f"number:{normalized or '0'}"


def _canonical_date(value) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:$|[T\s])", value.strip())
    if not match:
        return None
    return f"date:{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _normalized_id(value) -> str | None:
    normalized = _unicode_casefold(value)
    if normalized is None:
        return None
    return re.sub(r"[^\w]", "", normalized, flags=re.UNICODE)


def _replaceable_literals(records) -> list[tuple[str, str | None, object]]:
    return [
        (_literal_class(key, value), key, value)
        for record in records
        for key, value in _walk_scalars(record)
        if _literal_class(key, value).startswith("replaceable")
    ]


def example_overlap_audit(
    redacted_input: dict, redacted_output: dict, *, forbidden_payloads
) -> dict:
    """Audit exact, normalized, canonical, substring, ID, and derived-literal overlap."""
    measured_scalars = {
        _canonical_scalar(value)
        for payload in forbidden_payloads
        for _, value in _walk_scalars(payload)
    }
    measured_keys = {key for payload in forbidden_payloads for key in _walk_keys(payload)}
    overlaps = collections.defaultdict(set)
    for record in (redacted_input, redacted_output):
        for key, value in _walk_scalars(record):
            if _canonical_scalar(value) in measured_scalars:
                overlaps[_literal_class(key, value)].add(value)
    example_keys = set(_walk_keys(redacted_input)) | set(_walk_keys(redacted_output))

    redacted_replaceable = _replaceable_literals((redacted_input, redacted_output))
    measured_replaceable = _replaceable_literals(forbidden_payloads)
    measured_unicode = {
        normalized
        for _, _, value in measured_replaceable
        if (normalized := _unicode_casefold(value))
    }
    redacted_unicode = {
        normalized
        for _, _, value in redacted_replaceable
        if (normalized := _unicode_casefold(value))
    }
    measured_canonical = {
        canonical
        for _, _, value in measured_replaceable
        for canonical in (_canonical_number(value), _canonical_date(value))
        if canonical
    }
    redacted_canonical = {
        canonical
        for _, _, value in redacted_replaceable
        for canonical in (_canonical_number(value), _canonical_date(value))
        if canonical
    }
    measured_ids = {
        normalized
        for literal_class, _, value in measured_replaceable
        if literal_class == "replaceable_id" and (normalized := _normalized_id(value))
    }
    redacted_ids = {
        normalized
        for literal_class, _, value in redacted_replaceable
        if literal_class == "replaceable_id" and (normalized := _normalized_id(value))
    }

    def tokens(values):
        return {
            token
            for value in values
            if isinstance(value, str)
            for token in re.findall(r"\w+", _unicode_casefold(value) or "", flags=re.UNICODE)
            if len(token) >= 4
        }

    measured_values = [value for _, _, value in measured_replaceable]
    redacted_values = [value for _, _, value in redacted_replaceable]
    substring_overlaps = tokens(measured_values) & tokens(redacted_values)
    measured_strings = [
        normalized
        for value in measured_values
        if (normalized := _unicode_casefold(value)) and len(normalized) >= 6
    ]
    redacted_strings = [
        normalized
        for value in redacted_values
        if (normalized := _unicode_casefold(value)) and len(normalized) >= 6
    ]
    for measured in measured_strings:
        for redacted in redacted_strings:
            if measured in redacted or redacted in measured:
                substring_overlaps.add(measured if len(measured) <= len(redacted) else redacted)

    derived = set()
    for measured in measured_strings:
        digest = hashlib.sha256(measured.encode("utf-8")).hexdigest()
        for size in (8, 12, 16):
            prefix = digest[:size]
            if any(prefix in redacted for redacted in redacted_strings):
                derived.add(prefix)

    def stable(values):
        return sorted(values, key=lambda item: _canonical_scalar(item))

    result = {
        "shared_replaceable_non_id_literals": stable(overlaps["replaceable_non_id"]),
        "shared_replaceable_id_literals": stable(overlaps["replaceable_id"]),
        "shared_replaceable_unicode_casefold_literals": sorted(measured_unicode & redacted_unicode),
        "shared_canonical_date_number_literals": sorted(measured_canonical & redacted_canonical),
        "shared_normalized_id_literals": sorted(measured_ids & redacted_ids),
        "shared_replaceable_tokens_or_substrings": sorted(substring_overlaps),
        "shared_deterministically_derived_literals": sorted(derived),
        "shared_enum_literals": stable(overlaps["enum"]),
        "shared_gate_bound_identity_literals": stable(overlaps["gate_bound_identity"]),
        "shared_template_keys": sorted(example_keys & measured_keys),
        "interpretation": REDACTION_DIAGNOSTIC_CEILING,
    }
    blocking_fields = (
        "shared_replaceable_non_id_literals",
        "shared_replaceable_id_literals",
        "shared_replaceable_unicode_casefold_literals",
        "shared_canonical_date_number_literals",
        "shared_normalized_id_literals",
        "shared_deterministically_derived_literals",
    )
    result["blocking_replaceable_overlap"] = any(result[field] for field in blocking_fields)
    return result


def _gate_procedure_checksum() -> tuple[str, str]:
    checker_source_sha256 = hashlib.sha256(_OPERATOR_CHECKER_SOURCE.read_bytes()).hexdigest()
    policy = {
        "procedure_id": REDACTION_GATE_PROCEDURE_ID,
        "procedure_version": REDACTION_GATE_PROCEDURE_VERSION,
        "checker": "check_operator_output",
        "checker_source_sha256": checker_source_sha256,
        "input": "transformed example input payload",
        "output": "transformed example output payload",
        "required": "deterministic conformance",
        "human_holistic_verified": False,
    }
    checksum = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return checksum, checker_source_sha256


def redaction_competence_gate(
    example_mission_id: str,
    transformed_input: dict,
    transformed_output: dict,
    mission: dict,
) -> dict:
    """Run the suite's domain checker on the transformed pair, never semantic_match.

    Passing establishes only the deterministic invariants covered by the existing operator.
    It does not establish holistic competence or complete validity of preserved values.
    """
    verdict = grade(
        example_mission_id,
        transformed_input["payload"],
        transformed_output["payload"],
    )
    checksum, source_sha256 = _gate_procedure_checksum()
    deterministic_checks = mission.get("eval_spec", {}).get("deterministic_checks", [])
    return {
        "procedure_id": REDACTION_GATE_PROCEDURE_ID,
        "procedure_version": REDACTION_GATE_PROCEDURE_VERSION,
        "procedure_checksum": checksum,
        "checker_source_sha256": source_sha256,
        "operator_id": verdict.get("operator_id"),
        "checker_version": verdict.get("checker_version"),
        "mission_procedure_checksums": sorted(
            check.get("procedure_checksum")
            for check in deterministic_checks
            if check.get("required") and check.get("procedure_checksum")
        ),
        "deterministic_conformant": verdict.get("conformant") is True,
        "failed_invariants": verdict.get("failed_invariants", []),
        "blocked": verdict.get("blocked"),
        "block_reason": verdict.get("block_reason") or verdict.get("error"),
        "human_holistic_verified": False,
        "coverage_ceiling": (
            "existing deterministic operator invariants only; full semantic and human holistic "
            "competence remain unverified"
        ),
    }


def preflight_redacted_arm(
    missions: dict[str, dict],
    inputs: dict[str, dict],
    expected: dict[str, dict],
    gradeable_ids: set[str],
) -> dict:
    """Prepare and gate all 82 measurement examples before any router client is created."""
    targets = sorted(
        mid
        for mid in gradeable_ids
        if missions[mid]["task_snapshot"].get("split") in {"held_out", "ood"}
    )
    forbidden_payloads = [inputs[mid]["payload"] for mid in targets] + [
        expected[mid]["payload"] for mid in targets
    ]
    prepared_examples = {}
    gate_receipts = {}
    results = []
    failures = []
    for target_mid in targets:
        example_mid = pick_example(missions[target_mid], missions, gradeable_ids)
        if not example_mid:
            failure = {
                "target_mission_id": target_mid,
                "example_mission_id": None,
                "failed_invariants": ["no-category-matched-development-example"],
            }
            failures.append(failure)
            results.append(failure)
            continue
        redaction = redact_example(
            inputs[example_mid],
            expected[example_mid],
            seed=f"bare_redacted_example:{target_mid}:{example_mid}",
            forbidden_payloads=forbidden_payloads,
        )
        gate = redaction_competence_gate(
            example_mid,
            redaction["input_record"],
            redaction["output_record"],
            missions[example_mid],
        )
        overlap_passed = not redaction["overlap_audit"]["blocking_replaceable_overlap"]
        allowed = gate["deterministic_conformant"] and overlap_passed
        result = {
            "target_mission_id": target_mid,
            "example_mission_id": example_mid,
            "allowed": allowed,
            "competence_gate": gate,
            "overlap_gate_passed": overlap_passed,
            "overlap_audit": redaction["overlap_audit"],
        }
        if not allowed:
            failure = {
                "target_mission_id": target_mid,
                "example_mission_id": example_mid,
                "failed_invariants": gate["failed_invariants"]
                if not gate["deterministic_conformant"]
                else ["normalized-replaceable-overlap"],
                "competence_gate_passed": gate["deterministic_conformant"],
                "overlap_gate_passed": overlap_passed,
            }
            failures.append(failure)
        prepared_examples[target_mid] = redaction
        gate_receipts[target_mid] = gate
        results.append(result)

    arm_allowed = not failures and len(results) == len(targets) == 82
    report = {
        "candidate_arm": "bare_redacted_example",
        "evaluated_targets": len(results),
        "allowed": arm_allowed,
        "decision": "DIAGNOSTIC_ONLY" if arm_allowed else "HOLD",
        "passed_targets": sum(result.get("allowed") is True for result in results),
        "failed_targets": len(failures),
        "failures": failures,
        "results": results,
        "claim_ceiling": REDACTION_DIAGNOSTIC_CEILING,
        "human_holistic_competence_verified": False,
    }
    return {
        "report": report,
        "prepared_examples": prepared_examples,
        "gate_receipts": gate_receipts,
    }


def rendered_prompt_hash(user_content: str) -> str:
    """Bind the exact ordered system/user message bytes supplied to the router."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    rendered = json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def user_prompt(
    mission: dict,
    input_record: dict,
    example: tuple[dict, dict] | None = None,
    shape: str | None = None,
) -> str:
    ts = mission["task_snapshot"]
    title = ts.get("task_title") or ts.get("activity_title") or mission["category"]
    fields = required_fields(mission["mission_id"])
    parts = [f"Task: {title}", f"Category: {mission['category']}", ""]
    if example:
        ex_in, ex_out = example
        parts += [
            "A different case of this same kind, worked through, so that the exact shape of "
            "the answer is unambiguous. Its content has nothing to do with your case; only "
            "its encoding does — field names, how each element is written, and the exact "
            "wording of any summary line.",
            "",
            f"Example case:\n{json.dumps(ex_in['payload'], ensure_ascii=False)}",
            "",
            f"Answer for that example:\n{json.dumps(ex_out['payload'], ensure_ascii=False)}",
            "",
        ]
    if shape:
        parts += [
            "The answer's shape, so that its encoding is unambiguous. These are field names "
            "and element\nforms only — no values, and nothing about your case:",
            "",
            shape,
            "",
        ]
    parts += [
        "Now your case. Return a single JSON object with exactly these top-level fields and "
        f"no wrapper around them:\n  {', '.join(fields)}",
        f"`mission_id` is {mission['mission_id']}.",
        "",
        f"Case:\n{json.dumps(input_record['payload'], ensure_ascii=False, indent=1)}",
    ]
    return "\n".join(parts)


def parse(content: str) -> dict | None:
    text = cwm.strip_fences(content)
    if not text:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


def call(
    client,
    model: str,
    mission: dict,
    input_record: dict,
    pacer,
    example: tuple[dict, dict] | None = None,
    shape: str | None = None,
    rendered_user_prompt: str | None = None,
) -> tuple[dict | None, str, str | None]:
    last, backend = "unknown", None
    for attempt in range(cwm.MAX_RETRIES):
        if pacer:
            pacer.wait()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": rendered_user_prompt
                        if rendered_user_prompt is not None
                        else user_prompt(mission, input_record, example, shape),
                    },
                ],
                temperature=cwm.TEMPERATURE,
                max_tokens=4000,
                response_format={"type": "json_object"},
            )
            via = (getattr(resp, "model_extra", None) or {}).get("_routed_via")
            if isinstance(via, dict):
                backend = f"{via.get('platform')}/{via.get('model')}"
                if str(via.get("model") or "") != model:
                    last = f"substituted:{backend}"
                    if pacer:
                        pacer.refused()
                    continue
                if pacer:
                    pacer.served()
            ch = resp.choices or []
            got = parse(ch[0].message.content if ch else None)
            if got is not None:
                return got, "ok", backend
            last = "unparseable"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}:{str(exc)[:70]}"
        time.sleep(min(2**attempt, 8))
    return None, last, backend


def grade(mission_id: str, input_payload: dict, output: dict) -> dict:
    """The suite's own verdict, with its refusals passed through rather than smoothed."""
    try:
        r = check_operator_output(mission_id, input_payload, output)
    except Exception as exc:  # noqa: BLE001
        return {"conformant": None, "error": f"{type(exc).__name__}:{str(exc)[:90]}"}
    return {
        "conformant": bool(r.passed),
        "failed_invariants": list(r.failed_invariant_ids),
        "blocked": bool(r.blocked),
        "block_reason": r.block_reason,
        "operator_id": r.operator_id,
        "checker_version": r.checker_version,
    }


@click.command()
@click.option("--model", default=None, help="Rater, as named on the router.")
@click.option(
    "--arm",
    type=click.Choice(["bare", "bare_no_example", "bare_schema", "bare_redacted_example"]),
    default="bare",
    show_default=True,
    help="bare shows a worked development case to convey the required encoding. "
    "bare_no_example shows none; bare_schema shows only structure; bare_redacted_example "
    "is admitted only if every transformed example passes the independent domain checker. "
    "Any result is bundled-redaction sensitivity only, never a format/content/capability or "
    "causal arm effect.",
)
@click.option("--limit", default=None, type=int)
@click.option("--concurrency", default=4, show_default=True)
@click.option("--rpm", default=40.0, show_default=True)
@click.option(
    "--splits",
    default="held_out,ood",
    show_default=True,
    help="Which splits to measure on. Development missions supply the worked examples, so "
    "measuring on them would score a mission against a prompt built from its own kind.",
)
@click.option(
    "--grade-expected",
    is_flag=True,
    help="Grade the suite's own answers instead of running an agent. Every gradeable mission "
    "must come back conformant; anything else means the harness is wrong, not the agent.",
)
def main(model, arm, limit, concurrency, rpm, splits, grade_expected) -> None:
    missions, inputs, expected = load_suite()
    ok, ungradeable = gradeable(missions)
    click.echo(f"missions {len(missions)}   gradeable {len(ok)}   ungradeable {len(ungradeable)}")
    if ungradeable:
        click.echo("  ungradeable, excluded by name and counted, not dropped quietly:")
        for mid in ungradeable:
            click.echo(f"    {mid}")

    all_gradeable = set(ok)  # examples may come from any gradeable mission, incl. development
    wanted = {s.strip() for s in splits.split(",") if s.strip()}
    ok = [m for m in ok if missions[m]["task_snapshot"].get("split") in wanted]
    click.echo(f"measuring on splits {sorted(wanted)}: {len(ok)} missions")
    targets = ok[:limit] if limit else ok

    if grade_expected:
        counts = collections.Counter()
        for mid in targets:
            v = grade(mid, inputs[mid]["payload"], expected[mid]["payload"])
            counts["conformant" if v.get("conformant") else "NOT conformant"] += 1
        click.echo(f"\nthe suite's own answers, graded by the suite: {dict(counts)}")
        if counts["NOT conformant"]:
            click.echo(
                "  The harness is wrong. An answer that fails its own checker cannot "
                "be used to judge an agent."
            )
        return

    redaction_preflight = None
    if arm == "bare_redacted_example":
        redaction_preflight = preflight_redacted_arm(missions, inputs, expected, all_gradeable)
        report = redaction_preflight["report"]
        click.echo(
            f"\nredacted-example preflight: {report['passed_targets']}/"
            f"{report['evaluated_targets']} admitted; decision={report['decision']}"
        )
        if not report["allowed"]:
            for failure in report["failures"]:
                click.echo(
                    f"  {failure['target_mission_id']} <- "
                    f"{failure['example_mission_id']}: "
                    f"{failure['failed_invariants']}"
                )
            raise click.ClickException(
                "bare_redacted_example is HOLD: transformed examples failed the "
                "deterministic competence/overlap preflight; no model call was made"
            )

    if not model:
        raise click.ClickException("--model is required unless --grade-expected")
    key = os.environ.get(cwm.KEY_ENV)
    if not key:
        raise SystemExit(f"{cwm.KEY_ENV} is not set")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"TRIALS_{arm}_{re.sub(r'[^A-Za-z0-9._-]', '_', model)}.jsonl"
    run_spec = ARM_RUN_SPECS[arm]
    already = settled_ids(out_path, run_spec=run_spec, arm=arm)
    pending = [m for m in targets if m not in already]
    click.echo(f"\nmodel={model}  arm={arm}  endpoint={cwm.BASE_URL}")
    click.echo(f"already_done={len(already)}  pending={len(pending)}  -> {out_path}")
    if not pending:
        click.echo("nothing to do")
        return

    client = OpenAI(api_key=key, base_url=cwm.BASE_URL, timeout=180.0, max_retries=0)
    pacer = cwm.Pacer(rpm)
    lock = threading.Lock()
    counts = collections.Counter()
    stamp = datetime.now(timezone.utc).isoformat()
    with out_path.open("a", encoding="utf-8") as fh:

        def work(mid: str) -> None:
            ex_id = (
                pick_example(missions[mid], missions, all_gradeable)
                if arm in ("bare", "bare_schema", "bare_redacted_example")
                else None
            )
            redaction = None
            if ex_id and arm == "bare_redacted_example":
                redaction = redaction_preflight["prepared_examples"][mid]
                example = (redaction["input_record"], redaction["output_record"])
            else:
                example = (inputs[ex_id], expected[ex_id]) if (ex_id and arm == "bare") else None
            shape = (
                describe_shape(expected[ex_id]["payload"])
                if (ex_id and arm == "bare_schema")
                else None
            )
            prompt = user_prompt(missions[mid], inputs[mid], example, shape)
            deliverable, status, backend = call(
                client,
                model,
                missions[mid],
                inputs[mid],
                pacer,
                example,
                shape,
                rendered_user_prompt=prompt,
            )
            verdict = (
                grade(mid, inputs[mid]["payload"], deliverable)
                if deliverable is not None
                else {"conformant": None, "error": status}
            )
            rec = {
                "activity_id": mid,  # named for the resume helper; it is the mission id
                "mission_id": mid,
                "category": missions[mid]["category"],
                "task_activity_id": missions[mid]["task_snapshot"].get("activity_id"),
                "arm": arm,
                "split": missions[mid]["task_snapshot"].get("split"),
                "format_example_from": ex_id,
                "model_id": model,
                "backend": backend,
                "status": status,
                "deliverable": deliverable,
                "verdict": verdict,
                "measures": "deterministic conformance, not mission success",
                "run_spec": run_spec,
                "example_shown": example is not None,
                "shape_shown": shape is not None,
                "redaction_map_digest": redaction["map_digest"] if redaction else None,
                "redaction_substitution_count": (
                    redaction["substitution_count"] if redaction else None
                ),
                "rendered_prompt_hash": rendered_prompt_hash(prompt),
                "example_overlap_audit": redaction["overlap_audit"] if redaction else None,
                "redaction_competence_gate": (
                    redaction_preflight["gate_receipts"][mid] if redaction else None
                ),
                "redaction_diagnostic_ceiling": (
                    REDACTION_DIAGNOSTIC_CEILING if redaction else None
                ),
                "arm_comparison_scope": (
                    "paired historical diagnostic, not causal unless model snapshot, system "
                    "prompt, decoding, and endpoint are held fixed"
                    if redaction
                    else None
                ),
                "scored_at": stamp,
            }
            with lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                counts[
                    "conformant"
                    if verdict.get("conformant")
                    else "non-conformant"
                    if verdict.get("conformant") is False
                    else "no answer"
                ] += 1
                n = sum(counts.values())
                if n % 10 == 0 or n == len(pending):
                    click.echo(f"  {n}/{len(pending)} {dict(counts)}", err=True)

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            list(pool.map(work, pending))

    click.echo(f"\nthis invocation: {dict(counts)}")

    # Report from every trial on disk, not the slice this invocation happened to run, and
    # keep calls that never returned out of the denominator. Before this, a resumed run of
    # ten missions reported n=10 against an accumulated 82, and one transport failure moved
    # the rate by 1/n while looking like a non-conformant answer.
    settled = latest_trials(out_path, run_spec=run_spec, arm=arm)
    answered = {
        k: v
        for k, v in settled.items()
        if isinstance((v.get("verdict") or {}).get("conformant"), bool)
    }
    unanswered = len(settled) - len(answered)
    if answered:
        ok = sum(1 for v in answered.values() if v["verdict"]["conformant"])
        click.echo(
            f"\nACCUMULATED OVER {out_path.name}\n"
            f"  deterministic conformance: {ok}/{len(answered)} = {ok / len(answered):.1%}"
        )
        if unanswered:
            click.echo(
                f"  {unanswered} mission(s) never answered and are excluded from that "
                f"denominator rather than\n  counted as failures — a transport error is not "
                f"a non-conformant deliverable."
            )
    click.echo(
        "This is a necessary condition of the suite's success criterion and not a sufficient\n"
        "one: every mission also requires a human holistic review that this project will not\n"
        "perform. Do not report this number as task success."
    )


if __name__ == "__main__":
    main()
