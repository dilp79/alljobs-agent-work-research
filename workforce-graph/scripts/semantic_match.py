"""Compare an agent's answer with the reference by what it decided, not by how it wrote it.

Why this replaces the suite's own checker. That checker demands byte-identical output — the
same field order, the same element shapes, and an English summary sentence down to its
parenthesised plurals. It was written to validate the generator that produces the reference
answers, and for that it is exactly right. Used on an independent agent it measures something
else: whether the agent can reproduce an encoding it was never told. Shown a worked example
the model conformed on 69 of 82 missions; shown none, on 0 of 81. Nearly the whole figure was
the example.

The objection to writing our own comparator was that the verdicts would become ours, in a
study asking whether model judgements predict outcomes. That objection does not survive
inspection. The reference answers are not ours — they come with the suite. This module decides
only whether two answers say the same thing, and the fields it decides on are almost all
closed vocabularies of one to three values. That is establishing a fact, not forming a
judgement about whether a task suits an agent.

What is compared, declared here and not adjustable per run:

  decisions      closed-vocabulary fields — the label, the severity, the risk, whether
                 confirmation is pending. One to three distinct values across all 120
                 missions. These ARE the answer; getting them right is doing the work.
  membership     lists of records, sources and required fields, compared order-insensitively.
                 Identifiers establish membership; every expected non-ID scalar on an item is
                 required and compared. Extra declared decision fields fail closed, while
                 unknown extra metadata is named as uncovered rather than called verified.
  numbers        compared as numbers, so "0.80" and 0.8 agree.
  prose          rationale, diagnosis, draft, answer — NOT compared, and every mission reports
                 which of its fields went uncompared. A free-text explanation can be right in
                 a thousand wordings and no comparison of strings can tell.

The honest consequence, which must travel with any number this produces: a mission passing
here got the decisions and the memberships right. It says nothing about whether its written
reasoning was sound, because nothing here reads it.

Calibrations run before any agent is graded, because a lenient comparator would pass everything
and look like success:

  identity   every reference answer compared with itself must pass. If it does not, the
             comparator is broken.
  confusion  every ordered pair of different reference answers within the same category must
             fail. If those pass, the comparator is not discriminating and its verdicts are
             worthless.
  mutations  decision flips, membership non-ID flips, omitted fields, contradictory extra
             decision fields, numeric perturbations and identity swaps each report their own
             false-accept rate. Exempt prose is named as uncovered, never called checked.

Usage:
    python scripts/semantic_match.py --calibrate
"""

from __future__ import annotations

import collections
import copy
import itertools
import json
import re
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "benchmark" / "support_backoffice" / "v1"

#: Fields whose value is the decision. Measured across all 120 reference answers: each holds
#: between one and six distinct values, so agreeing on one is agreeing on the outcome.
DECISION_FIELDS = frozenset(
    {
        "completeness",
        "confirmation_status",
        "timezone",
        "tone",
        "recommended_next_step",
        "allowed_resolution",
        "confidence",
        "label",
        "corrective_action",
        "severity",
        "risk",
        "escalation_path",
        "owner",
    }
)

#: Fields holding sets of things, compared by membership rather than by arrangement.
MEMBERSHIP_FIELDS = frozenset(
    {
        "matched_records",
        "unmatched_records",
        "evidence",
        "required_fields",
        "grounded_sources",
    }
)

#: Free-text reasoning. Never compared, always reported as uncompared.
#: `discrepancy_summary` was first classified as a decision because it holds few distinct
#: values. Inspecting the disagreements showed it is a sentence restating counts — the
#: reference writes "record-pair: 1 match(es), 1 discrepancy(ies)." where the agent wrote
#: "1 matched, 1 discrepancy found". Identical facts, and the counts themselves are already
#: checked through matched_records and unmatched_records, so nothing is lost by not comparing
#: the sentence and a formatting difference stops being reported as a wrong decision.
PROSE_FIELDS = frozenset(
    {
        "rationale",
        "diagnosis",
        "draft",
        "answer",
        "issue",
        "determination",
        "discrepancy_summary",
    }
)

