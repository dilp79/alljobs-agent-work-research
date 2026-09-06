"""Offline data-to-table/figure replay of the September 2026 research note.

Default replay needs only public frozen evidence and original sufficient statistics. It does
not load a database, private model logs, credentials, or an API client. ``prepare-inputs`` is a
separate, explicit private-source extraction command; its output contains aggregate code/mode
cells and derived trial outcomes, never task text or raw generations. Frozen August evidence is
read-only. The 108 routes diagnose the retired code ordering, not automation or work-time shares.

Figures require matplotlib (tested with 3.10.8); --no-figures needs only the repository lock.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLICATION = Path("data/publication_2026_09_06")
INPUT_NAME = "replay_inputs.json"
RATERS = ("deepseek-v4-pro", "gemini-3.5-flash-lite", "minimax-m3")
ARMS = {"bare": "Worked example", "bare_schema": "Shape only", "bare_no_example": "No example"}
COMBINATIONS = ("code_order_median_low", "code_order_maximum", "code_order_minimum",
                "exact_code_unanimity")
WEIGHTS = ("one_task_one_vote", "onet_importance", "russian_employment")
POOLS = ("whole_corpus", "screen_only", "screen_and_mixed")
CEILING = "code-order sensitivity and synthetic conformance; not jobs, time, ROI or mission success"


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_digest(value: dict) -> str:
    return digest(canonical({k: v for k, v in value.items() if k != "payload_sha256"}))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_script(root: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, root / "scripts" / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ValueError(f"script unavailable: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_receipt(root: Path, path: Path) -> dict:
    data = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "bytes": len(data), "sha256": digest(data)}


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def freeze(path: Path, value: dict) -> None:
    data = canonical(value)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing changed frozen supplement: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def prepare_inputs(root: Path) -> dict:
    """Derive public sufficient statistics from exact local source rows, without model calls."""
    import duckdb

    sources: list[dict] = []
    scores: dict[str, dict[str, int]] = collections.defaultdict(dict)
    selection = {}
    for rater in RATERS:
        path = root / "data/scoring/full" / f"{rater}.jsonl"
        records = jsonl(path)
        sources.append(source_receipt(root, path))
        seen = set()
        for row in records:
            level = row.get("autonomy_level")
            if type(level) is not int or level not in range(5):
                raise ValueError(f"invalid retired autonomy code: {rater}")
            scores[row["activity_id"]][rater] = level
            seen.add(row["activity_id"])
        selection[rater] = {"rows": len(records), "latest_unique_activities": len(seen),
                            "superseded_rows": len(records) - len(seen)}
    sample = root / "data/scoring/full/sample.jsonl"
    sources.append(source_receipt(root, sample))
    importance = {r["activity_id"]: float(r["importance"]) for r in jsonl(sample)
                  if r.get("importance") is not None}
    snapshot_path = root / "data/work_mode/work_mode_final_2026-08-12.json"
    snapshot = read_json(snapshot_path)
    sources.append(source_receipt(root, snapshot_path))
    if set(scores) != set(snapshot["activities"]):
        raise ValueError("score corpus differs from frozen final work-mode inventory")
    bridge_path = root / "data/ru/onet_to_okz2.csv"
    sources.append(source_receipt(root, bridge_path))
    onet_group, group_share = {}, {}
    with bridge_path.open() as handle:
        for row in csv.DictReader(handle):
            if row["group_share"]:
                onet_group[row["onet_id"]] = row["okz2"]
                group_share[row["okz2"]] = float(row["group_share"])
    # Match the historical diagnostic's group-level denominator, including every reached
    # activity in occupation_activity. This reproduces its convention, not a hours measure.
    sql = ("SELECT oa.activity_id, o.source_code FROM curated.occupation_activity oa "
           "JOIN curated.occupation o USING (occupation_id) "
           "ORDER BY oa.activity_id, o.source_code")
    with duckdb.connect(str(root / "data/workforce_graph.duckdb"), read_only=True) as conn:
        pairs = conn.execute(sql).fetchall()
    groups: dict[str, set[str]] = collections.defaultdict(set)
    for aid, onet in pairs:
        if onet in onet_group:
            groups[onet_group[onet]].add(aid)
    employment: dict[str, float] = collections.defaultdict(float)
    for group in sorted(groups):
        tasks = groups[group]
        for aid in sorted(tasks):
            employment[aid] += group_share[group] / len(tasks)
    grouped: dict[tuple, dict] = {}
    for aid in sorted(scores):
        levels = tuple(scores[aid].get(r) for r in RATERS)
        mode = snapshot["activities"][aid]["label"]
        key = (*levels, mode)
        cell = grouped.setdefault(key, {"levels": list(levels), "mode": mode, "count": 0,
                                        "importance_mass": 0.0, "employment_mass": 0.0})
        cell["count"] += 1
        cell["importance_mass"] += importance.get(aid, 0.0)
        cell["employment_mass"] += employment.get(aid, 0.0)
    cells = sorted(grouped.values(), key=lambda c: json.dumps([c["levels"], c["mode"]]))

    layer_path = root / "data/benchmark_relevance/layer_two_freeze.json"
    layer = read_json(layer_path)
    sources.append(source_receipt(root, layer_path))
    expected_path = root / "benchmark/support_backoffice/v1/fixtures/expected_outputs.jsonl"
    sources.append(source_receipt(root, expected_path))
    expected = {r["mission_id"]: r["payload"] for r in jsonl(expected_path)}
    semantic = load_script(root, "semantic_match")
    sources.append(source_receipt(root, root / "scripts/semantic_match.py"))
    mission_map = {m["mission_id"]: m for m in layer["missions"]}
    trials, trial_selection = [], {}
    for arm in ARMS:
        path = root / "data/trials" / f"TRIALS_{arm}_deepseek-v4-pro.jsonl"
        sources.append(source_receipt(root, path))
        records = jsonl(path)
        latest = {}
        run_spec = "legacy-missing-run-spec" if arm == "bare" else "2026-08-10.1"
        for row in records:
            if row["arm"] != arm or row.get("run_spec", "legacy-missing-run-spec") != run_spec:
                raise ValueError("unexpected historical arm/run_spec")
            latest[row["mission_id"]] = row
        trial_selection[arm] = {"raw_rows": len(records), "latest_unique_missions": len(latest),
                                "superseded_rows": len(records) - len(latest), "run_spec": run_spec}
        for mid, row in sorted(latest.items()):
            mission = mission_map[mid]
            if not mission["primary_measured"]:
                raise ValueError("arm target is outside the frozen measured cohort")
            answer = row.get("deliverable")
            answered = row.get("status") == "ok" and isinstance(answer, dict)
            suite = (row.get("verdict") or {}).get("conformant") if answered else None
            sem = semantic.compare(expected[mid], answer)["matched"] if answered else None
            if answered and type(suite) is not bool:
                raise ValueError("answered row has no recorded suite/domain verdict")
            if arm == "bare" and (suite != mission["outcomes"]["byte_suite_checker"]
                                   or sem != mission["outcomes"]["semantic_hardened"]):
                raise ValueError("worked-example outcomes differ from immutable layer-two freeze")
            trials.append({"mission_id": mid, "category": mission["category"], "arm": arm,
                           "complete_votes": mission["complete_vote_join"], "answered": answered,
                           "status": row["status"], "suite_pass": suite, "semantic_pass": sem})
    artifact = {
        "schema_version": "alljobs.publication-replay-inputs.v1", "claim_ceiling": CEILING,
        "rights": "Original aggregate statistics and derived trial outcomes only; no source text, "
                  "raw model generation, WEF/WORKBank records or labour-force microdata.",
        "source_receipts": sources,
        "logical_occupation_activity_source": {"sql": sql, "rows": len(pairs),
                                                "sha256": digest(canonical(pairs))},
        "sensitivity": {"raters": list(RATERS), "scored_activities": len(scores),
                        "complete_rater_activities": sum(len(v) == 3 for v in scores.values()),
                        "selection": selection, "cells": cells,
                        "work_mode_authority": snapshot["snapshot_payload_sha256"],
                        "cohort": "final 2026-08-12 work-mode partition; additive replay, not the "
                                  "unfrozen work-mode checkpoint of the historical 108-grid",
                        "weight_rule": "one vote or O*NET importance or group employment mass; "
                                       "groups divide their share across distinct linked activities; "
                                       "missing weights contribute zero; none measures task time"},
        "scaffold": {"selection": trial_selection, "rows": trials,
                     "suite_outcome": "Recorded historical suite/domain boolean, not regraded "
                                      "without private deliverables in the public replay",
                     "semantic_outcome": "Hardened comparator applied during extraction; public "
                                         "replay aggregates derived outcomes, not omitted prose"},
        "historical_sensitivity_reference": source_receipt(root, root / "data/scoring/sensitivity.json"),
    }
    artifact["payload_sha256"] = payload_digest(artifact)
    freeze(root / PUBLICATION / INPUT_NAME, artifact)
    return artifact


def sensitivity_grid(cells: list[dict]) -> list[dict]:
    """Calculate all 108 retired-code diagnostic routes from sufficient aggregate cells."""
    result = []
    for combination, threshold, weight, pool in itertools.product(COMBINATIONS, (2, 3, 4),
                                                                 WEIGHTS, POOLS):
        numerator = declared = settled = 0.0
        for cell in cells:
            if pool == "screen_only" and cell["mode"] != "screen":
                continue
            if pool == "screen_and_mixed" and cell["mode"] not in ("screen", "mixed"):
                continue
            field = {"one_task_one_vote": "count", "onet_importance": "importance_mass",
                     "russian_employment": "employment_mass"}[weight]
            mass = cell[field]
            declared += mass
            values = sorted(v for v in cell["levels"] if v is not None)
            if not values:
                raise ValueError("cell has no observed retired codes")
            if combination == "exact_code_unanimity" and len(set(values)) != 1:
                continue
            level = {"code_order_median_low": values[(len(values) - 1) // 2],
                     "code_order_maximum": values[-1], "code_order_minimum": values[0],
                     "exact_code_unanimity": values[0]}[combination]
            settled += mass
            if level >= threshold:
                numerator += mass
        if declared <= 0:
            raise ValueError(f"empty declared diagnostic pool: {pool}/{weight}")
        abstained = 1.0 - settled / declared
        result.append({"combination": combination, "threshold": threshold, "weight": weight,
                       "denominator": pool, "numerator_mass": numerator, "declared_mass": declared,
                       "settled_mass": settled, "share_of_declared": numerator / declared,
                       "share_of_settled": numerator / settled if settled else None,
                       "abstained_share": abstained, "eligible_for_extrema": abstained <= 0.5})
    return result


def scaffold_table(rows: list[dict]) -> list[dict]:
    table = []
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        if not selected:
            continue
        for cohort in ("all_answered", "complete_vote_answered"):
            cohort_rows = [r for r in selected if cohort == "all_answered" or r["complete_votes"]]
            answered = [r for r in cohort_rows if r["answered"]]
            for checker, field in (("suite_domain", "suite_pass"),
                                   ("semantic_hardened", "semantic_pass")):
                if any(type(r[field]) is not bool for r in answered):
                    raise ValueError("answered trial has missing checker outcome")
                passes = sum(r[field] for r in answered)
                table.append({"arm": arm, "cohort": cohort, "checker": checker,
                              "passes": passes, "answered": len(answered),
                              "selected": len(cohort_rows),
                              "unanswered": len(cohort_rows) - len(answered),
                              "pass_share": passes / len(answered) if answered else None})
    return table


def v3_result(root: Path, *, permutations: int = 1999) -> tuple[dict, list[dict]]:
    analysis = load_script(root, "analyze_predictive_validity_successor")
    directory = root / "data/predictive_validity/successor_2026-08-12-v3"
    frame, main, frozen = (read_json(directory / f"{name}.json")
                           for name in ("frame", "main", "analysis"))
    rows = analysis.rows_from_artifacts(frame, main)
    cases = {r["case_id"]: r for r in frame["main_cases"]}
    for record in main["records"]:
        case = cases[record["case_id"]]
        observed = analysis.builder.check_operator_output(
            case["base_mission_id"], case["input_payload"], record["deliverable"] or {}
        ).passed
        if observed != record["outcome"]["conformant"]:
            raise ValueError("V3 deliverable grade differs from frozen outcome")
    baseline = analysis.cross_validated_log_loss(rows, include_votes=False)
    augmented = analysis.cross_validated_log_loss(rows, include_votes=True)
    improvement = baseline["log_loss"] - augmented["log_loss"]
    expected = frozen["result"]["predictive_analysis"]
    for key, value in (("baseline_log_loss", baseline["log_loss"]),
                       ("augmented_log_loss", augmented["log_loss"])):
        if not math.isclose(value, expected[key], rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"V3 analytical regression: {key}")
    exceedances = 0
    for index in range(permutations):
        shuffled = analysis.permute_votes_within_category(
            rows, seed=f"{analysis.builder.FRAME_SEED}:blocked-permutation:{index}")
        null_loss = analysis.cross_validated_log_loss(shuffled, include_votes=True)["log_loss"]
        exceedances += baseline["log_loss"] - null_loss >= improvement - 1e-15
        if (index + 1) % 200 == 0:
            print(f"Permutation replay: {index + 1}/{permutations}", flush=True)
    p_value = (exceedances + 1) / (permutations + 1) if permutations else None
    if permutations == 1999 and p_value != expected["blocked_permutation_p_one_sided"]:
        raise ValueError("V3 permutation regression")
    category_rows = []
    for category in analysis.CATEGORY_ORDER:
        members = [r for r in rows if r["category"] == category]
        failures = sum(r["failure"] for r in members)
        category_rows.append({"category": category, "n": len(members), "failures": failures,
                              "passes": len(members) - failures})
    for row in rows:
        mid = row["base_mission_id"]
        row["baseline_held_out_probability_failure"] = baseline["predictions"][mid]
        row["augmented_held_out_probability_failure"] = augmented["predictions"][mid]
    return {"n": len(rows), "passes": sum(not r["failure"] for r in rows),
            "failures": sum(r["failure"] for r in rows),
            "baseline_log_loss": baseline["log_loss"], "augmented_log_loss": augmented["log_loss"],
            "held_out_log_loss_improvement": improvement,
            "blocked_permutation_p_one_sided": p_value,
            "permutations": permutations,
            "permutation_status": "recomputed" if permutations else "not_recomputed",
            "historical_permutation_p_reference_only": expected["blocked_permutation_p_one_sided"],
            "homogeneous_categories": sum(r["failures"] in (0, r["n"]) for r in category_rows),
            "categories": category_rows}, rows


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def plot_figures(output: Path, grid: list[dict], scaffold: list[dict], v3: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "svg.fonttype": "none", "svg.hashsalt": "alljobs-note-2026-09-06"})

    def save(fig, name):
        fig.savefig(output / f"{name}.svg", bbox_inches="tight",
                    metadata={"Date": None, "Creator": "AllJobs replay"})
        fig.savefig(output / f"{name}.png", dpi=180, bbox_inches="tight",
                    metadata={"Software": "AllJobs replay"})
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.4), layout="constrained")
    for threshold, colour in ((2, "#1565c0"), (3, "#d96b20"), (4, "#6c3e91")):
        selected = sorted((r for r in grid if r["threshold"] == threshold),
                          key=lambda r: r["share_of_declared"])
        for eligible, marker in ((True, "o"), (False, "x")):
            points = [(i + 1, r["share_of_declared"] * 100) for i, r in enumerate(selected)
                      if r["eligible_for_extrema"] == eligible]
            if points:
                label = f"code >= {threshold}" if eligible else (
                    ">50% abstention (excluded from extrema)" if threshold == 2 else None)
                ax.scatter(*zip(*points), color=colour, marker=marker, s=30, label=label)
    ax.set(title="Retired code-order diagnostic: 108 analysis conventions",
           xlabel="Within-threshold rank (36 conventions each)",
           ylabel="Share of declared weighted task-statement pool (%)", ylim=(-2, 102))
    ax.legend(loc="upper left")
    ax.grid(axis="y", alpha=0.2)
    fig.text(0.02, -0.025, "Final Aug 12 work-mode partition. Crosses: >50% abstention; excluded "
             "from extrema. Not automation or working-time estimates.", fontsize=9)
    save(fig, "figure_1_definition_sensitivity")

    fig, ax = plt.subplots(figsize=(10, 5.4), layout="constrained")
    for j, (checker, label, colour) in enumerate((("suite_domain", "Suite/domain", "#1565c0"),
                                                 ("semantic_hardened", "Semantic", "#d96b20"))):
        values = [next(r for r in scaffold if r["arm"] == arm and r["checker"] == checker
                       and r["cohort"] == "all_answered") for arm in ARMS]
        positions = [i + (j - 0.5) * 0.32 for i in range(3)]
        ax.bar(positions, [r["pass_share"] * 100 for r in values], width=0.3,
               color=colour, label=label)
        for x, row in zip(positions, values, strict=True):
            ax.text(x, row["pass_share"] * 100 + 2, f"{row['passes']}/{row['answered']}",
                    ha="center", fontsize=10)
    ax.set(xticks=range(3), xticklabels=list(ARMS.values()), ylim=(0, 110),
           ylabel="Passes / answered missions (%)", title="Historical no-tool arms: two checkers")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.text(0.02, -0.025, "Latest eligible records; no-example has one unanswered target. "
             "Scaffold dependence, not an isolated causal effect. Prose/human review unverified.",
             fontsize=9)
    save(fig, "figure_2_scaffold_checkers")

    fig, (ax, loss) = plt.subplots(1, 2, figsize=(12, 6), layout="constrained",
                                   gridspec_kw={"width_ratios": [2.2, 1]})
    categories = v3["categories"]
    ax.barh([r["category"].replace("_", " ") for r in categories],
            [r["passes"] for r in categories], color="#25827a", label="Pass")
    ax.barh([r["category"].replace("_", " ") for r in categories],
            [r["failures"] for r in categories], left=[r["passes"] for r in categories],
            color="#b4474a", label="Fail")
    ax.set(xlabel="Missions (7 per category)", xlim=(0, 7),
           title=f"V3: {v3['passes']} passes, {v3['failures']} failures")
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside upper center", ncols=2)
    for i, key in enumerate(("baseline_log_loss", "augmented_log_loss")):
        loss.bar(i, v3[key], color=("#1565c0", "#d96b20")[i])
        loss.text(i, v3[key] + 0.01, f"{v3[key]:.4f}", ha="center")
    loss.set(xticks=[0, 1], xticklabels=["Category +\ndifficulty", "+ three\nvote doses"],
             ylim=(0, 0.65), ylabel="Five-fold held-out log loss (lower is better)")
    fig.text(0.02, -0.025, "One model + worked example + one read_case tool. Six categories "
             "have homogeneous outcomes; no claim of absent association outside this contour.",
             fontsize=9)
    save(fig, "figure_3_v3_prediction")


def reproduce(root: Path, output: Path, *, figures: bool = True, permutations: int = 1999) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing existing replay output; select a new --output directory")
    path = root / PUBLICATION / INPUT_NAME
    if not path.is_file():
        raise FileNotFoundError("publication inputs missing; obtain the complete public supplement")
    inputs = read_json(path)
    if inputs.get("schema_version") != "alljobs.publication-replay-inputs.v1":
        raise ValueError("unknown publication input schema")
    if inputs.get("payload_sha256") != payload_digest(inputs):
        raise ValueError("publication input payload hash mismatch")
    cells = inputs["sensitivity"]["cells"]
    if sum(c["count"] for c in cells) != inputs["sensitivity"]["scored_activities"]:
        raise ValueError("sensitivity sufficient statistics do not cover the declared inventory")
    grid = sensitivity_grid(cells)
    scaffold = scaffold_table(inputs["scaffold"]["rows"])
    v3, rows = v3_result(root, permutations=permutations)
    eligible = [r for r in grid if r["eligible_for_extrema"]]
    lo, hi = min(r["share_of_declared"] for r in eligible), max(r["share_of_declared"] for r in eligible)
    result = {"schema_version": "alljobs.publication-replay.v1", "claim_ceiling": CEILING,
              "inputs_payload_sha256": inputs["payload_sha256"],
              "sensitivity": {"routes": len(grid), "eligible_routes": len(eligible),
                              "lowest": lo, "highest": hi, "ratio": hi / lo if lo else None,
                              "cohort": inputs["sensitivity"]["cohort"]},
              "scaffold": scaffold, "v3": v3, "model_calls": 0}
    result["payload_sha256"] = payload_digest(result)
    # All source checks and calculations precede exclusive output creation. Existing directories
    # are refused so a replay cannot overwrite the shipped tables or figures.
    if output.resolve() == root.resolve() or output.resolve() == (root / PUBLICATION).resolve():
        raise ValueError("output must be a separate replay directory")
    if root.resolve() in output.resolve().parents and output.resolve() != (
        root / PUBLICATION / "reproduced"
    ).resolve():
        raise ValueError("in-repository output is restricted to the supplement reproduced directory")
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / "definition_sensitivity.csv", grid)
    write_csv(output / "scaffold_checkers.csv", scaffold)
    write_csv(output / "v3_categories.csv", v3["categories"])
    tidy = [{**{k: v for k, v in r.items() if k != "vote_doses"},
             **{f"dose_{k}": v for k, v in r["vote_doses"].items()}} for r in rows]
    write_csv(output / "v3_missions.csv", tidy)
    (output / "results.json").write_bytes(canonical(result))
    if figures:
        plot_figures(output, grid, scaffold, v3)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("replay", "prepare-inputs"), default="replay")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--skip-permutations", action="store_true",
                        help="Recompute loss/grades, label permutation p as historical reference only")
    args = parser.parse_args()
    if args.command == "prepare-inputs":
        value = prepare_inputs(args.root)
        print(f"Prepared original sufficient statistics: {value['payload_sha256']}")
    else:
        output = args.output or args.root / PUBLICATION / "reproduced"
        value = reproduce(args.root, output, figures=not args.no_figures,
                          permutations=0 if args.skip_permutations else 1999)
        print(json.dumps({"output": str(output), "payload_sha256": value["payload_sha256"],
                          "sensitivity": value["sensitivity"], "model_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
