"""Offline verifier for an emitted AllJobs public research release."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import click

EXPECTED_FILE_SHA256 = {
    "docs/reports/2026-08-12-research-completion.md": (
        "a8164cbde2d866d5cdef98f44f8b9b0de06f109c02e4be5158625fb9de278886"
    ),
    "workforce-graph/data/benchmark_relevance/layer_two_freeze.json": (
        "bfc797d06de65e36dc48e11e2458db60d6cb3ad7567cae13ca4793d0ed31e5b2"
    ),
    "workforce-graph/data/evidence/registry.json": (
        "0acb9ccdc1d4021a696308c63def790b5ffd60d0d5bff010efa13ecff77eac97"
    ),
    "workforce-graph/data/work_mode/work_mode_final_2026-08-12.json": (
        "3c79b4bf6e2f3141d512505511774b9b8c93d744293d62f9dfb67ecd4b5a21c4"
    ),
    (
        "workforce-graph/data/work_mode/"
        "corrected_result_full_glm_2026-08-12_final-collection.json"
    ): "474ea91d35f540679e6f1333dfd9af785a054509b145b6c225d5e8ad2984e29c",
    (
        "workforce-graph/data/predictive_validity/"
        "successor_2026-08-12-v3/main.json"
    ): "fcd503ae28274c6c092e20060ff89be2c96c393048861fd8285997d14cbb801e",
    (
        "workforce-graph/data/predictive_validity/"
        "successor_2026-08-12-v3/analysis.json"
    ): "69b8954d4d67e271bad71aedcc8afc3e29e4fd13f30425256b058d7f81294578",
}


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path) -> dict[str, object]:
    builder_path = root / "workforce-graph" / "scripts" / "build_public_release.py"
    spec = importlib.util.spec_from_file_location("build_public_release", builder_path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load public release verifier")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    manifest = builder.verify_tree(root)

    for relative, expected in EXPECTED_FILE_SHA256.items():
        path = root / relative
        if sha256_path(path) != expected:
            raise ValueError(f"frozen artifact hash mismatch: {relative}")

    successor_root = (
        root / "workforce-graph" / "data" / "predictive_validity" /
        "successor_2026-08-12-v3"
    )
    build_script = root / "workforce-graph" / "scripts" / "build_predictive_validity_successor.py"
    build_spec = importlib.util.spec_from_file_location("build_predictive", build_script)
    if build_spec is None or build_spec.loader is None:
        raise ValueError("cannot load predictive payload verifier")
    build = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(build)
    payloads: dict[str, str] = {}
    for name in ("frame", "pilot", "main", "analysis"):
        artifact = json.loads((successor_root / f"{name}.json").read_text(encoding="utf-8"))
        expected = artifact.get("payload_sha256")
        observed = build.payload_hash(artifact)
        if expected != observed:
            raise ValueError(f"predictive artifact payload mismatch: {name}")
        payloads[name] = observed
    return {
        "release_payload_sha256": manifest["release_payload_sha256"],
        "file_count": manifest["file_count"],
        "predictive_payloads": payloads,
    }


@click.command()
@click.option("--root", type=click.Path(path_type=Path), required=True)
def cli(root: Path) -> None:
    """Verify the public manifest and named frozen evidence hashes."""
    result = verify(root.resolve())
    click.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    cli()
