"""Freeze one fail-closed OSWorld 2.0 to AllJobs transfer review.

The selected public trajectory is useful precisely because it exposes a benchmark false
positive: task 010 received 1.0 even though the agent wrote the wrong budget code and the
evaluator did not inspect the table cells that held most required values.  The official task
class and hash manifest are gated and unavailable in the current environment.  This script
records those facts; it never turns the public score or an activity-text similarity into a
transfer witness.

External bytes are read from a temporary acquisition directory and represented in the tracked
artifact only by pinned URL/revision/hash/size receipts.  The trajectory dataset declares no
licence, so its bytes are not redistributed here.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
SCHEMA_VERSION = "alljobs.osworld2-transfer-review.v1"
RELEASE = "osworld-v2-2026.06.24"
CODE_TAG = "v2026.06.24"
CODE_COMMIT = "2b9b7b4eb73243d557bdbf2998fe18d8e18e19c6"
TASK_REPOSITORY_COMMIT = "e7996f4cc850be108e510bd8433c63ee7b8303dd"
TRAJECTORY_COMMIT = "458824aec9f07ffbe504f3b9306d941695387b00"
TASK_ID = "010"
ACTIVITY_ID = "23d778e73061800ae3732b1f34a750c5"
ACTIVITY_TITLE = (
    "Process and prepare documents, such as business or government forms and expense reports."
)
DEFAULT_OUTPUT = (
    ROOT
    / "data"
    / "evidence"
    / "successors"
    / RELEASE
    / f"{TASK_ID}__{ACTIVITY_ID}"
    / "review.json"
)
DEFAULT_CORPUS = ROOT / "data" / "work_mode" / "corpus.jsonl"
DEFAULT_WORK_MODE = ROOT / "data" / "work_mode" / "work_mode_final_2026-08-12.json"
DEFAULT_REGISTRY = ROOT / "data" / "evidence" / "registry.json"
DEFAULT_EXTERNAL_AUDIT = (
    REPO_ROOT / "docs" / "audits" / "2026-08-11-computer-use-evidence-update.md"
)
DEFAULT_WORKBANK = ROOT / "data" / "raw" / "workbank" / "v1" / "task_statement_with_metadata.csv"

_SOURCE_FILES = {
    "release_manifest": "release-manifest.json",
    "code_license": "code-license",
    "code_revision": "code-revision.txt",
    "task_repository_metadata": "task-repository.json",
    "task_tree_metadata": "task-tree.json",
    "task_class_http_status": "task-class-http-status.txt",
    "trajectory_repository_metadata": "trajectory-repository.json",
    "trajectory_analysis": "analysis_task_010.md",
    "trajectory_api_usage": "api_usage.json",
    "trajectory_checkpoints": "checkpoint_results.json",
    "trajectory_eval_log": "eval.log",
    "trajectory_result": "result.json",
    "trajectory_runtime_log": "runtime.log",
}

_SOURCE_LOCATORS = {
    "release_manifest": (
        "https://github.com/xlang-ai/OSWorld-V2/blob/"
        f"{CODE_COMMIT}/benchmark_releases/osworld-v2-2026.06.24.json"
    ),
    "code_license": f"https://github.com/xlang-ai/OSWorld-V2/blob/{CODE_COMMIT}/LICENSE",
    "code_revision": f"https://github.com/xlang-ai/OSWorld-V2/tree/{CODE_COMMIT}",
    "task_repository_metadata": "https://huggingface.co/api/datasets/xlangai/osworld_v2_tasks",
    "task_tree_metadata": (
        "https://huggingface.co/api/datasets/xlangai/osworld_v2_tasks/tree/"
        f"{TASK_REPOSITORY_COMMIT}?recursive=true"
    ),
    "task_class_http_status": (
        f"https://huggingface.co/datasets/xlangai/osworld_v2_tasks/resolve/{CODE_TAG}/task_010.py"
    ),
    "trajectory_repository_metadata": (
        "https://huggingface.co/api/datasets/xlangai/osworld2.0-trajectory"
    ),
}
for _trajectory_role, _trajectory_name in {
    "trajectory_analysis": "analysis_task_010.md",
    "trajectory_api_usage": "api_usage.json",
    "trajectory_checkpoints": "checkpoint_results.json",
    "trajectory_eval_log": "eval.log",
    "trajectory_result": "result.json",
    "trajectory_runtime_log": "runtime.log",
}.items():
    _SOURCE_LOCATORS[_trajectory_role] = (
        "https://huggingface.co/datasets/xlangai/osworld2.0-trajectory/resolve/"
        f"{TRAJECTORY_COMMIT}/website_demo/MiniMax-M3/tasks/{TASK_ID}/{_trajectory_name}"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _payload_hash(artifact: dict) -> str:
    payload = {key: value for key, value in artifact.items() if key != "payload_sha256"}
    return sha256_bytes(_canonical_bytes(payload))


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _receipt(path: Path, *, role: str, authority: str, locator: str | None = None) -> dict:
    data = path.read_bytes()
    receipt = {
        "authority": authority,
        "bytes": len(data),
        "path": _display_path(path) if locator is None else _SOURCE_FILES[role],
        "role": role,
        "sha256": sha256_bytes(data),
    }
    if locator is not None:
        receipt["source_locator"] = locator
    return receipt


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON source {path}: {error}") from error


def _source_paths(source_root: Path) -> dict[str, Path]:
    paths = {role: source_root / name for role, name in _SOURCE_FILES.items()}
    missing = [path.as_posix() for path in paths.values() if not path.is_file()]
    if missing:
        raise ValueError(f"source acquisition is incomplete: {missing}")
    return paths


def _load_activity(corpus: Path) -> dict:
    matches = []
    for line_number, line in enumerate(corpus.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{corpus}:{line_number}: invalid JSON") from error
        if row.get("activity_id") == ACTIVITY_ID:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError(f"expected one exact AllJobs activity {ACTIVITY_ID}, found {len(matches)}")
    row = matches[0]
    if row.get("title") != ACTIVITY_TITLE:
        raise ValueError("selected AllJobs activity title drifted")
    return row


def _load_workbank_row(path: Path) -> dict:
    matches = [
        row
        for row in csv.DictReader(path.open(encoding="utf-8"))
        if row.get("Task") == ACTIVITY_TITLE
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one exact Workbank source row, found {len(matches)}")
    row = matches[0]
    if row.get("Task ID") != "838" or row.get("O*NET-SOC Code") != "43-9061.00":
        raise ValueError("selected Workbank source identity drifted")
    return row


def _validate_external_sources(paths: dict[str, Path]) -> dict:
    manifest = _read_json(paths["release_manifest"])
    if not isinstance(manifest, dict):
        raise TypeError("release manifest must be an object")
    if manifest.get("release") != RELEASE or manifest.get("status") != "active":
        raise ValueError("OSWorld benchmark release identity/status drifted")
    code = manifest.get("osworld_code") or {}
    tasks = manifest.get("tasks") or {}
    task_hash_manifest = manifest.get("task_hash_manifest") or {}
    if code != {"repository": "xlang-ai/OSWorld-V2", "tag": CODE_TAG}:
        raise ValueError("OSWorld code release binding drifted")
    if tasks.get("repository") != "xlangai/osworld_v2_tasks" or tasks.get("tag") != CODE_TAG:
        raise ValueError("OSWorld task release binding drifted")
    if task_hash_manifest.get("task_count") != 108:
        raise ValueError("OSWorld task-count authority drifted")
    manifest_sha = str(task_hash_manifest.get("sha256", ""))
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_sha):
        raise ValueError("task hash manifest digest is missing or malformed")
    if b"Apache License" not in paths["code_license"].read_bytes():
        raise ValueError("OSWorld code licence is not the expected Apache licence")
    if paths["code_revision"].read_text(encoding="utf-8").strip() != CODE_COMMIT:
        raise ValueError("OSWorld code commit drifted from the release tag")

    task_repo = _read_json(paths["task_repository_metadata"])
    task_tree = _read_json(paths["task_tree_metadata"])
    if not isinstance(task_repo, dict) or not isinstance(task_tree, list):
        raise TypeError("task repository metadata is malformed")
    if task_repo.get("gated") != "auto" or "license:apache-2.0" not in task_repo.get("tags", []):
        raise ValueError("task repository gated/licence metadata drifted")
    if task_repo.get("sha") != TASK_REPOSITORY_COMMIT:
        raise ValueError("task repository commit drifted")
    if not any(row.get("path") == "task_010.py" for row in task_tree if isinstance(row, dict)):
        raise ValueError("task_010.py is absent from the pinned task tree metadata")
    task_tree_row = next(row for row in task_tree if row.get("path") == "task_010.py")
    if task_tree_row.get("oid") != "7435437f07e25192e7e12e13717e1b34b5f71ec4":
        raise ValueError("task_010.py Git object identity drifted")
    if task_tree_row.get("size") != 6633:
        raise ValueError("task_010.py listed size drifted")
    task_status_receipt = paths["task_class_http_status"].read_text(encoding="utf-8").strip()
    status_match = re.search(r"(?:HTTP/\S+\s+)?(?P<status>\d{3})", task_status_receipt)
    if status_match is None:
        raise ValueError("task-class HTTP receipt has no status code")
    task_status = status_match.group("status")
    if task_status == "200":
        raise ValueError(
            "task class became available; ingest and validate its bytes under a successor contract"
        )
    if task_status != "401":
        raise ValueError(f"expected a fail-closed gated task response, received HTTP {task_status}")

    trajectory_repo = _read_json(paths["trajectory_repository_metadata"])
    if not isinstance(trajectory_repo, dict) or trajectory_repo.get("gated") is not False:
        raise ValueError("trajectory repository metadata is malformed or unexpectedly gated")
    result = _read_json(paths["trajectory_result"])
    checkpoints = _read_json(paths["trajectory_checkpoints"])
    if not isinstance(result, dict) or result.get("score") != 1.0:
        raise ValueError("expected the pinned public result score 1.0")
    if not isinstance(checkpoints, list) or not any(
        row.get("step") == 150 and row.get("score") == 0.0 for row in checkpoints
    ):
        raise ValueError("pinned task-010 checkpoint result drifted")
    analysis = paths["trajectory_analysis"].read_text(encoding="utf-8")
    required_analysis = (
        "Task ID: 010",
        "Final score: 1.0",
        "evaluator is materially too lenient",
        "score masks a real content error",
        "does not check table cells",
    )
    missing = [text for text in required_analysis if text.casefold() not in analysis.casefold()]
    if missing:
        raise ValueError(
            f"public task-010 analysis lost required false-positive evidence: {missing}"
        )

    return {
        "code_commit": CODE_COMMIT,
        "code_tag": CODE_TAG,
        "manifest_task_count": 108,
        "provider_ami": (
            manifest.get("provider_images", {})
            .get("aws", {})
            .get("ubuntu", {})
            .get("us-east-1", {})
            .get("1920x1080", {})
            .get("ami_id")
        ),
        "reported_final_score": result["score"],
        "reported_step_150_score": 0.0,
        "task_class_git_oid": task_tree_row.get("oid"),
        "task_class_listed_bytes": task_tree_row.get("size"),
        "task_class_resolve_http_status": int(task_status),
        "task_hash_manifest_expected_sha256": manifest_sha.removeprefix("sha256:"),
        "task_repository_commit": task_repo.get("sha") or TASK_REPOSITORY_COMMIT,
        "trajectory_observed_repository_commit": trajectory_repo.get("sha"),
        "trajectory_selected_file_commit": TRAJECTORY_COMMIT,
    }


def build_artifact(
    *,
    source_root: Path,
    base_commit: str,
    corpus: Path,
    work_mode: Path,
    registry: Path,
    external_audit: Path,
    workbank: Path,
) -> dict:
    """Build the only verdict current authority supports; no caller supplies the decision."""

    if not re.fullmatch(r"[0-9a-f]{40}", base_commit):
        raise ValueError("base_commit must be a lowercase 40-hex Git commit")
    paths = _source_paths(source_root)
    source_facts = _validate_external_sources(paths)
    activity = _load_activity(corpus)
    workbank_row = _load_workbank_row(workbank)
    work_mode_data = _read_json(work_mode)
    activity_state = (
        work_mode_data.get("activities", {}).get(ACTIVITY_ID)
        if isinstance(work_mode_data, dict)
        else None
    )
    if not isinstance(activity_state, dict):
        raise TypeError("selected activity is absent from the frozen work-mode snapshot")
    registry_data = _read_json(registry)
    if (
        not isinstance(registry_data, dict)
        or registry_data.get("schema_version") != "evidence/1"
        or registry_data.get("edges_authorising_a_bound") != 0
    ):
        raise ValueError("base evidence registry is not the frozen zero-bound authority")

    source_receipts = [
        _receipt(
            paths[role],
            role=role,
            authority=(
                "official_release"
                if role
                in {
                    "release_manifest",
                    "code_license",
                    "code_revision",
                    "task_repository_metadata",
                    "task_tree_metadata",
                }
                else "public_trajectory_or_access_receipt"
            ),
            locator=_SOURCE_LOCATORS[role],
        )
        for role in sorted(paths)
    ]
    base_receipts = [
        _receipt(corpus, role="alljobs_activity_corpus", authority="current_local_source"),
        _receipt(
            work_mode,
            role="work_mode_model_judgments",
            authority="frozen_model_judgment_not_task_requirement",
        ),
        _receipt(registry, role="frozen_evidence_registry", authority="current_study_authority"),
        _receipt(external_audit, role="external_evidence_audit", authority="current_dated_audit"),
        _receipt(workbank, role="workbank_onet_source_row", authority="historical_local_extract"),
    ]
    failed = [
        "gated_task_class_bytes_missing",
        "task_hash_manifest_bytes_missing",
        "pinned_task_assets_missing",
        "trajectory_redistribution_licence_not_declared",
        "exact_task_success_criterion_unavailable",
        "reported_pass_is_known_evaluator_false_positive",
        "independent_task_channel_authority_missing",
        "mandatory_component_authority_missing",
        "task_permission_and_failure_semantics_authority_missing",
    ]
    artifact = {
        "base": {
            "external_audit_sha256": sha256_path(external_audit),
            "frozen_registry_sha256": sha256_path(registry),
            "repository_commit_before_successor": base_commit,
            "receipts": base_receipts,
        },
        "candidate_alljobs_activity": {
            "activity_id": ACTIVITY_ID,
            "activity_row_sha256": sha256_bytes(_canonical_bytes(activity)),
            "activity_title": activity["title"],
            "importance": activity.get("importance"),
            "mandatory_component_analysis": {
                "authoritative_components": [],
                "exact_statement_spans": [
                    {
                        "interpretation": "broad compound action, not a complete component decomposition",
                        "span": "Process and prepare documents",
                    },
                    {
                        "interpretation": "illustrative examples introduced by 'such as', not mandatory exhaustive objects",
                        "span": "business or government forms and expense reports",
                    },
                ],
                "status": "missing_independent_component_authority",
            },
            "occupation_title": activity.get("occupation_title"),
            "source_identity": {
                "onet_soc_code": workbank_row["O*NET-SOC Code"],
                "task_id": workbank_row["Task ID"],
            },
            "task_channel": {
                "independent_requirement": "unknown",
                "model_judgment": activity_state.get("label"),
                "model_judgment_authorises_gate": False,
            },
        },
        "claim_ceiling": {
            "allowed": (
                "one exact public OSWorld trajectory and one AllJobs activity were reviewed; "
                "current authority cannot admit a directed transfer witness"
            ),
            "not_a_finding_of_inability": True,
            "prohibited": [
                "OSWorld task 010 bounds the AllJobs activity",
                "the reported 1.0 proves faithful task completion",
                "the review estimates a workforce share or production reliability",
                "absence of a witness is evidence that an agent cannot do the work",
            ],
        },
        "decision": "HOLD_SOURCE_OR_AUTHORITY_GAP",
        "gates": {
            "all_passed": False,
            "failed": failed,
            "passed": [
                "exact_code_release_manifest_and_tag_bound",
                "task_010_listed_in_pinned_task_repository_metadata",
                "public_trajectory_files_hash_bound",
                "reported_score_and_checkpoint_reproduced_from_public_records",
                "alljobs_activity_and_onet_source_identity_bound",
                "frozen_registry_still_authorises_zero_bounds",
            ],
        },
        "item_outcome_receipt": None,
        "reported_benchmark_outcome": {
            "admission_status": "not_admitted_evaluator_false_positive_and_task_authority_missing",
            "evidence_tier": "BENCHMARK",
            "known_misalignment": (
                "the public analysis reports a wrong required budget code and a full score because "
                "the evaluator did not inspect table cells"
            ),
            "model": "MiniMax-M3",
            "score": source_facts["reported_final_score"],
            "step": 248,
        },
        "schema_version": SCHEMA_VERSION,
        "source_pack": {
            "acquisition": {
                "code": f"git clone --depth 1 --branch {CODE_TAG} https://github.com/xlang-ai/OSWorld-V2.git",
                "task_class": (
                    "accept the gated xlangai/osworld_v2_tasks terms, authenticate with hf, then "
                    f"download task_010.py at {CODE_TAG}"
                ),
                "trajectory_base_url": (
                    "https://huggingface.co/datasets/xlangai/osworld2.0-trajectory/resolve/"
                    f"{TRAJECTORY_COMMIT}/website_demo/MiniMax-M3/tasks/{TASK_ID}"
                ),
            },
            "licence_disposition": {
                "code_and_task_metadata": "apache-2.0",
                "trajectory": "not_declared_receipts_only_no_redistributed_bytes",
            },
            "release": RELEASE,
            "selection_rule": (
                "task 010 selected before AllJobs retrieval because it has a public complete demo "
                "trajectory and a binary final result"
            ),
            "source_facts": source_facts,
            "source_receipts": source_receipts,
            "status": "PARTIAL_SOURCE_PACK_GATED_TASK_CLASS",
            "workflow_id": TASK_ID,
        },
        "transfer_edge": {
            "component_id": None,
            "differences": [
                "OSWorld is a specific reimbursement-checklist instance; the AllJobs statement is broad and illustrative",
                "OSWorld uses Thunderbird, Writer, spreadsheets, PDF tooling and a named AWS image",
                "the reported evaluator omits decisive table-cell fields and accepted a wrong budget code",
            ],
            "provenance": "codex successor review 2026-08-12; source receipts embedded",
            "rationale": (
                "lexical and operational similarity is sufficient for a candidate review only; "
                "missing task bytes, independent task requirements and evaluator adequacy block admission"
            ),
            "result_id": "r_osworld_v2_minimax_m3_task_010_public_demo",
            "scope": "contextual",
            "similarities": [
                "both concern preparing a document/form from supplied information",
                "the OSWorld workflow includes an expense/reimbursement document",
            ],
            "status": "unresolved",
            "task_id": ACTIVITY_ID,
            "unknowns": [
                "exact gated task-class bytes and full success criterion",
                "pinned asset bytes",
                "independent AllJobs channel, permissions, failure semantics and mandatory components",
            ],
        },
        "workflow": {
            "environment": {
                "apps": ["Thunderbird", "Writer", "spreadsheet", "PDF tooling"],
                "provider_ami": source_facts["provider_ami"],
                "step_limit_contour": "public demo finished at step 248; paper primary contour is 500 steps",
            },
            "id": TASK_ID,
            "summary": (
                "read a reimbursement email and local office files, complete a checklist document, "
                "and save it under the required desktop filename"
            ),
        },
    }
    artifact["payload_sha256"] = _payload_hash(artifact)
    validate_artifact(artifact)
    return artifact


def validate_artifact(artifact: dict) -> None:
    if artifact.get("payload_sha256") != _payload_hash(artifact):
        raise ValueError("review payload hash mismatch")
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("review schema version mismatch")
    if artifact.get("decision") != "HOLD_SOURCE_OR_AUTHORITY_GAP":
        raise ValueError("this contract cannot emit an eligible or negative capability decision")
    if artifact.get("item_outcome_receipt") is not None:
        raise ValueError("a blocked review cannot contain an item-outcome receipt")
    edge = artifact.get("transfer_edge") or {}
    if edge.get("scope") != "contextual" or edge.get("status") != "unresolved":
        raise ValueError("blocked review must retain a contextual unresolved edge")
    gates = artifact.get("gates") or {}
    required_failures = {
        "gated_task_class_bytes_missing",
        "reported_pass_is_known_evaluator_false_positive",
        "independent_task_channel_authority_missing",
        "mandatory_component_authority_missing",
    }
    if gates.get("all_passed") is not False or not required_failures.issubset(
        gates.get("failed", [])
    ):
        raise ValueError("required fail-closed gates are missing")
    ceiling = artifact.get("claim_ceiling") or {}
    if ceiling.get("not_a_finding_of_inability") is not True:
        raise ValueError("absence of a witness was converted into a finding of inability")
    if (artifact.get("source_pack") or {}).get("status") != "PARTIAL_SOURCE_PACK_GATED_TASK_CLASS":
        raise ValueError("source-pack authority ceiling drifted")


def freeze_artifact(*, output: Path, artifact: dict) -> str:
    validate_artifact(artifact)
    data = _canonical_bytes(artifact)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() == data:
            return "unchanged"
        raise FileExistsError(f"refusing to replace non-identical frozen artifact: {output}")
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
            raise FileExistsError(f"refusing to replace competing frozen artifact: {output}")
        return "written"
    finally:
        temporary.unlink(missing_ok=True)


def check_artifact(
    *,
    output: Path,
    corpus: Path,
    work_mode: Path,
    registry: Path,
    external_audit: Path,
    workbank: Path,
) -> None:
    artifact = _read_json(output)
    if not isinstance(artifact, dict):
        raise TypeError("review artifact must be an object")
    validate_artifact(artifact)
    actual = {
        "alljobs_activity_corpus": sha256_path(corpus),
        "work_mode_model_judgments": sha256_path(work_mode),
        "frozen_evidence_registry": sha256_path(registry),
        "external_evidence_audit": sha256_path(external_audit),
        "workbank_onet_source_row": sha256_path(workbank),
    }
    expected = {row["role"]: row["sha256"] for row in artifact["base"]["receipts"]}
    if actual != expected:
        raise ValueError(f"review base input drift: expected {expected}, actual {actual}")
    _load_activity(corpus)
    _load_workbank_row(workbank)


@click.group()
def cli() -> None:
    """Freeze or check the single OSWorld transfer successor artifact."""


def _base_options(function):
    options = [
        click.option("--corpus", type=click.Path(path_type=Path), default=DEFAULT_CORPUS),
        click.option("--work-mode", type=click.Path(path_type=Path), default=DEFAULT_WORK_MODE),
        click.option("--registry", type=click.Path(path_type=Path), default=DEFAULT_REGISTRY),
        click.option(
            "--external-audit", type=click.Path(path_type=Path), default=DEFAULT_EXTERNAL_AUDIT
        ),
        click.option("--workbank", type=click.Path(path_type=Path), default=DEFAULT_WORKBANK),
    ]
    for option in reversed(options):
        function = option(function)
    return function


@cli.command("freeze")
@click.option("--source-root", required=True, type=click.Path(path_type=Path))
@click.option("--base-commit", required=True)
@click.option("--output", type=click.Path(path_type=Path), default=DEFAULT_OUTPUT)
@_base_options
def freeze_command(source_root: Path, base_commit: str, output: Path, **paths) -> None:
    artifact = build_artifact(source_root=source_root, base_commit=base_commit, **paths)
    result = freeze_artifact(output=output, artifact=artifact)
    click.echo(
        f"{result}: {output} decision={artifact['decision']} payload={artifact['payload_sha256']}"
    )


@cli.command("check")
@click.option("--output", type=click.Path(path_type=Path), default=DEFAULT_OUTPUT)
@_base_options
def check_command(output: Path, **paths) -> None:
    check_artifact(output=output, **paths)
    artifact = _read_json(output)
    click.echo(
        f"PASS: {output} decision={artifact['decision']} payload={artifact['payload_sha256']}"
    )


if __name__ == "__main__":
    cli()
