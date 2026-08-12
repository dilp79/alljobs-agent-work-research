"""Freeze and compare hash-bound work-mode labelling states.

The bulk-label JSONL files can be append-only while a rater is still running.  A snapshot
therefore opens each input once, fixes the byte length from ``fstat``, reads exactly that
prefix into one buffer, and derives the hash, line counts, labels, and partition from that
same buffer.  Appends that happen after ``fstat`` are outside the snapshot by construction.

Usage:
    python scripts/freeze_work_mode_snapshot.py freeze \
      --output data/work_mode/work_mode_baseline_2026-08-11_incomplete-third-rater.json \
      --snapshot-date 2026-08-11 --third-rater gemini-3.5-flash-lite \
      --third-rater-status incomplete

    python scripts/freeze_work_mode_snapshot.py audit \
      --baseline data/work_mode/work_mode_baseline_2026-08-11_incomplete-third-rater.json \
      --final data/work_mode/work_mode_final_YYYY-MM-DD.json --output /tmp/transition.json
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parent.parent
WM_DIR = ROOT / "data" / "work_mode"
MODES = ("screen", "mixed", "physical")
STRATA = ("contested", "control")
SNAPSHOT_SCHEMA = "alljobs.work-mode-snapshot/v1"
AUDIT_SCHEMA = "alljobs.work-mode-transition-audit/v1"
EXPECTED_CORPUS_SIZE = 18_796
EXPLICIT_NONRESPONSE_STATUS = "complete_with_explicit_nonresponse"
MAX_EXPLICIT_NONRESPONSES = 1
MIN_CACHE_BUSTED_RECORDS = 5
MIN_ATTEMPT_RECEIPTS = 20
NONRESPONSE_CLAIM_CEILING = (
    "no valid third-rater label after exact-route attempts; per-attempt content outcome and "
    "provider-side cause are not established"
)


class SnapshotInputError(ValueError):
    """An input cannot support a byte-bound, reproducible snapshot."""


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def payload_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _read_fixed_prefix(path: Path) -> tuple[bytes, dict[str, object]]:
    """Read the size observed at open exactly once; later appends are not admitted."""
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        expected = opened.st_size
        data = handle.read(expected)
        if len(data) != expected:
            raise SnapshotInputError(
                f"{path}: expected {expected} bytes from fstat but read {len(data)}"
            )
    after = path.stat()
    return data, {
        "size_at_open": expected,
        "size_after_read": after.st_size,
        "appended_during_read": after.st_size > expected,
        "modified_during_read": (
            after.st_size != expected or after.st_mtime_ns != opened.st_mtime_ns
        ),
    }


def snapshot_jsonl_input(
    path: Path,
    *,
    role: str,
    identity: str,
    allow_incomplete_tail: bool = False,
) -> tuple[dict[str, object], list[dict]]:
    """Return a manifest and parsed records derived from the same one-read byte buffer."""
    data, read_observation = _read_fixed_prefix(path)
    line_count = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    pieces = data.splitlines(keepends=True)
    records: list[dict] = []
    incomplete_tail: dict[str, object] | None = None

    for index, raw in enumerate(pieces, start=1):
        complete_by_delimiter = raw.endswith((b"\n", b"\r"))
        content = raw.rstrip(b"\r\n")
        if not content.strip():
            continue
        try:
            decoded = content.decode("utf-8")
            record = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            is_last_undelimited = index == len(pieces) and not complete_by_delimiter
            if is_last_undelimited and allow_incomplete_tail:
                incomplete_tail = {
                    "line_number": index,
                    "byte_length": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "excluded_from_derivation": True,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
                continue
            kind = "torn trailing line" if is_last_undelimited else "invalid complete line"
            raise SnapshotInputError(f"{path}:{index}: {kind}: {exc}") from exc
        if not isinstance(record, dict):
            raise SnapshotInputError(f"{path}:{index}: JSON record must be an object")
        records.append(record)

    successful_modes = set(MODES) | ({"unclear"} if role == "unclear_experiment" else set())
    successful = {
        str(record.get("activity_id"))
        for record in records
        if record.get("activity_id") and record.get("mode") in successful_modes
    }
    manifest = {
        "path": _relative(path),
        "role": role,
        "identity": identity,
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_length": len(data),
        "line_count": line_count,
        "parsed_record_count": len(records),
        "unique_successful_labels": len(successful),
        "ends_with_newline": not data or data.endswith(b"\n"),
        "incomplete_tail": incomplete_tail,
        "read_observation": read_observation,
    }
    return manifest, records


def _last_successful_labels(records: Iterable[dict]) -> tuple[dict[str, str], set[str]]:
    labels: dict[str, str] = {}
    observed: set[str] = set()
    for record in records:
        activity_id = record.get("activity_id")
        if not activity_id:
            continue
        activity_id = str(activity_id)
        observed.add(activity_id)
        if record.get("mode") in MODES:
            labels[activity_id] = str(record["mode"])
    return labels, observed


def _explicit_nonresponse_receipt(
    records: Iterable[dict],
    *,
    activity_id: str,
    third_rater: str,
    requested_model_id: str,
) -> dict[str, object]:
    """Prove repeated exact-route attempts yielded no valid label without imputing one."""
    target = [row for row in records if str(row.get("activity_id")) == activity_id]
    if any(row.get("mode") in MODES for row in target):
        raise SnapshotInputError(
            f"explicit nonresponse {activity_id}: a successful third-rater label exists"
        )
    recovery = [
        row
        for row in target
        if isinstance(row.get("cache_nonce"), int)
        and not isinstance(row.get("cache_nonce"), bool)
    ]
    if len(recovery) < MIN_CACHE_BUSTED_RECORDS:
        raise SnapshotInputError(
            f"explicit nonresponse {activity_id}: only {len(recovery)} cache-busted records; "
            f"minimum is {MIN_CACHE_BUSTED_RECORDS}"
        )
    expected_backend = f"openrouter/{requested_model_id}"
    prompt_hashes: set[str] = set()
    request_max_tokens: list[int] = []
    for row in recovery:
        if (
            row.get("status") != "unparseable:None"
            or row.get("model_id") != third_rater
            or row.get("requested_model_id") != requested_model_id
            or row.get("backend") != expected_backend
        ):
            raise SnapshotInputError(
                f"explicit nonresponse {activity_id}: recovery record route/status drift"
            )
        prompt_hash = row.get("prompt_hash")
        if not isinstance(prompt_hash, str) or not prompt_hash:
            raise SnapshotInputError(
                f"explicit nonresponse {activity_id}: missing prompt receipt"
            )
        prompt_hashes.add(prompt_hash)
        attempts = row.get("attempt_receipts")
        if not isinstance(attempts, list) or not attempts:
            raise SnapshotInputError(
                f"explicit nonresponse {activity_id}: missing attempt receipts"
            )
        for attempt in attempts:
            token_limit = attempt.get("request_max_tokens") if isinstance(attempt, dict) else None
            if (
                not isinstance(attempt, dict)
                or attempt.get("provider") != "openrouter"
                or attempt.get("served_model_id") != requested_model_id
                or not isinstance(token_limit, int)
                or isinstance(token_limit, bool)
            ):
                raise SnapshotInputError(
                    f"explicit nonresponse {activity_id}: attempt receipt route/cache drift"
                )
            request_max_tokens.append(token_limit)
    if len(prompt_hashes) != 1:
        raise SnapshotInputError(
            f"explicit nonresponse {activity_id}: expected one prompt hash; got {len(prompt_hashes)}"
        )
    if len(request_max_tokens) < MIN_ATTEMPT_RECEIPTS:
        raise SnapshotInputError(
            f"explicit nonresponse {activity_id}: only {len(request_max_tokens)} attempts; "
            f"minimum is {MIN_ATTEMPT_RECEIPTS}"
        )
    if len(set(request_max_tokens)) != len(request_max_tokens):
        raise SnapshotInputError(
            f"explicit nonresponse {activity_id}: request cache keys are not unique"
        )
    return {
        "activity_id": activity_id,
        "attempt_receipt_count": len(request_max_tokens),
        "cache_busted_record_count": len(recovery),
        "prompt_hash": next(iter(prompt_hashes)),
        "requested_model_id": requested_model_id,
        "served_backend": expected_backend,
        "status": "exact_route_no_valid_label",
        "terminal_none_record_count": len(recovery),
        "claim_ceiling": NONRESPONSE_CLAIM_CEILING,
    }


def build_snapshot(
    label_paths: Iterable[Path],
    adjudication_paths: Iterable[Path],
    experiment_paths: Iterable[Path] = (),
    *,
    snapshot_date: str,
    third_rater: str,
    third_rater_status: str,
    third_rater_nonresponses: Iterable[str] = (),
    third_rater_request_model: str | None = None,
    allow_incomplete_tail: bool = False,
) -> dict[str, object]:
    """Build a deterministic state from one-read manifests and their in-memory records."""
    inputs: list[dict[str, object]] = []
    readings: dict[str, dict[str, str]] = collections.defaultdict(dict)
    observed_activity_ids: set[str] = set()
    adjudicated: dict[str, str] = {}
    historical_arms: dict[str, dict[str, str]] = collections.defaultdict(dict)
    third_rater_records: list[dict] | None = None

    for path in sorted(Path(p) for p in label_paths):
        suffix = "__r0.jsonl"
        if not path.name.endswith(suffix):
            raise SnapshotInputError(f"{path}: bulk-label input must end in {suffix}")
        rater = path.name[: -len(suffix)]
        manifest, records = snapshot_jsonl_input(
            path,
            role="bulk_label",
            identity=rater,
            allow_incomplete_tail=allow_incomplete_tail,
        )
        inputs.append(manifest)
        labels, observed = _last_successful_labels(records)
        if rater == third_rater:
            if third_rater_records is not None:
                raise SnapshotInputError(f"multiple bulk inputs for third rater {third_rater}")
            third_rater_records = records
        observed_activity_ids.update(observed)
        for activity_id, label in labels.items():
            readings[activity_id][rater] = label

    for path in sorted(Path(p) for p in adjudication_paths):
        adjudicator = path.stem.removeprefix("ADJ_")
        manifest, records = snapshot_jsonl_input(
            path,
            role="adjudication",
            identity=adjudicator,
            allow_incomplete_tail=allow_incomplete_tail,
        )
        inputs.append(manifest)
        labels, observed = _last_successful_labels(records)
        observed_activity_ids.update(observed)
        adjudicated.update(labels)

    for path in sorted(Path(p) for p in experiment_paths):
        experiment_rater = path.stem.removeprefix("UNCLEAR_")
        manifest, records = snapshot_jsonl_input(
            path,
            role="unclear_experiment",
            identity=experiment_rater,
            allow_incomplete_tail=allow_incomplete_tail,
        )
        inputs.append(manifest)
        for record in records:
            activity_id = record.get("activity_id")
            arm = record.get("arm")
            if activity_id and arm in STRATA:
                historical_arms[str(activity_id)][experiment_rater] = str(arm)

    normalized_status = third_rater_status.strip().lower()
    nonresponse_ids = tuple(str(value) for value in third_rater_nonresponses)
    if len(set(nonresponse_ids)) != len(nonresponse_ids):
        raise SnapshotInputError("explicit nonresponse activity IDs must be unique")
    if normalized_status == EXPLICIT_NONRESPONSE_STATUS:
        if len(nonresponse_ids) != MAX_EXPLICIT_NONRESPONSES:
            raise SnapshotInputError(
                f"{EXPLICIT_NONRESPONSE_STATUS} requires exactly "
                f"{MAX_EXPLICIT_NONRESPONSES} explicit nonresponse"
            )
        if not third_rater_request_model:
            raise SnapshotInputError(
                f"{EXPLICIT_NONRESPONSE_STATUS} requires --third-rater-request-model"
            )
        if third_rater_records is None:
            raise SnapshotInputError(f"missing bulk input for third rater {third_rater}")
        nonresponse_receipts = [
            _explicit_nonresponse_receipt(
                third_rater_records,
                activity_id=activity_id,
                third_rater=third_rater,
                requested_model_id=third_rater_request_model,
            )
            for activity_id in sorted(nonresponse_ids)
        ]
    elif nonresponse_ids or third_rater_request_model:
        raise SnapshotInputError(
            "explicit nonresponse arguments require third-rater-status "
            f"{EXPLICIT_NONRESPONSE_STATUS}"
        )
    else:
        nonresponse_receipts = []

    activities: dict[str, dict[str, object]] = {}
    label_source = collections.Counter()
    stratum_counts = collections.Counter()
    settlement_counts = collections.Counter()
    n_raters_counts = collections.Counter()
    label_counts = collections.Counter()
    for activity_id in sorted(observed_activity_ids | set(adjudicated)):
        per_rater = dict(sorted(readings.get(activity_id, {}).items()))
        modes = set(per_rater.values())
        n_raters = len(per_rater)
        if len(modes) > 1:
            stratum = "contested"
        elif len(modes) == 1:
            stratum = "control"
        else:
            stratum = "unobserved"

        if activity_id in nonresponse_ids:
            label = None
            source = "third_rater_explicit_nonresponse"
        elif activity_id in adjudicated:
            label = adjudicated[activity_id]
            source = "adjudicated"
        elif n_raters >= 2 and len(modes) == 1:
            label = next(iter(modes))
            source = "unanimous_at_least_two"
        elif n_raters < 2:
            label = None
            source = "fewer_than_two_raters"
        else:
            label = None
            source = "split_awaiting_adjudication"
        settlement = "settled" if label else "unsettled"

        activities[activity_id] = {
            "label": label,
            "stratum": stratum,
            "n_raters": n_raters,
            "readings": per_rater,
            "successful_label_values": sorted(modes),
            "label_source": source,
            "settlement": settlement,
            "historical_experiment_arms": dict(
                sorted(historical_arms.get(activity_id, {}).items())
            ),
        }
        label_source[source] += 1
        stratum_counts[stratum] += 1
        settlement_counts[settlement] += 1
        n_raters_counts[str(n_raters)] += 1
        label_counts[label or "unsettled"] += 1

    payload: dict[str, object] = {
        "schema": SNAPSHOT_SCHEMA,
        "snapshot_date": snapshot_date,
        "snapshot_status": {
            "third_rater": third_rater,
            "third_rater_status": third_rater_status,
            "third_rater_complete": normalized_status == "complete",
            "third_rater_collection_complete": normalized_status
            in {"complete", EXPLICIT_NONRESPONSE_STATUS},
            "third_rater_nonresponses": nonresponse_receipts,
            "claim_ceiling": (
                "interim hash-bound baseline; not final work-mode evidence"
                if normalized_status not in {"complete", EXPLICIT_NONRESPONSE_STATUS}
                else (
                    "hash-bound collection with one explicit nonresponse retained as unsettled; "
                    "downstream validity gates still apply"
                    if normalized_status == EXPLICIT_NONRESPONSE_STATUS
                    else "hash-bound snapshot; downstream validity gates still apply"
                )
            ),
        },
        "input_scope": (
            "bulk work-mode labels, adjudications, and explicitly selected UNCLEAR "
            "experiment files; downstream database and employment crosswalk are not frozen here"
        ),
        "inputs": inputs,
        "partition_counts": {
            "activities": len(activities),
            "stratum": dict(sorted(stratum_counts.items())),
            "settlement": dict(sorted(settlement_counts.items())),
            "n_raters": dict(sorted(n_raters_counts.items())),
            "label": dict(sorted(label_counts.items())),
            "label_source": dict(sorted(label_source.items())),
        },
        "activities": activities,
    }
    payload["snapshot_payload_sha256"] = payload_sha256(payload)
    return payload


def verify_snapshot(snapshot: dict[str, object]) -> None:
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise SnapshotInputError(f"unsupported snapshot schema: {snapshot.get('schema')!r}")
    expected = snapshot.get("snapshot_payload_sha256")
    without_hash = dict(snapshot)
    without_hash.pop("snapshot_payload_sha256", None)
    actual = payload_sha256(without_hash)
    if expected != actual:
        raise SnapshotInputError(
            f"snapshot payload hash mismatch: recorded {expected!r}, derived {actual}"
        )


def completion_gate_failures(
    snapshot: dict[str, object],
    *,
    expected_corpus_size: int = EXPECTED_CORPUS_SIZE,
    baseline: dict[str, object] | None = None,
) -> list[str]:
    """Return every reason a snapshot cannot truthfully declare its third route complete."""
    failures: list[str] = []
    status = snapshot.get("snapshot_status", {})
    if not isinstance(status, dict):
        return ["snapshot_status must be an object"]
    third_rater = status.get("third_rater")
    if not isinstance(third_rater, str) or not third_rater:
        failures.append("third_rater must be a non-empty string")
    if status.get("third_rater_collection_complete") is not True:
        failures.append("third_rater_collection_complete is not true")
    normalized_status = str(status.get("third_rater_status", "")).strip().lower()
    nonresponses = status.get("third_rater_nonresponses")
    if not isinstance(nonresponses, list):
        failures.append("third_rater_nonresponses must be a list")
        nonresponses = []
    if normalized_status == "complete":
        if status.get("third_rater_complete") is not True or nonresponses:
            failures.append("complete status requires all labels and no explicit nonresponses")
    elif normalized_status == EXPLICIT_NONRESPONSE_STATUS:
        if status.get("third_rater_complete") is not False or len(nonresponses) != 1:
            failures.append(
                f"{EXPLICIT_NONRESPONSE_STATUS} requires one explicit nonresponse and no all-label claim"
            )
    else:
        failures.append(f"unsupported collection-complete status: {normalized_status!r}")

    nonresponse_ids: set[str] = set()
    for proof in nonresponses:
        activity_id = proof.get("activity_id") if isinstance(proof, dict) else None
        proof_valid = (
            isinstance(proof, dict)
            and isinstance(activity_id, str)
            and bool(activity_id)
            and isinstance(proof.get("cache_busted_record_count"), int)
            and proof["cache_busted_record_count"] >= MIN_CACHE_BUSTED_RECORDS
            and isinstance(proof.get("attempt_receipt_count"), int)
            and proof["attempt_receipt_count"] >= MIN_ATTEMPT_RECEIPTS
            and proof["attempt_receipt_count"]
            >= 4 * proof["cache_busted_record_count"]
            and isinstance(proof.get("prompt_hash"), str)
            and bool(proof["prompt_hash"])
            and isinstance(proof.get("requested_model_id"), str)
            and proof.get("served_backend") == f"openrouter/{proof.get('requested_model_id')}"
            and proof.get("status") == "exact_route_no_valid_label"
            and proof.get("terminal_none_record_count")
            == proof.get("cache_busted_record_count")
            and proof.get("claim_ceiling") == NONRESPONSE_CLAIM_CEILING
        )
        if not proof_valid:
            failures.append(f"explicit nonresponse proof for {activity_id} is invalid")
        if isinstance(activity_id, str):
            nonresponse_ids.add(activity_id)
    if len(nonresponse_ids) != len(nonresponses):
        failures.append("explicit nonresponse activity IDs are missing or duplicated")

    if baseline is None:
        failures.append("a hash-valid baseline snapshot is required for a complete declaration")
    else:
        baseline_activities = baseline.get("activities", {})
        if not isinstance(baseline_activities, dict) or len(baseline_activities) != expected_corpus_size:
            observed = (
                len(baseline_activities) if isinstance(baseline_activities, dict) else "non-object"
            )
            failures.append(
                f"baseline activity inventory is {observed}; expected {expected_corpus_size}"
            )
        if status.get("completion_baseline_payload_sha256") != baseline.get(
            "snapshot_payload_sha256"
        ):
            failures.append("completion baseline payload hash is missing or does not match")

    activities = snapshot.get("activities", {})
    if not isinstance(activities, dict) or len(activities) != expected_corpus_size:
        observed = len(activities) if isinstance(activities, dict) else "non-object"
        failures.append(
            f"activity inventory is {observed}; expected exactly {expected_corpus_size}"
        )

    inputs = snapshot.get("inputs", [])
    third_inputs = [
        row
        for row in inputs
        if isinstance(row, dict)
        and row.get("role") == "bulk_label"
        and row.get("identity") == third_rater
    ] if isinstance(inputs, list) else []
    if len(third_inputs) != 1:
        failures.append(f"third-rater bulk input receipts found: {len(third_inputs)}; expected 1")
    expected_successes = expected_corpus_size - len(nonresponse_ids)
    if len(third_inputs) == 1 and third_inputs[0].get("unique_successful_labels") != expected_successes:
        failures.append(
            "third-rater unique successful labels are "
            f"{third_inputs[0].get('unique_successful_labels')}; expected {expected_successes}"
        )

    if isinstance(activities, dict) and isinstance(third_rater, str):
        successful_readings = sum(
            isinstance(row, dict)
            and isinstance(row.get("readings"), dict)
            and row["readings"].get(third_rater) in MODES
            for row in activities.values()
        )
        if successful_readings != expected_successes:
            failures.append(
                f"activities with a successful third-rater reading: {successful_readings}; "
                f"expected {expected_successes}"
            )
        missing_readings = {
            activity_id
            for activity_id, row in activities.items()
            if not isinstance(row, dict)
            or not isinstance(row.get("readings"), dict)
            or row["readings"].get(third_rater) not in MODES
        }
        if missing_readings != nonresponse_ids:
            failures.append(
                "activities missing a third-rater reading differ from explicit nonresponses"
            )
        for activity_id in nonresponse_ids:
            row = activities.get(activity_id)
            if not isinstance(row, dict) or not (
                row.get("label") is None
                and row.get("label_source") == "third_rater_explicit_nonresponse"
                and row.get("settlement") == "unsettled"
            ):
                failures.append(
                    f"explicit nonresponse activity {activity_id} is not retained as unsettled"
                )
        if baseline is not None and isinstance(baseline.get("activities"), dict):
            baseline_ids = set(baseline["activities"])
            final_ids = set(activities)
            if final_ids != baseline_ids:
                failures.append(
                    "activity inventory differs from baseline: "
                    f"added={len(final_ids - baseline_ids)} removed={len(baseline_ids - final_ids)}"
                )
    return failures


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def atomic_write_json_no_replace(path: Path, value: object) -> str:
    """Atomically publish JSON without replacing a competing frozen target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    with tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.link(temporary, path)
    except FileExistsError as exc:
        try:
            existing = path.read_bytes()
        except FileNotFoundError as vanished:
            raise SnapshotInputError(
                f"competing frozen snapshot appeared and vanished at {path}"
            ) from vanished
        if existing != rendered:
            raise SnapshotInputError(
                f"refusing to replace existing non-identical frozen snapshot: {path}"
            ) from exc
        return "unchanged"
    finally:
        temporary.unlink(missing_ok=True)
    return "written"


