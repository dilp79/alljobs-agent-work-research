"""How much of Russian work is done at a screen, weighted by who actually does it.

This is the denominator the project has been missing. Everything else it publishes is a
share, and a share needs to be divided by something defensible.

How the three inputs meet:

  work-mode labels   per O*NET task: screen / mixed / physical, from three raters, with the
                     tasks they split on settled by a stronger model
  the bridge         O*NET occupation -> ISCO-08 -> ОКЗ 2-digit group
  employment         from the labour force survey microdata, by ОКЗ 2-digit group

The direction of the join is the whole design. Employment is known for a GROUP of related
occupations, never for one occupation, because that is the depth the survey publishes. So
labels are aggregated up to the group and the group is weighted. The alternative — spreading
a group's employment down onto the occupations inside it — would require a rule that invents
within-group structure the data does not contain, and that invention would then be
invisible inside every published figure.

The assumption this makes, stated plainly because it is not testable here: the share of a
group's tasks that are screen work is taken from O*NET, which describes American jobs, and
applied to Russian employment counts. We assume a Russian driver and an American driver do
broadly the same kinds of task. Where that fails, this figure fails with it.

What it does NOT claim. Nothing about whether software can do any of this work. The label
answers where the work happens and nothing else, and the raters were told so explicitly.

Usage:
    python scripts/weight_work_mode_by_employment.py
"""

from __future__ import annotations

import collections
import csv
import glob
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Mapping

import click
import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from workforce_graph.config import get_db_path  # noqa: E402

WM_DIR = ROOT / "data" / "work_mode"
RU_DIR = ROOT / "data" / "ru"
MODES = ("screen", "mixed", "physical")

TASK_OCCUPATION_SQL = """
SELECT oa.activity_id, o.source_code
FROM curated.occupation_activity oa
JOIN curated.occupation o USING (occupation_id)
"""


