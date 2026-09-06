"""Build the fail-closed, allowlisted AllJobs public research release.

The private repository keeps the full laboratory history. This builder emits only the reader
surface authorised by docs/contracts/public-release-v1.md. It copies evidence bytes without
rewriting them, generates one deterministic manifest, rejects an existing output directory and
fails on undisclosed files, local home paths, secret-like material or symlinks.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

import click

SOURCE_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "alljobs.public-release/v1"
PUBLIC_REPOSITORY = "https://github.com/dilp79/alljobs-agent-work-research"

MAPPED_FILES = {
    "docs/public/README.md": "README.md",
    "docs/public/PUBLIC_RELEASE.md": "PUBLIC_RELEASE.md",
    "docs/public/public.gitignore": ".gitignore",
    "docs/public/workforce_graph_evidence_init.py": (
        "workforce-graph/src/workforce_graph/evidence/__init__.py"
    ),
}

FIXED_FILES = (
    "LICENSE",
    "THIRD_PARTY_DATA.md",
    "docs/audits/2026-08-11-computer-use-evidence-update.md",
    "docs/audits/2026-08-11-historical-authority-recovery.md",
    "docs/contracts/item-outcome-transfer-witness-v1.md",
    "docs/contracts/osworld-transfer-review-v1.md",
    "docs/contracts/predictive-validity-successor-v1.md",
    "docs/contracts/predictive-validity-successor-v2.md",
    "docs/contracts/predictive-validity-successor-v3.md",
    "docs/contracts/public-release-v1.md",
    "docs/contracts/research-completion-report-v1.md",
    "docs/reports/2026-08-12-business-outcome-RU.md",
    "docs/reports/2026-08-12-predictive-validity-successor.md",
    "docs/reports/2026-08-12-research-completion.md",
    "docs/reports/research-note_06--092026_19-13.md",
    "docs/reports/ate-appendix_06--092026_19-32.md",
    "workforce-graph/.python-version",
    "workforce-graph/pyproject.toml",
    "workforce-graph/uv.lock",
    "workforce-graph/data/benchmark_relevance/layer_two_freeze.json",
    "workforce-graph/data/evidence/registry.json",
    (
        "workforce-graph/data/evidence/successors/osworld-v2-2026.06.24/"
        "010__23d778e73061800ae3732b1f34a750c5/review.json"
    ),
    "workforce-graph/data/ru/employment_by_okz2.csv",
    "workforce-graph/data/ru/employment_by_okz2.meta.json",
    "workforce-graph/data/ru/onet_to_okz2.csv",
    "workforce-graph/data/ru/onet_to_okz2.meta.json",
    (
        "workforce-graph/data/work_mode/"
        "work_mode_baseline_2026-08-11_incomplete-third-rater.json"
    ),
    (
        "workforce-graph/data/work_mode/"
        "corrected_result_full_glm_2026-08-11_incomplete-third-rater.json"
    ),
    "workforce-graph/data/work_mode/work_mode_final_2026-08-12.json",
    (
        "workforce-graph/data/work_mode/"
        "corrected_result_full_glm_2026-08-12_final-collection.json"
    ),
    "workforce-graph/research/authorities/content_27_hh.2026-04-12.logical-slice.v1.json",
    "workforce-graph/research/authorities/rli-15row-canonical.json",
    "workforce-graph/scripts/analyze_predictive_validity_successor.py",
    "workforce-graph/scripts/build_osworld_transfer_successor.py",
    "workforce-graph/scripts/build_predictive_validity_successor.py",
    "workforce-graph/scripts/build_public_release.py",
    "workforce-graph/scripts/build_research_completion_report.py",
    "workforce-graph/scripts/classify_work_mode.py",
    "workforce-graph/scripts/correct_for_uncertainty.py",
    "workforce-graph/scripts/freeze_layer_two.py",
    "workforce-graph/scripts/freeze_work_mode_snapshot.py",
    "workforce-graph/scripts/run_missions.py",
    "workforce-graph/scripts/run_predictive_validity_successor.py",
    "workforce-graph/scripts/reproduce_research_note.py",
    "workforce-graph/scripts/reproduce_ate_audit.py",
    "workforce-graph/scripts/semantic_match.py",
    "workforce-graph/scripts/verify_public_release.py",
    "workforce-graph/scripts/weight_work_mode_by_employment.py",
    "workforce-graph/src/workforce_graph/__init__.py",
    "workforce-graph/src/workforce_graph/config.py",
    "workforce-graph/src/workforce_graph/evidence/task4_phase2b_operators.py",
    "workforce-graph/src/workforce_graph/evidence/task4_phase2b_profiles.py",
    "workforce-graph/tests/__init__.py",
    "workforce-graph/tests/test_analyze_predictive_validity_successor.py",
    "workforce-graph/tests/test_freeze_layer_two.py",
    "workforce-graph/tests/test_osworld_transfer_successor.py",
    "workforce-graph/tests/test_predictive_validity_successor.py",
    "workforce-graph/tests/test_research_completion_report.py",
    "workforce-graph/tests/test_run_missions.py",
    "workforce-graph/tests/test_run_predictive_validity_successor.py",
    "workforce-graph/tests/test_semantic_match.py",
    "workforce-graph/tests/test_reproduce_research_note.py",
    "workforce-graph/tests/test_reproduce_ate_audit.py",
    "workforce-graph/data/ate_audit/descriptive.json",
    "workforce-graph/data/ate_audit/private_join.json",
    "workforce-graph/data/publication_2026_09_06/replay_inputs.json",
    "workforce-graph/data/publication_2026_09_06/reproduced/results.json",
    "workforce-graph/data/publication_2026_09_06/reproduced/definition_sensitivity.csv",
    "workforce-graph/data/publication_2026_09_06/reproduced/scaffold_checkers.csv",
    "workforce-graph/data/publication_2026_09_06/reproduced/v3_categories.csv",
    "workforce-graph/data/publication_2026_09_06/reproduced/v3_missions.csv",
    "workforce-graph/data/publication_2026_09_06/reproduced/figure_1_definition_sensitivity.svg",
    "workforce-graph/data/publication_2026_09_06/reproduced/figure_1_definition_sensitivity.png",
    "workforce-graph/data/publication_2026_09_06/reproduced/figure_2_scaffold_checkers.svg",
    "workforce-graph/data/publication_2026_09_06/reproduced/figure_2_scaffold_checkers.png",
    "workforce-graph/data/publication_2026_09_06/reproduced/figure_3_v3_prediction.svg",
    "workforce-graph/data/publication_2026_09_06/reproduced/figure_3_v3_prediction.png",
)

DIRECTORIES = (
    "workforce-graph/benchmark/support_backoffice/v1",
    "workforce-graph/data/predictive_validity/successor_2026-08-12",
    "workforce-graph/data/predictive_validity/successor_2026-08-12-v2",
    "workforce-graph/data/predictive_validity/successor_2026-08-12-v3",
)

FORBIDDEN_PATH_PREFIXES = (
    "docs/archive/",
    "docs/decisions/",
    "docs/plans/",
    "docs/questions/",
    "workforce-graph/data/raw/",
    "workforce-graph/data/trials/",
    "workforce-graph/data/scoring/",
    "workforce-graph/site/",
)
FORBIDDEN_EXACT_PATHS = {
    "HANDOFF.md",
    "PUBLICATION-READINESS.md",
    "prd.md",
    "readme.md",
    "workforce-graph/site/data.json",
}
SECRET_PATTERNS = (
    re.compile(rb"sk-or-v1-[A-Za-z0-9_-]+"),
    re.compile(rb"AIza[A-Za-z0-9_-]{20,}"),
    re.compile(rb"Bearer [A-Za-z0-9_-]{20,}"),
)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
PRIVATE_HOME_PREFIX = b"/home/" + b"dilp79/"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe release path: {value}")
    return path


def _validate_content(path: str, data: bytes) -> None:
    relative = _safe_relative(path).as_posix()
    if relative in FORBIDDEN_EXACT_PATHS or any(
        relative.startswith(prefix) for prefix in FORBIDDEN_PATH_PREFIXES
    ):
        raise ValueError(f"forbidden public path: {relative}")
    if PRIVATE_HOME_PREFIX in data:
        raise ValueError(f"absolute home path in public file: {relative}")
    for pattern in SECRET_PATTERNS:
        if pattern.search(data):
            raise ValueError(f"secret-like material in public file: {relative}")


def release_sources(root: Path = SOURCE_ROOT) -> dict[str, Path]:
    selected: dict[str, Path] = {}

    def add(source_relative: str, public_relative: str | None = None) -> None:
        source = root / source_relative
        destination = public_relative or source_relative
        if source.is_symlink():
            raise ValueError(f"symlink is forbidden: {source_relative}")
        if not source.is_file():
            raise FileNotFoundError(source)
        if destination in selected:
            raise ValueError(f"duplicate public path: {destination}")
        _safe_relative(destination)
        selected[destination] = source

    for source_relative, public_relative in MAPPED_FILES.items():
        add(source_relative, public_relative)
    for relative in FIXED_FILES:
        add(relative)
    for directory_relative in DIRECTORIES:
        directory = root / directory_relative
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        for source in sorted(path for path in directory.rglob("*") if path.is_file()):
            if source.is_symlink():
                raise ValueError(f"symlink is forbidden: {source.relative_to(root)}")
            add(source.relative_to(root).as_posix())
    return dict(sorted(selected.items()))


def _manifest(source_commit: str, files: list[dict[str, object]]) -> dict[str, object]:
    payload = {
        "schema_version": SCHEMA,
        "source_commit": source_commit,
        "public_repository": PUBLIC_REPOSITORY,
        "licence": "Apache-2.0 for original code and documentation only",
        "file_count": len(files),
        "files": files,
        "claim_ceiling": (
            "clean research release; evidence tiers and historical report qualifiers unchanged; "
            "no production, customer-ROI, workforce-share or job-automation claim"
        ),
    }
    payload["release_payload_sha256"] = _sha256(_canonical_bytes(payload))
    return payload


def build_release(output: Path, source_commit: str, root: Path = SOURCE_ROOT) -> dict[str, object]:
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise ValueError("source commit must be a 40-character lowercase SHA-1")
    if output.exists():
        raise FileExistsError(f"refusing existing output: {output}")
    if root.resolve() == output.resolve() or root.resolve() in output.resolve().parents:
        raise ValueError("output must be outside the private source tree")

    sources = release_sources(root)
    output.mkdir(parents=True)
    receipts: list[dict[str, object]] = []
    for public_relative, source in sources.items():
        data = source.read_bytes()
        _validate_content(public_relative, data)
        destination = output / public_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(data)
        receipts.append(
            {"path": public_relative, "bytes": len(data), "sha256": _sha256(data)}
        )

    manifest = _manifest(source_commit, receipts)
    manifest_bytes = _canonical_bytes(manifest)
    _validate_content("release-manifest.json", manifest_bytes)
    with (output / "release-manifest.json").open("xb") as handle:
        handle.write(manifest_bytes)
    return manifest


def verify_tree(root: Path) -> dict[str, object]:
    manifest_path = root / "release-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("release-manifest.json is missing or invalid")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA:
        raise ValueError("unexpected public release schema")
    recorded_payload = manifest.get("release_payload_sha256")
    unhashed = dict(manifest)
    unhashed.pop("release_payload_sha256", None)
    if recorded_payload != _sha256(_canonical_bytes(unhashed)):
        raise ValueError("public release payload hash mismatch")

    recorded = {item["path"]: item for item in manifest.get("files", [])}
    actual: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        if any(
            part in {".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"}
            for part in relative_path.parts
        ):
            continue
        if path.is_symlink():
            raise ValueError(f"symlink is forbidden: {relative_path}")
        if path.is_file() and path != manifest_path:
            relative = relative_path.as_posix()
            if relative.endswith(".pyc"):
                continue
            actual[relative] = path
    if set(recorded) != set(actual):
        missing = sorted(set(recorded) - set(actual))
        added = sorted(set(actual) - set(recorded))
        raise ValueError(f"public tree inventory drift; missing={missing}; added={added}")

    for relative, path in actual.items():
        data = path.read_bytes()
        _validate_content(relative, data)
        expected = recorded[relative]
        if expected.get("bytes") != len(data) or expected.get("sha256") != _sha256(data):
            raise ValueError(f"public file receipt mismatch: {relative}")
    return manifest


@click.group()
def cli() -> None:
    """Build or verify a clean public release tree."""


@cli.command("build")
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--source-commit", default=None)
def build_command(output: Path, source_commit: str | None) -> None:
    """Build a new public tree; never replace an existing path."""
    commit = source_commit or _source_commit(SOURCE_ROOT)
    manifest = build_release(output.resolve(), commit)
    click.echo(
        f"PASS built {output} files={manifest['file_count']} "
        f"payload={manifest['release_payload_sha256']}"
    )


@cli.command("check")
@click.option("--root", "release_root", type=click.Path(path_type=Path), required=True)
def check_command(release_root: Path) -> None:
    """Verify exact manifest membership, bytes and safety boundary."""
    manifest = verify_tree(release_root.resolve())
    click.echo(
        f"PASS verified {release_root} files={manifest['file_count']} "
        f"payload={manifest['release_payload_sha256']}"
    )


if __name__ == "__main__":
    cli()