def load_snapshot(path: Path) -> dict[str, object]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    verify_snapshot(snapshot)
    return snapshot


def _activity_range(snapshot: dict[str, object]) -> dict[str, object]:
    """A transition diagnostic, not the employment-weighted published estimand."""
    activities = snapshot["activities"]
    denominator = len(activities)
    counts = collections.Counter(row.get("label") or "unsettled" for row in activities.values())
    if not denominator:
        strict = [0.0, 1.0]
        generous = [0.0, 1.0]
    else:
        strict = [
            counts["screen"] / denominator,
            (counts["screen"] + counts["unsettled"]) / denominator,
        ]
        generous = [
            (counts["screen"] + counts["mixed"]) / denominator,
            (counts["screen"] + counts["mixed"] + counts["unsettled"]) / denominator,
        ]
    return {
        "range_kind": (
            "unweighted activity-share partial-identification diagnostic; not the "
            "employment-weighted headline and not a confidence interval"
        ),
        "coverage_ceiling": "none; deterministic extrema over unsettled activity labels",
        "denominator": denominator,
        "strict_screen": strict,
        "generous_screen_or_mixed": generous,
    }


def transition_audit(baseline: dict[str, object], final: dict[str, object]) -> dict[str, object]:
    verify_snapshot(baseline)
    verify_snapshot(final)
    before = baseline["activities"]
    after = final["activities"]
    before_ids, after_ids = set(before), set(after)
    common = sorted(before_ids & after_ids)

    stratum_2x2 = {f"baseline_{left}__final_{right}": 0 for left in STRATA for right in STRATA}
    settlement_2x2 = {
        f"baseline_{left}__final_{right}": 0
        for left in ("settled", "unsettled")
        for right in ("settled", "unsettled")
    }
    stratum_changes: list[dict[str, object]] = []
    label_changes: list[dict[str, object]] = []
    excluded_from_stratum_2x2 = collections.Counter()

    for activity_id in common:
        old, new = before[activity_id], after[activity_id]
        old_stratum, new_stratum = old["stratum"], new["stratum"]
        if old_stratum in STRATA and new_stratum in STRATA:
            stratum_2x2[f"baseline_{old_stratum}__final_{new_stratum}"] += 1
        else:
            excluded_from_stratum_2x2[f"{old_stratum}->{new_stratum}"] += 1
        old_settlement = "settled" if old.get("label") else "unsettled"
        new_settlement = "settled" if new.get("label") else "unsettled"
        settlement_2x2[f"baseline_{old_settlement}__final_{new_settlement}"] += 1
        if old_stratum != new_stratum:
            stratum_changes.append(
                {
                    "activity_id": activity_id,
                    "baseline": old_stratum,
                    "final": new_stratum,
                    "baseline_n_raters": old["n_raters"],
                    "final_n_raters": new["n_raters"],
                }
            )
        if old.get("label") != new.get("label"):
            label_changes.append(
                {
                    "activity_id": activity_id,
                    "baseline": old.get("label"),
                    "final": new.get("label"),
                    "baseline_source": old.get("label_source"),
                    "final_source": new.get("label_source"),
                }
            )

    audit: dict[str, object] = {
        "schema": AUDIT_SCHEMA,
        "baseline_snapshot_payload_sha256": baseline["snapshot_payload_sha256"],
        "final_snapshot_payload_sha256": final["snapshot_payload_sha256"],
        "activity_inventory": {
            "baseline": len(before_ids),
            "final": len(after_ids),
            "common": len(common),
            "added": sorted(after_ids - before_ids),
            "removed": sorted(before_ids - after_ids),
        },
        "stratum_2x2": stratum_2x2,
        "stratum_2x2_excluded": dict(sorted(excluded_from_stratum_2x2.items())),
        "settlement_2x2": settlement_2x2,
        "previously_settled_to_split_awaiting_adjudication": sum(
            1
            for activity_id in common
            if before[activity_id].get("label")
            and after[activity_id].get("label_source") == "split_awaiting_adjudication"
        ),
        "stratum_changes": stratum_changes,
        "label_changes": label_changes,
        "range_under_each": {
            "baseline": _activity_range(baseline),
            "final": _activity_range(final),
        },
        "range_kind": "deterministic snapshot transition audit; not a confidence interval",
        "coverage_ceiling": "none",
    }
    audit["audit_payload_sha256"] = payload_sha256(audit)
    return audit