#: Identity. Must match exactly; an answer to another mission is not an answer.
IDENTITY_FIELDS = frozenset({"mission_id"})

# A membership element has two kinds of scalar fields. Identifier fields say which item the
# element is about. Decision fields say what was decided about that item. The latter are not
# arrangement: omitting `status=matched`, flipping it, or adding `severity=critical` changes
# the answer even when the record IDs are unchanged.
MEMBERSHIP_DECISION_FIELDS = DECISION_FIELDS | frozenset(
    {
        "status",
        "passed",
        "result",
        "outcome",
        "action",
        "resolution",
        "classification",
    }
)

_ID_KEYS = (
    "left_record_id",
    "right_record_id",
    "record_id",
    "source_id",
    "evidence_id",
    "id",
    "name",
    "field",
)

#: Deliberately absent: any attempt to pull an identifier out of free text, or to strip
#: prefixes an agent invented. "Observation evidence-10: score = 75" contains the right
#: identifier as a substring, and so would a sentence about the wrong one. A comparator that
#: accepts substrings stops discriminating, which is the only property that makes it worth
#: having. Where the agent chose its own representation, the answer is to tell it the shape
#: beforehand, not to guess afterwards.


def _norm_scalar(v):
    """Case and whitespace are not decisions; numbers written as strings are still numbers."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    if isinstance(v, str):
        s = re.sub(r"\s+", " ", v.strip()).casefold()
        try:
            return round(float(s), 6)
        except ValueError:
            return s
    return v


def _member_identity(item):
    """Stable identity for a membership item, excluding its decision-bearing descriptors."""
    if isinstance(item, str):
        return _norm_scalar(item)
    if isinstance(item, dict):
        ids = tuple((k, _norm_scalar(item[k])) for k in _ID_KEYS if k in item)
        if ids:
            return ids
        return tuple(
            sorted((k, _norm_scalar(v)) for k, v in item.items() if not isinstance(v, (dict, list)))
        )
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def _members(value) -> collections.Counter:
    if isinstance(value, list):
        return collections.Counter(_member_identity(x) for x in value)
    if value in (None, ""):
        return collections.Counter()
    return collections.Counter([_member_identity(value)])


def _membership_compare(field: str, want, got) -> dict:
    """Compare membership and every expected scalar descriptor on matching identified items.

    Policy:
    - identifiers determine which list element is which and list order is ignored;
    - every non-ID scalar present in the reference item is required and compared;
    - an extra scalar whose name is in the declared decision vocabulary is contradictory and
      fails closed;
    - other extra metadata is not treated as verified and is reported as uncovered.
    """
    membership_ok = _members(want) == _members(got)
    mismatches: list[str] = []
    missing: list[str] = []
    extra_decisions: list[str] = []
    uncovered: list[str] = []

    want_items = want if isinstance(want, list) else ([] if want in (None, "") else [want])
    got_items = got if isinstance(got, list) else ([] if got in (None, "") else [got])
    got_by_identity: dict[object, list] = collections.defaultdict(list)
    for item in got_items:
        got_by_identity[_member_identity(item)].append(item)

    for expected_item in want_items:
        if not isinstance(expected_item, dict):
            continue
        candidates = got_by_identity.get(_member_identity(expected_item), [])
        if not candidates or not isinstance(candidates[0], dict):
            continue
        actual_item = candidates.pop(0)
        for key, expected_value in expected_item.items():
            if key in _ID_KEYS:
                continue
            path = f"{field}[].{key}"
            if key not in actual_item:
                missing.append(path)
            elif _norm_scalar(expected_value) != _norm_scalar(actual_item[key]):
                mismatches.append(path)
        for key in actual_item.keys() - expected_item.keys():
            path = f"{field}[].{key}"
            if key in MEMBERSHIP_DECISION_FIELDS:
                extra_decisions.append(path)
            else:
                uncovered.append(path)

    return {
        "matched": membership_ok and not mismatches and not missing and not extra_decisions,
        "mismatches": sorted(mismatches),
        "missing": sorted(missing),
        "extra_decisions": sorted(extra_decisions),
        "uncovered": sorted(uncovered),
    }


def compare(expected: dict, actual: dict | None) -> dict:
    """Field-by-field verdict. `matched` is true only when nothing decidable disagreed."""
    if not isinstance(actual, dict):
        return {
            "matched": False,
            "reason": "no answer object",
            "compared": [],
            "mismatched": [],
            "missing": [],
            "extra_decision_fields": [],
            "membership_mismatches": [],
            "exempt": [],
            "uncovered_actual_fields": [],
            "claim_ceiling": "no semantic agreement can be established",
        }

    # An agent may nest its deliverable under the deliverable's name; that is arrangement.
    if len(actual) == 1:
        only = next(iter(actual.values()))
        if isinstance(only, dict):
            actual = only

    compared, mismatched, missing, exempt = [], [], [], []
    membership_mismatches: list[str] = []
    extra_decision_fields: list[str] = []
    uncovered_actual_fields: list[str] = []
    for field, want in expected.items():
        if field in PROSE_FIELDS:
            exempt.append(field)
            continue
        if field not in actual:
            missing.append(field)
            continue
        got = actual[field]
        if field in MEMBERSHIP_FIELDS:
            detail = _membership_compare(field, want, got)
            ok = detail["matched"]
            membership_mismatches.extend(detail["mismatches"])
            membership_mismatches.extend(detail["missing"])
            membership_mismatches.extend(detail["extra_decisions"])
            missing.extend(detail["missing"])
            extra_decision_fields.extend(detail["extra_decisions"])
            uncovered_actual_fields.extend(detail["uncovered"])
        elif field in DECISION_FIELDS or field in IDENTITY_FIELDS:
            ok = _norm_scalar(want) == _norm_scalar(got)
        elif isinstance(want, list):
            ok = _members(want) == _members(got)
        else:
            ok = _norm_scalar(want) == _norm_scalar(got)
        compared.append(field)
        if not ok:
            mismatched.append(field)

    for field in actual.keys() - expected.keys():
        if field in DECISION_FIELDS or field in IDENTITY_FIELDS or field in MEMBERSHIP_FIELDS:
            extra_decision_fields.append(field)
        else:
            uncovered_actual_fields.append(field)

    return {
        "matched": not mismatched and not missing and not extra_decision_fields,
        "compared": compared,
        "mismatched": mismatched,
        "missing": sorted(set(missing)),
        "extra_decision_fields": sorted(set(extra_decision_fields)),
        "membership_mismatches": sorted(set(membership_mismatches)),
        "exempt": exempt,
        "uncovered_actual_fields": sorted(set(uncovered_actual_fields)),
        "claim_ceiling": (
            "agreement on compared decisions and memberships only; does not verify exempt prose"
        ),
    }


def compare_legacy(expected: dict, actual: dict | None) -> dict:
    """Reproduce the pre-hardening comparator for historical freeze transparency only.

    This intentionally preserves the old defects: membership dictionaries are reduced to ID
    fields, required non-ID membership fields may be omitted, and extra decision fields are
    ignored. New grading must use `compare`; this function exists only to show whether the
    hardened policy changes a previously reported per-mission verdict.
    """
    if not isinstance(actual, dict):
        return {"matched": False, "reason": "no answer object"}
    if len(actual) == 1:
        only = next(iter(actual.values()))
        if isinstance(only, dict):
            actual = only

    mismatched = []
    missing = []
    exempt = []

    def legacy_member_key(item):
        if isinstance(item, str):
            return _norm_scalar(item)
        if isinstance(item, dict):
            identifiers = tuple(_norm_scalar(item[key]) for key in _ID_KEYS if key in item)
            if identifiers:
                return identifiers
            return tuple(
                sorted(
                    (key, _norm_scalar(value))
                    for key, value in item.items()
                    if not isinstance(value, (dict, list))
                )
            )
        return json.dumps(item, sort_keys=True, ensure_ascii=False)

    def legacy_members(value):
        if isinstance(value, list):
            return collections.Counter(legacy_member_key(item) for item in value)
        if value in (None, ""):
            return collections.Counter()
        return collections.Counter([legacy_member_key(value)])

    for field, want in expected.items():
        if field in PROSE_FIELDS:
            exempt.append(field)
            continue
        if field not in actual:
            missing.append(field)
            continue
        got = actual[field]
        if field in MEMBERSHIP_FIELDS or isinstance(want, list):
            ok = legacy_members(want) == legacy_members(got)
        else:
            ok = _norm_scalar(want) == _norm_scalar(got)
        if not ok:
            mismatched.append(field)
    return {
        "matched": not mismatched and not missing,
        "mismatched": mismatched,
        "missing": missing,
        "exempt": exempt,
        "historical_only": True,
    }


def load_expected() -> dict[str, dict]:
    return {
        json.loads(line)["mission_id"]: json.loads(line)["payload"]
        for line in (SUITE / "fixtures" / "expected_outputs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }


def _flip(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    return "__calibration_flip__" if value != "__calibration_flip__" else "__other_flip__"


def _mutate_numeric(value) -> tuple[object, bool]:
    """Perturb the first numeric leaf, including a numeric string, without changing shape."""
    if isinstance(value, bool) or value is None:
        return value, False
    if isinstance(value, int):
        return value + 1, True
    if isinstance(value, float):
        return value + 0.5, True
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value, False
        if re.fullmatch(r"[+-]?\d+", value.strip()):
            return str(int(number) + 1), True
        return format(number + 0.5, ".2f"), True
    if isinstance(value, list):
        out = copy.deepcopy(value)
        for index, item in enumerate(out):
            out[index], changed = _mutate_numeric(item)
            if changed:
                return out, True
        return out, False
    if isinstance(value, dict):
        out = copy.deepcopy(value)
        for key in out:
            if key in _ID_KEYS or key in IDENTITY_FIELDS:
                continue
            out[key], changed = _mutate_numeric(out[key])
            if changed:
                return out, True
        return out, False
    return value, False


def _calibration_result(attempted: int, false_accepts: int) -> dict:
    return {
        "attempted": attempted,
        "false_accepts": false_accepts,
        "false_accept_rate": false_accepts / attempted if attempted else None,
    }


def mutation_calibration(expected: dict[str, dict]) -> dict[str, dict]:
    """False-accept calibration over six deterministic mutation classes."""
    counts = collections.defaultdict(lambda: [0, 0])
    mission_ids = sorted(expected)
    for index, mid in enumerate(mission_ids):
        payload = expected[mid]

        decision_fields = sorted(set(payload) & DECISION_FIELDS)
        if decision_fields:
            actual = copy.deepcopy(payload)
            field = decision_fields[0]
            actual[field] = _flip(actual[field])
            counts["decision_flip"][0] += 1
            counts["decision_flip"][1] += int(compare(payload, actual)["matched"])

        mutated_membership = False
        for field in sorted(set(payload) & MEMBERSHIP_FIELDS):
            items = payload[field] if isinstance(payload[field], list) else []
            for item_index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                non_ids = [key for key in item if key not in _ID_KEYS]
                if not non_ids:
                    continue
                actual = copy.deepcopy(payload)
                key = sorted(non_ids)[0]
                actual[field][item_index][key] = _flip(item[key])
                counts["membership_non_id_flip"][0] += 1
                counts["membership_non_id_flip"][1] += int(compare(payload, actual)["matched"])
                mutated_membership = True
                break
            if mutated_membership:
                break

        required = sorted(set(payload) - PROSE_FIELDS - IDENTITY_FIELDS)
        if required:
            actual = copy.deepcopy(payload)
            del actual[required[0]]
            counts["omitted_field"][0] += 1
            counts["omitted_field"][1] += int(compare(payload, actual)["matched"])

        extra_fields = sorted(DECISION_FIELDS - set(payload))
        if extra_fields:
            actual = copy.deepcopy(payload)
            actual[extra_fields[0]] = "__contradictory_extra__"
            counts["contradictory_extra_field"][0] += 1
            counts["contradictory_extra_field"][1] += int(compare(payload, actual)["matched"])

        actual, changed = _mutate_numeric(payload)
        if changed:
            counts["numeric_perturbation"][0] += 1
            counts["numeric_perturbation"][1] += int(compare(payload, actual)["matched"])

        actual = copy.deepcopy(payload)
        actual["mission_id"] = mission_ids[(index + 1) % len(mission_ids)]
        counts["identity_swap"][0] += 1
        counts["identity_swap"][1] += int(compare(payload, actual)["matched"])

    classes = (
        "decision_flip",
        "membership_non_id_flip",
        "omitted_field",
        "contradictory_extra_field",
        "numeric_perturbation",
        "identity_swap",
    )
    return {name: _calibration_result(*counts[name]) for name in classes}


def cross_mission_calibration(expected: dict[str, dict]) -> dict:
    """Compare all ordered pairs of different missions within each category."""
    by_category: dict[str, list[str]] = collections.defaultdict(list)
    for mid in expected:
        by_category[mid.rsplit("-", 1)[0]].append(mid)
    pairs = false_accepts = 0
    for mids in by_category.values():
        for wanted, supplied in itertools.permutations(sorted(mids), 2):
            pairs += 1
            false_accepts += int(compare(expected[wanted], expected[supplied])["matched"])
    return {
        "ordered_pairs": pairs,
        "false_accepts": false_accepts,
        "false_accept_rate": false_accepts / pairs if pairs else None,
    }


def coverage_report(expected: dict[str, dict]) -> dict:
    uncovered = sorted(
        {field for payload in expected.values() for field in compare(payload, payload)["exempt"]}
    )
    return {
        "uncovered_fields": uncovered,
        "policy": "exempt_not_verified",
        "claim_ceiling": "passing answers are not verified on these fields",
    }


@click.command()
@click.option("--calibrate", is_flag=True, help="Run both calibrations and report.")
def main(calibrate: bool) -> None:
    expected = load_expected()
    click.echo(f"reference answers: {len(expected)}")

    if not calibrate:
        click.echo("nothing to do; pass --calibrate")
        return

    identity = sum(1 for mid, p in expected.items() if compare(p, p)["matched"])
    click.echo(f"\nIDENTITY  every answer against itself: {identity}/{len(expected)}")
    if identity != len(expected):
        click.echo("  The comparator is broken. Stop here.")
        return

    confusion = cross_mission_calibration(expected)
    pairs = confusion["ordered_pairs"]
    confused = confusion["false_accepts"]
    click.echo(
        f"CONFUSION every answer against a different mission of its own category: "
        f"{confused}/{pairs} wrongly matched"
    )
    if confused:
        click.echo(
            "  The comparator accepts answers to other questions. Its verdicts cannot be used."
        )
    else:
        click.echo("  It discriminates: no answer passes as the answer to a different mission.")

    click.echo("\nMUTATION FALSE-ACCEPT CALIBRATION")
    for name, result in mutation_calibration(expected).items():
        rate = result["false_accept_rate"]
        click.echo(
            f"  {name}: {result['false_accepts']}/{result['attempted']} false accepts ({rate:.1%})"
        )

    coverage = coverage_report(expected)
    click.echo(f"\nuncovered fields (exempt, not verified): {coverage['uncovered_fields']}")
    click.echo("  A mission passing this comparison got its decisions and memberships right.")
    click.echo("  Exempt prose is not read, checked, or vouched for by this comparator.")


if __name__ == "__main__":
    main()