def settled_labels() -> tuple[dict[str, str], dict[str, int]]:
    """One label per task, and where it came from.

    A task counts as settled when at least two raters answered and agreed, or when the
    adjudicator ruled on it. A task the raters split on and the adjudicator has not yet
    reached is left out rather than resolved by majority — a two-against-one vote is not a
    decision, and counting it as one would quietly fill the hardest part of the corpus with
    guesses.

    The two-rater minimum is not decoration. An earlier version tested `len(set(modes)) == 1`,
    which is trivially true of a single element, so a task only one rater had reached counted
    as unanimous. An audit found 1,246 such tasks — 7.3% of everything settled — and they
    leaned towards screen work (57% against a corpus average near 45%), because the raters
    run at different speeds and the fastest one was ahead on a part of the queue. Agreement
    requires someone to agree with.
    """
    MIN_RATERS = 2
    by_task: dict[str, dict[str, str]] = {}
    for path in sorted(glob.glob(str(WM_DIR / "*__r0.jsonl"))):
        run = os.path.basename(path)[:-6]
        for line in open(path, encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("mode"):
                by_task.setdefault(rec["activity_id"], {})[run] = rec["mode"]

    adjudicated: dict[str, str] = {}
    for path in sorted(glob.glob(str(WM_DIR / "ADJ_*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("mode"):
                adjudicated[rec["activity_id"]] = rec["mode"]

    final: dict[str, str] = {}
    source = collections.Counter()
    for aid, runs in by_task.items():
        modes = list(runs.values())
        if aid in adjudicated:
            final[aid] = adjudicated[aid]
            source["adjudicated"] += 1
        elif len(modes) < MIN_RATERS:
            source["only_one_rater_so_far"] += 1
        elif len(set(modes)) == 1:
            final[aid] = modes[0]
            source["unanimous"] += 1
        else:
            source["split_awaiting_adjudication"] += 1
    source["labelled_by_at_least_one_rater"] = len(by_task)
    return final, dict(source)


def mapped_tasks_by_group(
    pairs: Iterable[tuple[str, str]], onet_to_group: Mapping[str, str]
) -> dict[str, set[str]]:
    """Distinct corpus tasks reached by each employment group, labels or no labels.

    The complete mapped task inventory is the denominator.  Building it from only settled
    labels made a group with one answer indistinguishable from a fully labelled group, and
    duplicate occupation links could otherwise count the same shared task more than once.
    """
    tasks: dict[str, set[str]] = collections.defaultdict(set)
    for activity_id, onet_id in pairs:
        group = onet_to_group.get(onet_id)
        if group:
            tasks[group].add(activity_id)
    return dict(tasks)


def weighted_index_summary(
    tasks_by_group: Mapping[str, set[str]],
    counts_by_group: Mapping[str, Mapping[str, float]],
    group_share: Mapping[str, float],
    categories: tuple[str, ...],
) -> dict[str, object]:
    """Weight observed categories without expanding them over unsettled statements.

    A group's employment share is spread evenly over every distinct mapped statement in the
    group.  Observed categories receive only the mass of statements actually observed; the
    rest remains `unsettled`.  Returned index values are normalised only for the 99.2%-style
    mapping gap, never for label missingness inside a mapped group.
    """
    raw = collections.Counter()
    mapped_employment = 0.0
    fully_settled_employment = 0.0
    groups_fully_settled = 0

    for group, tasks in tasks_by_group.items():
        if group not in group_share or not tasks:
            continue
        share = float(group_share[group])
        total = len(tasks)
        counts = counts_by_group.get(group, {})
        observed = sum(float(counts.get(category, 0.0)) for category in categories)
        if observed > total + 1e-9:
            raise ValueError(f"{group}: {observed} observed task mass exceeds {total} mapped tasks")

        mapped_employment += share
        if abs(observed - total) <= 1e-9:
            fully_settled_employment += share
            groups_fully_settled += 1
        for category in categories:
            raw[category] += share * float(counts.get(category, 0.0)) / total
        raw["unsettled"] += share * (total - observed) / total

    if mapped_employment <= 0:
        raise ValueError("no mapped employment groups")
    weighted = {
        category: raw[category] / mapped_employment
        for category in categories + ("unsettled",)
    }
    settled_share = 1.0 - weighted["unsettled"]
    return {
        "mapped_employment_share": mapped_employment,
        "fully_settled_group_employment_share": fully_settled_employment,
        "groups_fully_settled": groups_fully_settled,
        "settled_statement_index_share": settled_share,
        "weighted_index": weighted,
    }


@click.command()
@click.option("--corpus-size", default=18796, show_default=True)
@click.option("--write", "write_path", default=str(WM_DIR / "weighted_result.json"), show_default=True)
def main(corpus_size: int, write_path: str) -> None:
    final, source = settled_labels()
    click.echo(f"settled labels: {len(final)} of {corpus_size} = {len(final)/corpus_size:.1%} of corpus")
    click.echo(f"  {source}")

    onet_to_group: dict[str, str] = {}
    group_share: dict[str, float] = {}
    group_name: dict[str, str] = {}
    for r in csv.DictReader((RU_DIR / "onet_to_okz2.csv").open(encoding="utf-8")):
        if r["group_share"]:
            onet_to_group[r["onet_id"]] = r["okz2"]
            group_share[r["okz2"]] = float(r["group_share"])
            if r["okz_name"]:
                group_name[r["okz2"]] = r["okz_name"]

    conn = duckdb.connect(str(get_db_path()), read_only=True)
    pairs = conn.execute(TASK_OCCUPATION_SQL).fetchall()
    conn.close()

    tasks_by_group = mapped_tasks_by_group(pairs, onet_to_group)
    per_group: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for group, tasks in tasks_by_group.items():
        for activity_id in tasks:
            mode = final.get(activity_id)
            if mode:
                per_group[group][mode] += 1

    summary = weighted_index_summary(tasks_by_group, per_group, group_share, MODES)
    weighted_index = summary["weighted_index"]
    settled_index_share = float(summary["settled_statement_index_share"])
    weighted = {
        mode: weighted_index[mode] / settled_index_share if settled_index_share else 0.0
        for mode in MODES
    }

    mapped_groups = sum(1 for group in tasks_by_group if group in group_share)
    click.echo(f"\nmapped employment groups: {mapped_groups} of {len(group_share)}")
    click.echo(f"Russian employment mapped to them: {summary['mapped_employment_share']:.1%}")
    click.echo(
        f"fully settled groups: {summary['groups_fully_settled']} of {mapped_groups}, carrying "
        f"{summary['fully_settled_group_employment_share']:.1%} of employment"
    )
    click.echo(
        f"settled share of the employment-weighted statement index: {settled_index_share:.1%}"
    )

    unweighted = collections.Counter(final.values())
    n_settled = len(final)

    click.echo("\n                 unweighted   weighted by employment")
    for m in MODES:
        click.echo(f"  {m:9s}      {unweighted[m]/n_settled:6.1%}        {weighted[m]:6.1%}")
    click.echo(
        f"\ndigital, strict   (screen)        {unweighted['screen']/n_settled:6.1%}        {weighted['screen']:6.1%}"
    )
    click.echo(
        f"digital, generous (screen+mixed)  "
        f"{(unweighted['screen']+unweighted['mixed'])/n_settled:6.1%}        "
        f"{weighted['screen']+weighted['mixed']:6.1%}"
    )

    strict_bounds = [
        weighted_index["screen"],
        weighted_index["screen"] + weighted_index["unsettled"],
    ]
    generous_bounds = [
        weighted_index["screen"] + weighted_index["mixed"],
        weighted_index["screen"] + weighted_index["mixed"] + weighted_index["unsettled"],
    ]
    click.echo("\nidentified set after retaining unsettled statements:")
    click.echo(f"  screen              {strict_bounds[0]:6.1%} – {strict_bounds[1]:6.1%}")
    click.echo(f"  screen plus mixed   {generous_bounds[0]:6.1%} – {generous_bounds[1]:6.1%}")

    click.echo("\nlargest groups, settled screen share and unsettled share:")
    for group in sorted(tasks_by_group, key=lambda g: -group_share.get(g, 0.0))[:8]:
        counts = per_group[group]
        n = len(tasks_by_group[group])
        click.echo(
            f"  {group_share[group]:5.1%} of employment | screen {counts['screen']/n:5.1%} | "
            f"unsettled {(n-sum(counts.values()))/n:5.1%} | "
            f"{group_name.get(group, '')[:46]}"
        )

    Path(write_path).write_text(
        json.dumps(
            {
                "settled_labels": n_settled,
                "corpus_size": corpus_size,
                "settled_share_of_corpus": n_settled / corpus_size,
                "label_source": source,
                "mapped_groups": mapped_groups,
                "employment_mapping_share": summary["mapped_employment_share"],
                "groups_fully_settled": summary["groups_fully_settled"],
                "fully_settled_group_employment_share": summary[
                    "fully_settled_group_employment_share"
                ],
                "settled_statement_index_share": settled_index_share,
                "unweighted": {m: unweighted[m] / n_settled for m in MODES},
                "weighted_by_employment": {m: weighted[m] for m in MODES},
                "weighted_statement_index": weighted_index,
                "digital_share_identified_set": {
                    "strict_screen": strict_bounds,
                    "generous_screen_or_mixed": generous_bounds,
                },
                "weight_denominator": (
                    "all distinct mapped task-group pairs; unsettled statements retain their "
                    "employment-weighted index mass"
                ),
                "assumption": (
                    "within-group task composition is taken from O*NET (US) and applied to "
                    "Russian employment counts"
                ),
                "incomplete": weighted_index["unsettled"] > 0,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    click.echo(f"\nwritten {write_path}")


if __name__ == "__main__":
    main()
