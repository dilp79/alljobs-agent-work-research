"""Reproduce the original AllJobs appendix to the pinned CohereLabs ATE release.

``fetch`` is the only command that accesses the network. It downloads public source bytes into
an external user cache, pins the Hub revision and MANIFEST SHA-256, and checks each named table.
``audit`` recomputes aggregate descriptive statistics offline. ``join-alljobs`` additionally
requires the owner's private AllJobs DuckDB and effective (post-review) mission bindings.
No command runs a model or an ATE tool. Public outputs contain original counts/provenance only,
never task text, descriptions, source parquet files or private binding rows.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
REVISION = "4b567ba98acc6ddf27b2abb9004844581083c5d8"
MANIFEST_SHA256 = "bcd60bb94d625cdc73cc988ae4c5c245c0a7957f1356b288f4e8ce596fa9cb35"
EFFECTIVE_BINDINGS_SHA256 = "8ab85234d091379d20c1a0989f6bc5d86f7868ddf258963f8c672d32d67c9357"
BASE_URL = f"https://huggingface.co/datasets/CohereLabs/ATE/resolve/{REVISION}"
TABLES = ("tasks", "onet_matches", "tools", "servers", "occupation_results",
          "cluster_taxonomy", "clusters", "usage_stats")
DEFAULT_CACHE = Path.home() / ".cache" / "alljobs" / "ate" / REVISION
CEILING = "advertised-tool nearest-task label coverage; no callable-tool, execution, adoption or ROI evidence"


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n").encode()


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def require_external_cache(cache: Path) -> None:
    if cache.resolve() == ROOT.parent.resolve() or ROOT.parent.resolve() in cache.resolve().parents:
        raise ValueError("ATE raw cache must be outside the repository")


def read_manifest(cache: Path) -> dict:
    path = cache / "MANIFEST.json"
    if not path.is_file():
        raise FileNotFoundError("MANIFEST.json missing; run explicit fetch or provide the verified cache")
    if sha256(path) != MANIFEST_SHA256:
        raise ValueError("pinned manifest SHA-256 mismatch; existing cache was not changed")
    manifest = json.loads(path.read_text())
    by_path = {row["path"]: row for row in manifest["files"]}
    return {name: by_path[f"{name}.parquet"] for name in TABLES}


def verify_cache(cache: Path) -> dict:
    require_external_cache(cache)
    expected = read_manifest(cache)
    files = []
    for name in TABLES:
        path = cache / f"{name}.parquet"
        if not path.is_file():
            raise FileNotFoundError(f"verified ATE table missing: {name}")
        row = expected[name]
        if path.stat().st_size != row["bytes"] or sha256(path) != row["sha256"]:
            raise ValueError(f"pinned table SHA-256/size mismatch: {name}")
        files.append({"table": name, "bytes": row["bytes"], "sha256": row["sha256"],
                      "hub_path": f"data/{name}/train-00000-of-00001.parquet"})
    return {"dataset": "CohereLabs/ATE", "revision": REVISION, "onet_version": "29.2",
            "manifest_sha256": MANIFEST_SHA256, "manifest_url": BASE_URL + "/MANIFEST.json",
            "files": files, "integrity_ceiling": "downloaded source bytes only; generation pipeline unverified"}


def _download(url: str, destination: Path, expected_sha: str, expected_bytes: int | None) -> None:
    if destination.exists():
        if sha256(destination) != expected_sha or (
            expected_bytes is not None and destination.stat().st_size != expected_bytes
        ):
            raise ValueError(f"refusing to replace nonmatching cached file: {destination.name}")
        print(f"Verified cached {destination.name}", flush=True)
        return
    request = urllib.request.Request(url, headers={"User-Agent": "AllJobs-ATE-replay/1"})
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            total = 0
            with urllib.request.urlopen(request, timeout=60) as response:
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if expected_bytes is not None and total > expected_bytes:
                        raise ValueError("download exceeds pinned byte length")
                    handle.write(block)
                    if total % (16 * 1024 * 1024) == 0:
                        print(f"Downloading {destination.name}: {total}/{expected_bytes} bytes", flush=True)
        if sha256(temporary) != expected_sha or (
            expected_bytes is not None and temporary.stat().st_size != expected_bytes
        ):
            raise ValueError(f"download checksum mismatch: {destination.name}")
        # Hard-link no-replace publication avoids overwriting another process's cache file.
        os.link(temporary, destination)
        print(f"Downloaded and verified {destination.name}", flush=True)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def fetch(cache: Path) -> dict:
    require_external_cache(cache)
    cache.mkdir(parents=True, exist_ok=True)
    _download(BASE_URL + "/MANIFEST.json", cache / "MANIFEST.json", MANIFEST_SHA256, None)
    for name, row in read_manifest(cache).items():
        _download(BASE_URL + f"/data/{name}/train-00000-of-00001.parquet",
                  cache / f"{name}.parquet", row["sha256"], row["bytes"])
    return verify_cache(cache)


def register_tables(conn: duckdb.DuckDBPyConnection, cache: Path) -> None:
    for name in TABLES:
        conn.read_parquet(str(cache / f"{name}.parquet")).create_view(name)


def scalar(conn: duckdb.DuckDBPyConnection, query: str) -> int:
    return int(conn.execute(query).fetchone()[0])


def counts(conn: duckdb.DuckDBPyConnection, query: str) -> dict:
    return {str(key) if key is not None else "missing": int(value)
            for key, value in conn.execute(query).fetchall()}


def core_metrics(conn: duckdb.DuckDBPyConnection) -> dict:
    n_tasks = scalar(conn, "SELECT count(*) FROM tasks")
    if scalar(conn, "SELECT count(DISTINCT task_id) FROM tasks") != n_tasks:
        raise ValueError("task_id is not a unique complete identifier")
    if scalar(conn, "SELECT count(*) FROM onet_matches WHERE rank IS NULL OR rank <> 1"):
        raise ValueError("audit requires the published rank-one table")
    unknown = scalar(conn, "SELECT count(*) FROM onet_matches WHERE match_quality IS NOT NULL "
                     "AND match_quality NOT IN ('good','partial','bad')")
    if unknown:
        raise ValueError("unrecognized source match_quality")
    if scalar(conn, "SELECT count(*) FROM onet_matches m LEFT JOIN tasks t USING(task_id) "
              "WHERE t.task_id IS NULL"):
        raise ValueError("matched task ID absent from source tasks")
    rows = scalar(conn, "SELECT count(*) FROM onet_matches")
    labelled = scalar(conn, "SELECT count(match_quality) FROM onet_matches")
    good = scalar(conn, "SELECT count(*) FROM onet_matches WHERE match_quality='good'")
    software = scalar(conn, "SELECT count(*) FROM tasks WHERE software_performable")
    good_tasks = scalar(conn, "SELECT count(DISTINCT task_id) FROM onet_matches WHERE match_quality='good'")
    if scalar(conn, "SELECT count(*) FROM onet_matches m JOIN tasks t USING(task_id) "
              "WHERE m.match_quality='good' AND NOT coalesce(t.software_performable,false)"):
        raise ValueError("good match is outside the software-eligible denominator")
    if not (rows and labelled and software):
        raise ValueError("empty descriptive denominator")
    occupations = scalar(conn, "SELECT count(DISTINCT soc_code) FROM tasks")
    eligible_occupations = scalar(conn, "SELECT count(DISTINCT soc_code) FROM tasks WHERE software_performable")
    good_occupations = scalar(conn, "SELECT count(DISTINCT soc_code) FROM onet_matches WHERE match_quality='good'")
    return {
        "label_denominators": {"rank_one_rows": rows, "successfully_labelled_pairs": labelled,
                               "missing_match_quality": rows - labelled},
        "labels": counts(conn, "SELECT match_quality,count(*) FROM onet_matches GROUP BY 1 ORDER BY 1"),
        "good_share_of_labelled_pairs": good / labelled,
        "good_share_of_all_rank_one_rows": good / rows,
        "all_task_ids": n_tasks, "software_eligible_task_ids": software,
        "good_matched_task_ids": good_tasks, "task_node_coverage": good_tasks / software,
        "candidate_task_ids": scalar(conn, "SELECT count(DISTINCT task_id) FROM onet_matches"),
        "occupations_all": occupations, "occupations_software_eligible": eligible_occupations,
        "occupations_good_matched": good_occupations,
        "eligible_occupations_without_good": eligible_occupations - good_occupations,
        "all_occupations_without_good": occupations - good_occupations,
        "task_text_duplicate_excess": n_tasks - scalar(conn, "SELECT count(DISTINCT task_text) FROM tasks"),
        "task_text_duplicate_groups": scalar(conn, "SELECT count(*) FROM (SELECT task_text FROM tasks "
                                               "GROUP BY 1 HAVING count(*)>1)"),
    }


def audit(cache: Path) -> dict:
    provenance = verify_cache(cache)
    with duckdb.connect() as conn:
        register_tables(conn, cache)
        result = core_metrics(conn)
        result["row_counts"] = {name: scalar(conn, f"SELECT count(*) FROM {name}") for name in TABLES}
        result["tools"] = {
            "nonnull_distinct_tool_ids": scalar(conn, "SELECT count(DISTINCT tool_id) FROM tools"),
            "null_tool_ids": scalar(conn, "SELECT count(*) FROM tools WHERE tool_id IS NULL"),
            "duplicate_nonnull_id_excess": scalar(conn, "SELECT count(tool_id)-count(DISTINCT tool_id) FROM tools"),
            "analysis_set_rows": scalar(conn, "SELECT count(*) FROM tools WHERE in_analysis_set"),
            "excluded_reasons": counts(conn, "SELECT excluded_reason,count(*) FROM tools GROUP BY 1 ORDER BY 1"),
            "null_descriptions": scalar(conn, "SELECT count(*) FROM tools WHERE description IS NULL"),
            "blank_descriptions": scalar(conn, "SELECT count(*) FROM tools WHERE trim(description)=''"),
            "listings_with_tools": scalar(conn, "SELECT count(DISTINCT mcp_id) FROM tools"),
        }
        result["occupation_coverage"] = {
            "n_eligible_at_least_three_tasks": scalar(conn, "SELECT count(*) FROM occupation_results "
                                                     "WHERE n_tasks_software_performable>=3"),
            "fully_covered_occupations": scalar(conn, "SELECT count(*) FROM occupation_results WHERE share_tasks_matched=1"),
            "fully_covered_at_least_three_tasks": scalar(conn, "SELECT count(*) FROM occupation_results "
                                                        "WHERE share_tasks_matched=1 AND n_tasks_software_performable>=3"),
            "sum_matched_tasks": scalar(conn, "SELECT sum(n_matched_tasks) FROM occupation_results"),
            "sum_matched_tools": scalar(conn, "SELECT sum(n_tools) FROM occupation_results"),
        }
        result["taxonomy"] = {
            "work_types": counts(conn, "SELECT work_type,count(*) FROM cluster_taxonomy GROUP BY 1 ORDER BY 1"),
            "work_types_tool_weighted": counts(conn, "SELECT work_type,sum(size) FROM cluster_taxonomy GROUP BY 1 ORDER BY 1"),
            "gates": counts(conn, "SELECT gate_category,count(*) FROM clusters GROUP BY 1 ORDER BY 1"),
        }
    value = {"schema_version": "alljobs.ate-descriptive-audit.v1", "claim_ceiling": CEILING,
             "provenance": provenance, "metrics": result, "model_calls": 0,
             "source_text_redistributed": False, "ate_tools_executed": 0}
    return seal(value)


def read_effective_bindings(path: Path) -> list[dict]:
    if path.name != "effective_candidate_bindings.csv":
        raise ValueError("use exact effective_candidate_bindings.csv; superseded aliases are refused")
    if sha256(path) != EFFECTIVE_BINDINGS_SHA256:
        raise ValueError("effective binding SHA-256 differs from the accepted post-review authority")
    with path.open() as handle:
        reader = csv.DictReader(handle)
        if not {"mission_id", "activity_id", "source_activity_id"}.issubset(reader.fieldnames or []):
            raise ValueError("effective bindings lack post-review identity columns")
        rows = list(reader)
    if len({r["mission_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate effective mission identity")
    return rows


def join_alljobs(cache: Path, database: Path, bindings: Path) -> dict:
    provenance = verify_cache(cache)
    effective = read_effective_bindings(bindings)
    if not database.is_file():
        raise FileNotFoundError("private AllJobs DuckDB required for join-alljobs")
    with duckdb.connect(str(database), read_only=True) as conn:
        local_rows = conn.execute("SELECT source_code,title,activity_id FROM curated.activity "
                                  "WHERE source_system='onet' AND activity_type='task' "
                                  "ORDER BY source_code").fetchall()
        staging_rows = conn.execute("SELECT cast(task_id AS VARCHAR),onet_soc_code "
                                    "FROM staging.stg_onet_task_statements ORDER BY task_id").fetchall()
        linked_rows = conn.execute("SELECT a.activity_id,o.source_code FROM curated.activity a "
                                   "JOIN curated.occupation_activity oa USING(activity_id) "
                                   "JOIN curated.occupation o USING(occupation_id) "
                                   "WHERE a.source_system='onet' AND a.activity_type='task' "
                                   "AND o.source_system='onet' AND oa.link_type='task' "
                                   "ORDER BY a.activity_id,o.source_code").fetchall()
    local = {tid: (text, aid) for tid, text, aid in local_rows}
    if len(local) != len(local_rows):
        raise ValueError("private local task source_code is not unique")
    staging: dict[str, set[str]] = collections.defaultdict(set)
    linked: dict[str, set[str]] = collections.defaultdict(set)
    for tid, soc in staging_rows:
        staging[tid].add(soc)
    for aid, soc in linked_rows:
        linked[aid].add(soc)
    with duckdb.connect() as conn:
        tasks = conn.read_parquet(str(cache / "tasks.parquet")).project(
            "task_id,task_text,soc_code,software_performable").fetchall()
        good = {row[0] for row in conn.read_parquet(str(cache / "onet_matches.parquet")).filter(
            "match_quality='good'").project("task_id").distinct().fetchall()}
    ate = {tid: (text, soc, software) for tid, text, soc, software in tasks}
    metrics = collections.Counter()
    changed_text_ids, missing_ids = [], []
    for tid, (text, soc, software) in sorted(ate.items()):
        if tid not in local:
            missing_ids.append(tid)
            metrics["ate_ids_absent_local"] += 1
            continue
        local_text, aid = local[tid]
        metrics["matched_task_ids"] += 1
        metrics["exact_text_equal" if text == local_text else "text_changed"] += 1
        metrics["staging_soc_equal" if soc in staging[tid] else "staging_soc_mismatch_or_missing"] += 1
        if text != local_text:
            changed_text_ids.append(tid)
        if not linked[aid]:
            metrics["matched_missing_curated_occupation_edge"] += 1
        elif soc in linked[aid]:
            metrics["matched_curated_soc_equal"] += 1
        else:
            metrics["matched_curated_soc_mismatch"] += 1
        metrics["software_eligible_matched"] += bool(software)
        metrics["good_matched_task_ids_retained"] += tid in good
    metrics["ate_task_ids"] = len(ate)
    metrics["local_task_ids"] = len(local)
    metrics["local_ids_absent_ate"] = len(set(local) - set(ate))
    metrics.setdefault("staging_soc_mismatch_or_missing", 0)
    metrics.setdefault("matched_curated_soc_mismatch", 0)
    source_by_aid = {aid: tid for tid, (_, aid) in local.items()}
    binding_metrics = collections.Counter()
    for row in effective:
        aid = row["activity_id"]
        tid = source_by_aid.get(aid)
        binding_metrics["effective_missions"] += 1
        binding_metrics["source_activity_replaced_by_review"] += aid != row["source_activity_id"]
        if tid is None:
            binding_metrics["effective_activity_absent_local"] += 1
            continue
        binding_metrics["effective_activity_in_local"] += 1
        binding_metrics["effective_task_id_in_ate"] += tid in ate
        binding_metrics["effective_task_id_with_good_descriptor_match"] += tid in good
    value = {
        "schema_version": "alljobs.ate-private-join-audit.v1", "claim_ceiling": CEILING,
        "reproduction_ceiling": "requires private current AllJobs DB and effective bindings; "
                                 "public aggregate receipt cannot recreate unavailable source rows",
        "provenance": provenance, "local_onet_version": "30.2", "join": dict(sorted(metrics.items())),
        "effective_bindings": dict(sorted(binding_metrics.items())),
        "changed_text_task_ids": changed_text_ids, "ate_ids_absent_local": missing_ids,
        "local_ids_absent_ate": sorted(set(local) - set(ate)),
        "private_source_receipts": {
            "database_sha256": sha256(database), "effective_bindings_sha256": sha256(bindings),
            "logical_task_rows_sha256": hashlib.sha256(canonical(local_rows)).hexdigest(),
            "logical_staging_soc_rows_sha256": hashlib.sha256(canonical(staging_rows)).hexdigest(),
            "logical_curated_links_sha256": hashlib.sha256(canonical(linked_rows)).hexdigest()},
        "private_source_rows_redistributed": False, "model_calls": 0,
    }
    return seal(value)


def seal(value: dict) -> dict:
    value["payload_sha256"] = hashlib.sha256(canonical(value)).hexdigest()
    return value


def write_result(path: Path, value: dict) -> None:
    data = canonical(value)
    if path.exists() and path.read_bytes() != data:
        raise ValueError("refusing replacement of a different audit output; select a new output path")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("xb") as handle:
            handle.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "audit", "join-alljobs"))
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--effective-bindings", type=Path)
    args = parser.parse_args()
    if args.command != "fetch" and args.output is None:
        parser.error("audit commands require an explicit --output")
    if args.command == "fetch":
        value = fetch(args.cache)
    elif args.command == "audit":
        value = audit(args.cache)
    else:
        if args.database is None or args.effective_bindings is None:
            parser.error("join-alljobs requires --database and --effective-bindings")
        value = join_alljobs(args.cache, args.database, args.effective_bindings)
    if args.output:
        write_result(args.output, value)
    print(json.dumps({"command": args.command, "revision": REVISION,
                      "payload_sha256": value.get("payload_sha256"), "model_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
