"""Exact identity, missingness and pinned-input boundaries for the ATE appendix."""

from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ate_audit", ROOT / "scripts/reproduce_ate_audit.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_cache_without_manifest_refuses_before_reading_tables(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="MANIFEST"):
        audit.verify_cache(tmp_path)


def test_changed_manifest_is_not_repaired_or_trusted(tmp_path: Path) -> None:
    path = tmp_path / "MANIFEST.json"
    path.write_text('{"files": []}')
    before = path.read_bytes()
    with pytest.raises(ValueError, match="manifest SHA-256"):
        audit.verify_cache(tmp_path)
    assert path.read_bytes() == before


def test_rank_one_missing_labels_use_two_explicit_denominators() -> None:
    with duckdb.connect() as conn:
        conn.execute("CREATE TABLE tasks(task_id VARCHAR, task_text VARCHAR, soc_code VARCHAR, "
                     "software_performable BOOLEAN)")
        conn.execute("INSERT INTO tasks VALUES ('1','same','a',true),('2','same','b',true),"
                     "('3','other','c',false)")
        conn.execute("CREATE TABLE onet_matches(task_id VARCHAR, soc_code VARCHAR, "
                     "match_quality VARCHAR, rank INTEGER)")
        conn.execute("INSERT INTO onet_matches VALUES ('1','a','good',1),('1','a','partial',1),"
                     "('2','b',NULL,1)")
        result = audit.core_metrics(conn)
    assert result["label_denominators"] == {
        "rank_one_rows": 3, "successfully_labelled_pairs": 2, "missing_match_quality": 1}
    assert result["good_share_of_labelled_pairs"] == 0.5
    assert result["good_share_of_all_rank_one_rows"] == pytest.approx(1 / 3)
    assert result["task_node_coverage"] == 0.5
    assert result["task_text_duplicate_excess"] == 1


def test_stale_effective_binding_alias_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "candidate_bindings.csv"
    path.write_text("mission_id,activity_id,source_activity_id\na,new,old\n")
    with pytest.raises(ValueError, match="effective_candidate_bindings"):
        audit.read_effective_bindings(path)


def test_cache_must_be_outside_repository(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside"):
        audit.require_external_cache(ROOT / "data" / "ate_cache")


def test_correctly_named_but_unreviewed_binding_bytes_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "effective_candidate_bindings.csv"
    path.write_text("mission_id,activity_id,source_activity_id\na,new,old\n")
    with pytest.raises(ValueError, match="accepted post-review authority"):
        audit.read_effective_bindings(path)


def test_verified_cache_file_is_reused_without_network(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "cached.parquet"
    data = b"existing verified source bytes"
    path.write_bytes(data)
    def no_network(*args, **kwargs):
        raise AssertionError("network must not be reached for a valid cached file")
    monkeypatch.setattr(audit.urllib.request, "urlopen", no_network)
    audit._download("https://example.invalid/file", path, hashlib.sha256(data).hexdigest(), len(data))
    assert path.read_bytes() == data


def test_download_checksum_failure_leaves_no_published_cache_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "cached.parquet"
    monkeypatch.setattr(audit.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"wrong"))
    with pytest.raises(ValueError, match="download checksum mismatch"):
        audit._download("https://example.invalid/file", path, hashlib.sha256(b"right").hexdigest(), 5)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []
