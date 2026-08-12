"""Fail-closed successor review for one exact OSWorld 2.0 workflow."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build_osworld_transfer_successor.py"
_spec = importlib.util.spec_from_file_location("build_osworld_transfer_successor", SCRIPT)
successor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(successor)


def _write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _source_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    _write(
        source / "release-manifest.json",
        json.dumps(
            {
                "schema_version": 1,
                "release": "osworld-v2-2026.06.24",
                "status": "active",
                "osworld_code": {"repository": "xlang-ai/OSWorld-V2", "tag": "v2026.06.24"},
                "tasks": {
                    "repository": "xlangai/osworld_v2_tasks",
                    "repo_type": "dataset",
                    "tag": "v2026.06.24",
                },
                "task_hash_manifest": {
                    "repository": "xlangai/osworld_v2_tasks",
                    "repo_type": "dataset",
                    "tag": "v2026.06.24",
                    "path": "manifests/task_hashes.json",
                    "sha256": "sha256:" + "a" * 64,
                    "task_count": 108,
                },
                "provider_images": {
                    "aws": {"ubuntu": {"us-east-1": {"1920x1080": {"ami_id": "ami-test"}}}}
                },
            },
            sort_keys=True,
        ).encode(),
    )
    _write(source / "code-license", b"Apache License\nVersion 2.0\n")
    _write(source / "code-revision.txt", (successor.CODE_COMMIT + "\n").encode())
    _write(
        source / "task-repository.json",
        json.dumps(
            {
                "sha": successor.TASK_REPOSITORY_COMMIT,
                "gated": "auto",
                "tags": ["license:apache-2.0"],
                "siblings": [{"rfilename": "task_010.py"}],
            }
        ).encode(),
    )
    _write(
        source / "task-tree.json",
        json.dumps(
            [
                {
                    "path": "task_010.py",
                    "size": 6633,
                    "oid": "7435437f07e25192e7e12e13717e1b34b5f71ec4",
                },
                {"path": "manifests/task_hashes.json", "size": 14505, "oid": "d" * 40},
            ]
        ).encode(),
    )
    _write(source / "task-class-http-status.txt", b"401\n")
    _write(
        source / "trajectory-repository.json",
        json.dumps({"sha": "e" * 40, "gated": False, "tags": []}).encode(),
    )
    _write(
        source / "analysis_task_010.md",
        (
            b"# Task Overview\n\n- Task ID: 010\n- Final score: 1.0\n"
            b"- Checkpoint score: step 150 scored 0.0; final step 248 scored 1.0.\n\n"
            b"# What Went Wrong\n\n- The agent missed a critical value in the email.\n\n"
            b"# Evaluation analysis\n\nThe evaluator is materially too lenient.\n"
            b"The final task score masks a real content error because the evaluator does not "
            b"check table cells.\n"
        ),
    )
    _write(source / "api_usage.json", b"{}\n")
    _write(
        source / "checkpoint_results.json",
        b'[{"step":150,"status":"success","score":0.0}]\n',
    )
    _write(source / "eval.log", b"AMI: ami-test\n")
    _write(source / "result.json", b'{"score":1.0,"safety":{"total_penalty":0.0}}\n')
    _write(source / "runtime.log", b"MiniMax-M3 task 010 step 248 DONE\n")
    return source


def _base_fixture(tmp_path: Path) -> dict[str, Path]:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        json.dumps(
            {
                "activity_id": successor.ACTIVITY_ID,
                "title": successor.ACTIVITY_TITLE,
                "occupation_title": "Office Clerks, General",
                "importance": 3.82,
            }
        )
        + "\n"
    )
    work_mode = tmp_path / "work-mode.json"
    work_mode.write_text(
        json.dumps(
            {
                "activities": {
                    successor.ACTIVITY_ID: {
                        "label": "screen",
                        "readings": {"r1": "screen", "r2": "screen", "r3": "screen"},
                    }
                }
            }
        )
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps({"schema_version": "evidence/1", "edges_authorising_a_bound": 0})
    )
    audit = tmp_path / "audit.md"
    audit.write_text("# audit\n")
    raw = tmp_path / "workbank.csv"
    raw.write_text(
        "O*NET-SOC Code,Occupation (O*NET-SOC Title),Task ID,Task\n"
        f'43-9061.00,"Office Clerks, General",838,"{successor.ACTIVITY_TITLE}"\n'
    )
    return {
        "corpus": corpus,
        "work_mode": work_mode,
        "registry": registry,
        "external_audit": audit,
        "workbank": raw,
    }


def test_review_stays_hold_and_never_mints_a_receipt_from_a_false_positive(tmp_path: Path) -> None:
    artifact = successor.build_artifact(
        source_root=_source_fixture(tmp_path),
        base_commit="8" * 40,
        **_base_fixture(tmp_path),
    )

    assert artifact["decision"] == "HOLD_SOURCE_OR_AUTHORITY_GAP"
    assert artifact["item_outcome_receipt"] is None
    assert artifact["transfer_edge"]["scope"] == "contextual"
    assert artifact["transfer_edge"]["status"] == "unresolved"
    assert artifact["reported_benchmark_outcome"]["score"] == 1.0
    assert artifact["reported_benchmark_outcome"]["admission_status"] == (
        "not_admitted_evaluator_false_positive_and_task_authority_missing"
    )
    assert artifact["claim_ceiling"]["not_a_finding_of_inability"] is True
    assert artifact["gates"]["all_passed"] is False
    assert "gated_task_class_bytes_missing" in artifact["gates"]["failed"]
    assert "independent_task_channel_authority_missing" in artifact["gates"]["failed"]
    assert "mandatory_component_authority_missing" in artifact["gates"]["failed"]
    successor.validate_artifact(artifact)


def test_task_class_access_or_a_different_reported_outcome_requires_a_new_contract(
    tmp_path: Path,
) -> None:
    source = _source_fixture(tmp_path)
    (source / "task-class-http-status.txt").write_text("200\n")
    with pytest.raises(ValueError, match="task class became available"):
        successor.build_artifact(
            source_root=source, base_commit="8" * 40, **_base_fixture(tmp_path)
        )

    source = _source_fixture(tmp_path / "second")
    (source / "result.json").write_text('{"score":0.0}\n')
    with pytest.raises(ValueError, match="expected the pinned public result score 1.0"):
        successor.build_artifact(
            source_root=source, base_commit="8" * 40, **_base_fixture(tmp_path / "second")
        )


def test_payload_hash_detects_review_mutation(tmp_path: Path) -> None:
    artifact = successor.build_artifact(
        source_root=_source_fixture(tmp_path),
        base_commit="8" * 40,
        **_base_fixture(tmp_path),
    )
    artifact["decision"] = "ELIGIBLE_LOWER_FRONTIER_WITNESS"
    with pytest.raises(ValueError, match="payload hash"):
        successor.validate_artifact(artifact)


def test_freeze_is_no_replace_and_check_is_byte_exact(tmp_path: Path) -> None:
    source = _source_fixture(tmp_path)
    paths = _base_fixture(tmp_path)
    output = tmp_path / "review.json"
    successor.freeze_artifact(
        output=output,
        artifact=successor.build_artifact(source_root=source, base_commit="8" * 40, **paths),
    )
    first = output.read_bytes()
    successor.check_artifact(output=output, **paths)
    with pytest.raises(FileExistsError):
        successor.freeze_artifact(
            output=output,
            artifact=successor.build_artifact(source_root=source, base_commit="9" * 40, **paths),
        )
    assert output.read_bytes() == first


def test_frozen_current_study_inputs_have_not_drifted() -> None:
    assert successor.sha256_path(ROOT / "data" / "evidence" / "registry.json") == (
        "0acb9ccdc1d4021a696308c63def790b5ffd60d0d5bff010efa13ecff77eac97"
    )
    assert (
        successor.sha256_path(
            ROOT.parent / "docs" / "reports" / "2026-08-12-research-completion.md"
        )
        == "a8164cbde2d866d5cdef98f44f8b9b0de06f109c02e4be5158625fb9de278886"
    )