@click.group()
def cli() -> None:
    """Freeze work-mode inputs or audit a baseline-to-final transition."""


@cli.command("freeze")
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--snapshot-date", required=True, help="Explicit YYYY-MM-DD provenance date.")
@click.option("--third-rater", required=True)
@click.option("--third-rater-status", required=True)
@click.option(
    "--third-rater-nonresponse",
    multiple=True,
    help="Activity ID with no valid label after proved exact-route attempts; narrowly capped.",
)
@click.option(
    "--third-rater-request-model",
    help="Exact provider request model for explicit-nonresponse receipt validation.",
)
@click.option(
    "--baseline-snapshot",
    type=click.Path(path_type=Path, exists=True),
    help="Required hash-valid activity inventory authority when declaring complete.",
)
@click.option(
    "--expected-corpus-size",
    default=EXPECTED_CORPUS_SIZE,
    show_default=True,
    type=click.IntRange(min=1),
    help="Exact activity and completed-third-route denominator.",
)
@click.option(
    "--experiment-rater",
    multiple=True,
    help="Include and hash UNCLEAR_<rater>.jsonl; repeat for more than one.",
)
@click.option("--allow-incomplete-tail", is_flag=True)
def freeze_command(
    output: Path,
    snapshot_date: str,
    third_rater: str,
    third_rater_status: str,
    third_rater_nonresponse: tuple[str, ...],
    third_rater_request_model: str | None,
    baseline_snapshot: Path | None,
    expected_corpus_size: int,
    experiment_rater: tuple[str, ...],
    allow_incomplete_tail: bool,
) -> None:
    label_paths = sorted(WM_DIR.glob("*__r0.jsonl"))
    adjudication_paths = sorted(WM_DIR.glob("ADJ_*.jsonl"))
    experiment_paths = [WM_DIR / f"UNCLEAR_{rater}.jsonl" for rater in experiment_rater]
    missing = [path for path in experiment_paths if not path.exists()]
    if missing:
        raise click.ClickException("missing experiment inputs: " + ", ".join(map(str, missing)))
    if not label_paths:
        raise click.ClickException(f"no bulk-label inputs in {WM_DIR}")
    try:
        snapshot = build_snapshot(
            label_paths,
            adjudication_paths,
            experiment_paths,
            snapshot_date=snapshot_date,
            third_rater=third_rater,
            third_rater_status=third_rater_status,
            third_rater_nonresponses=third_rater_nonresponse,
            third_rater_request_model=third_rater_request_model,
            allow_incomplete_tail=allow_incomplete_tail,
        )
        if snapshot["snapshot_status"]["third_rater_collection_complete"]:
            if baseline_snapshot is None:
                raise SnapshotInputError(
                    "cannot declare third route complete without --baseline-snapshot"
                )
            baseline = load_snapshot(baseline_snapshot)
            snapshot["snapshot_status"]["completion_baseline_payload_sha256"] = baseline[
                "snapshot_payload_sha256"
            ]
            snapshot.pop("snapshot_payload_sha256", None)
            snapshot["snapshot_payload_sha256"] = payload_sha256(snapshot)
            failures = completion_gate_failures(
                snapshot,
                expected_corpus_size=expected_corpus_size,
                baseline=baseline,
            )
            if failures:
                raise SnapshotInputError(
                    "cannot declare third route complete:\n- " + "\n- ".join(failures)
                )
        disposition = atomic_write_json_no_replace(output, snapshot)
    except SnapshotInputError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"{disposition} {output}  activities={len(snapshot['activities'])} "
        f"snapshot={snapshot['snapshot_payload_sha256']}"
    )


@cli.command("audit")
@click.option("--baseline", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--final", "final_path", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--output", type=click.Path(path_type=Path), required=True)
def audit_command(baseline: Path, final_path: Path, output: Path) -> None:
    try:
        audit = transition_audit(load_snapshot(baseline), load_snapshot(final_path))
        atomic_write_json(output, audit)
    except SnapshotInputError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"written {output}  stratum_changes={len(audit['stratum_changes'])} "
        f"label_changes={len(audit['label_changes'])}"
    )


if __name__ == "__main__":
    cli()
