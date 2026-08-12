"""Carry the measured leak back into the headline without conflating uncertainties.

The three-way instrument forced every task into screen, mixed or physical. The four-way
experiment measured what that forcing cost: offered a way to decline, the same rater declined
on 20% of the tasks its peers had split on and on 2.4% of the tasks nobody ever doubted. The
gap is real, and the tasks it lifts out were disproportionately ones the three-way pass had
called screen work. So the published digital share is too high by an amount we can now
estimate instead of argue about.

What this does. For every settled task it asks how likely that task would have been declined,
had the rater been allowed to. The probability comes from the experiment, conditioned on two
things that both matter:

  stratum     whether the raters split on this task or agreed unanimously. Splitting is the
              strongest available signal that a statement is underspecified, and the decline
              rates in the two arms differ by an order of magnitude.
  prior label what the three-way instrument called it. Uncertainty did not leak evenly; it
              leaked mostly into screen, which is exactly why the correction is not symmetric.

Each settled task then contributes (1 - p) of itself to its label and p to an "unknown" pile.
Unsettled tasks remain in a separate pile rather than disappearing. The piles are aggregated
to occupation groups over the complete mapped statement inventory and weighted by Russian
employment, and the result is reported as two numbers:

  low    every unknown task is not screen work
  high   every unknown task is screen work

This low/high pair is a partial-identification and directional sensitivity range. It is not a
confidence interval. Sampling variation in the answered experiment attempts is reported as a
separate Wilson component, with no joint headline coverage claim, and historical-to-current arm
drift is reported as a separate transport audit.

What this does NOT do. It does not decide the unknown tasks. It does not treat a declined
task as evidence of physical work, which is the mistake that would quietly shrink the digital
share instead of quietly inflating it. And it inherits every assumption of the weighting step
underneath it, including that Russian and American occupations of the same group do broadly
the same kinds of task.

Two honest weaknesses, stated because they bound how far this can be pushed:

  A previously quoted narrow robustness range used the pre-missingness method and is withdrawn.
  Robustness must be recomputed from a hash-bound current state with the full GLM experiment;
  the 13-row failed Gemini stub is not a replication arm. Route receipts and a minimum experiment
  row count are checked before a result is produced.

  Cells thin out fast. Where a stratum-by-label cell has too few observations to estimate a
  rate, the stratum's overall rate is used instead and the substitution is reported, never
  silently applied.

Usage:
    python scripts/correct_for_uncertainty.py --state-snapshot SNAPSHOT.json
    python scripts/correct_for_uncertainty.py --state-snapshot FINAL.json \
      --baseline-snapshot BASELINE.json --rater glm-5.2 --min-cell 20
"""

from __future__ import annotations

import collections
import csv
import glob
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import click
import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from workforce_graph.config import get_db_path

_spec = importlib.util.spec_from_file_location(
    "weight_work_mode", Path(__file__).parent / "weight_work_mode_by_employment.py"
)
wwm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wwm)

_freeze_spec = importlib.util.spec_from_file_location(
    "freeze_work_mode_snapshot", Path(__file__).parent / "freeze_work_mode_snapshot.py"
)
fws = importlib.util.module_from_spec(_freeze_spec)
_freeze_spec.loader.exec_module(fws)

WM_DIR = ROOT / "data" / "work_mode"
RU_DIR = ROOT / "data" / "ru"
MODES = wwm.MODES
STRATA = ("contested", "control")
CORRECTED_SCHEMA = "alljobs.work-mode-corrected-result/v1"


def _snapshot_state(snapshot: dict[str, object]) -> dict[str, object]:
    activities = snapshot["activities"]
    final = {
        activity_id: row["label"]
        for activity_id, row in activities.items()
        if row.get("label") in MODES
    }
    stratum = {
        activity_id: row["stratum"]
        for activity_id, row in activities.items()
        if row.get("stratum") in ("contested", "control")
    }
    n_raters = {activity_id: int(row.get("n_raters", 0)) for activity_id, row in activities.items()}
    readings = {
        activity_id: dict(row.get("readings", {})) for activity_id, row in activities.items()
    }
    return {
        "final": final,
        "stratum": stratum,
        "n_raters": n_raters,
        "readings": readings,
        "label_source": dict(snapshot["partition_counts"].get("label_source", {})),
        "snapshot": snapshot,
    }


def _live_snapshot() -> dict[str, object]:
    """Read live label inputs once each; prefer an explicit snapshot for publishable runs."""
    return fws.build_snapshot(
        sorted(WM_DIR.glob("*__r0.jsonl")),
        sorted(WM_DIR.glob("ADJ_*.jsonl")),
        snapshot_date="runtime-unfrozen",
        third_rater="unspecified",
        third_rater_status="live state; completion not asserted",
    )


def load_work_mode_state(snapshot_path: Path | None = None) -> dict[str, object]:
    snapshot = fws.load_snapshot(snapshot_path) if snapshot_path else _live_snapshot()
    return _snapshot_state(snapshot)


def strata_of_corpus() -> dict[str, str]:
    """Which tasks the raters split on, derived from one-read input buffers."""
    return load_work_mode_state()["stratum"]


def decline_rate_bounds(attempted: int, answered: int, declined: int) -> tuple[float, float]:
    """Bound the decline rate while retaining unanswered attempts in the denominator."""
    if not 0 <= declined <= answered <= attempted:
        raise ValueError("decline counts must satisfy 0 <= declined <= answered <= attempted")
    if attempted == 0:
        return 0.0, 0.0
    return declined / attempted, (declined + attempted - answered) / attempted


def wilson_interval(successes: int, trials: int, coverage: float = 0.95) -> tuple[float, float]:
    """Two-sided Wilson score interval; an empty cell is explicitly unidentified."""
    if not 0 <= successes <= trials:
        raise ValueError("Wilson counts must satisfy 0 <= successes <= trials")
    if not 0.0 < coverage < 1.0:
        raise ValueError("coverage must be between zero and one")
    if trials == 0:
        return 0.0, 1.0
    z = NormalDist().inv_cdf(0.5 + coverage / 2.0)
    z2 = z * z
    p = successes / trials
    denominator = 1.0 + z2 / trials
    centre = (p + z2 / (2.0 * trials)) / denominator
    half_width = z * ((p * (1.0 - p) / trials + z2 / (4.0 * trials * trials)) ** 0.5) / denominator
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def validate_experiment_route(
    records: list[dict], requested_rater: str, minimum_rows: int = 1
) -> dict[str, object]:
    """Fail closed on a short stub, requested-model drift, or served-route substitution."""
    if len(records) < minimum_rows:
        raise ValueError(
            f"{requested_rater}: experiment has {len(records)} rows; minimum is {minimum_rows}"
        )
    requested = collections.Counter(str(record.get("model_id") or "missing") for record in records)
    wrong_requested = {
        model: count for model, count in requested.items() if model != requested_rater
    }
    if wrong_requested:
        raise ValueError(
            f"{requested_rater}: experiment contains other requested routes: {wrong_requested}"
        )
    served = collections.Counter()
    substitutions = collections.Counter()
    refused_substitutions = collections.Counter()
    for record in records:
        backend = record.get("backend")
        if not backend:
            continue
        backend = str(backend)
        served[backend] += 1
        served_model = backend.rsplit("/", 1)[-1]
        if served_model != requested_rater:
            if record.get("mode") is not None:
                substitutions[backend] += 1
            elif str(record.get("status") or "").startswith("substituted:"):
                refused_substitutions[backend] += 1
            else:
                substitutions[backend] += 1
    if substitutions:
        raise ValueError(
            f"{requested_rater}: served-route substitutions present: {dict(substitutions)}"
        )
    return {
        "requested_rater": requested_rater,
        "rows": len(records),
        "minimum_rows": minimum_rows,
        "requested_model_ids": dict(sorted(requested.items())),
        "served_backends": dict(sorted(served.items())),
        "refused_substitutions_retained_as_lost_attempts": dict(
            sorted(refused_substitutions.items())
        ),
        "route_guard_passed": True,
    }


def _arm_rate_summary(records: list[dict], arm_for: dict[str, str]) -> dict[str, object]:
    attempted = collections.Counter()
    answered = collections.Counter()
    declined = collections.Counter()
    missing_arm = 0
    for record in records:
        activity_id = str(record.get("activity_id") or "")
        arm = arm_for.get(activity_id)
        if arm not in STRATA:
            missing_arm += 1
            continue
        attempted[arm] += 1
        if not record.get("mode"):
            continue
        answered[arm] += 1
        if record.get("mode") == "unclear":
            declined[arm] += 1
    return {
        "arms": {
            arm: {
                "attempted": attempted[arm],
                "answered": answered[arm],
                "lost": attempted[arm] - answered[arm],
                "declined": declined[arm],
                "missingness_rate_bounds": list(
                    decline_rate_bounds(attempted[arm], answered[arm], declined[arm])
                ),
            }
            for arm in STRATA
        },
        "rows_without_arm": missing_arm,
    }


def arm_transport_audit(
    records: list[dict], current_stratum: dict[str, str] | None
) -> dict[str, object]:
    historical = {
        str(record.get("activity_id")): str(record.get("arm"))
        for record in records
        if record.get("activity_id") and record.get("arm") in STRATA
    }
    if current_stratum is None:
        return {
            "status": "not_computed_without_current_partition",
            "estimator_arm_policy": "historical",
        }
    transition = collections.Counter()
    changed_ids: list[str] = []
    missing_current: list[str] = []
    for activity_id, old_arm in sorted(historical.items()):
        new_arm = current_stratum.get(activity_id)
        if new_arm not in STRATA:
            missing_current.append(activity_id)
            continue
        transition[f"historical_{old_arm}__current_{new_arm}"] += 1
        if old_arm != new_arm:
            changed_ids.append(activity_id)

    historical_summary = _arm_rate_summary(records, historical)
    current_summary = _arm_rate_summary(records, current_stratum)
    material_delta = {}
    for arm in STRATA:
        old_bounds = historical_summary["arms"][arm]["missingness_rate_bounds"]
        new_bounds = current_summary["arms"][arm]["missingness_rate_bounds"]
        material_delta[arm] = {
            "low_delta": new_bounds[0] - old_bounds[0],
            "high_delta": new_bounds[1] - old_bounds[1],
        }
    return {
        "status": "computed",
        "range_kind": "historical-to-current arm transport diagnostic; not a confidence interval",
        "coverage_ceiling": "none",
        "rows": len(records),
        "unique_historical_activities": len(historical),
        "transition_counts": dict(sorted(transition.items())),
        "changed_unique_activities": len(changed_ids),
        "changed_activity_ids": changed_ids,
        "missing_from_current_partition": missing_current,
        "historical_arm_rates": historical_summary,
        "current_rederived_arm_rates": current_summary,
        "material_delta_current_minus_historical": material_delta,
    }


def estimate_decline_rates(
    rater: str,
    min_cell: int,
    *,
    prior: dict[str, str] | None = None,
    current_stratum: dict[str, str] | None = None,
    arm_policy: str = "historical",
    sampling_coverage: float = 0.95,
    enforce_route: bool = False,
    minimum_rows: int = 1,
) -> dict[str, object]:
    """How often the rater declined, by stratum and by what it had said before.

    Returns LOW and HIGH rates, the evidence, and the thin-cell notes.

    Two rates rather than one because a call that never came back is not an observation of
    "did not decline". An audit found this the hard way: 292 of minimax-m3's 2,027 attempts and
    320 of glm-5.2's 1,893 produced no answer, and every one of them was silently dropped from
    the denominator. That is 14% and 17% of the experiment, discarded in a way that made the
    resulting interval narrower than the data supports — the exact failure mode of computing a
    complete-case statistic and calling it the answer.

    Nothing here can recover what those calls would have said. What it can do is refuse to
    assume. The low rate assumes no unanswered attempt would have declined, the high rate that
    every one would, and the truth is between. Where the failures are few the two bounds nearly
    coincide and the cost is nothing; where they are many the interval widens, which is the
    honest consequence of having lost that much of the experiment.
    """
    path = WM_DIR / f"UNCLEAR_{rater}.jsonl"
    if not path.exists():
        raise click.ClickException(f"{path} not found — run reask_with_unclear.py first")

    if prior is None:
        prior = {}
        for p in glob.glob(str(WM_DIR / f"{rater}__r*.jsonl")):
            with open(p, encoding="utf-8") as handle:
                for line in handle:
                    rec = json.loads(line)
                    if rec.get("mode") in MODES:
                        prior[rec["activity_id"]] = rec["mode"]

    experiment_bytes = path.read_bytes()
    records = []
    for line in experiment_bytes.decode("utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    route_receipt = (
        validate_experiment_route(records, rater, minimum_rows) if enforce_route else None
    )
    if arm_policy not in ("historical", "current"):
        raise ValueError("arm_policy must be 'historical' or 'current'")
    if arm_policy == "current" and current_stratum is None:
        raise ValueError("current arm policy requires a current stratum map")

    n = collections.Counter()  # answered
    attempted = collections.Counter()  # answered + lost
    declined = collections.Counter()
    missing_current_arm: list[str] = []
    missing_prior_label: list[str] = []
    for rec in records:
        was = prior.get(rec["activity_id"])
        if was is None:
            missing_prior_label.append(rec["activity_id"])
            continue
        arm = (
            rec.get("arm")
            if arm_policy == "historical"
            else current_stratum.get(rec["activity_id"])
        )
        if arm not in STRATA:
            missing_current_arm.append(rec["activity_id"])
            continue
        if rec.get("mode") not in MODES + ("unclear", None):
            raise ValueError(f"unexpected experiment mode {rec.get('mode')!r}")
        cell = (arm, was)
        attempted[cell] += 1
        if not rec.get("mode"):
            continue  # counted as attempted, never as "did not decline"
        n[cell] += 1
        if rec["mode"] == "unclear":
            declined[cell] += 1

    stratum_n = collections.Counter()
    stratum_att = collections.Counter()
    stratum_declined = collections.Counter()
    for (arm, was), c in attempted.items():
        stratum_att[arm] += c
        stratum_n[arm] += n[(arm, was)]
        stratum_declined[arm] += declined[(arm, was)]

    rates_low: dict[tuple[str, str], float] = {}
    rates_high: dict[tuple[str, str], float] = {}
    sampling_low: dict[tuple[str, str], float] = {}
    sampling_high: dict[tuple[str, str], float] = {}
    notes: list[str] = []
    for arm in STRATA:
        base_low, base_high = decline_rate_bounds(
            stratum_att[arm], stratum_n[arm], stratum_declined[arm]
        )
        base_sampling_low, base_sampling_high = wilson_interval(
            stratum_declined[arm], stratum_n[arm], sampling_coverage
        )
        for m in MODES:
            cell = (arm, m)
            if n[cell] >= min_cell:
                rates_low[cell], rates_high[cell] = decline_rate_bounds(
                    attempted[cell], n[cell], declined[cell]
                )
                sampling_low[cell], sampling_high[cell] = wilson_interval(
                    declined[cell], n[cell], sampling_coverage
                )
            else:
                rates_low[cell] = base_low
                rates_high[cell] = base_high
                sampling_low[cell] = base_sampling_low
                sampling_high[cell] = base_sampling_high
                notes.append(
                    f"{arm}/{m}: only {n[cell]} answered of {attempted[cell]} attempted, "
                    f"used the {arm} rate {base_low:.1%}-{base_high:.1%}"
                )
    evidence = {
        f"{arm}/{m}": {
            "attempted": attempted[(arm, m)],
            "answered": n[(arm, m)],
            "lost": attempted[(arm, m)] - n[(arm, m)],
            "declined": declined[(arm, m)],
        }
        for arm in STRATA
        for m in MODES
    }
    for arm in STRATA:
        evidence[f"{arm}/ALL"] = {
            "attempted": stratum_att[arm],
            "answered": stratum_n[arm],
            "lost": stratum_att[arm] - stratum_n[arm],
            "declined": stratum_declined[arm],
        }
    return {
        "missingness_low": rates_low,
        "missingness_high": rates_high,
        "sampling_low": sampling_low,
        "sampling_high": sampling_high,
        "evidence": evidence,
        "notes": notes,
        "sampling_coverage": sampling_coverage,
        "route_receipt": route_receipt,
        "arm_policy": arm_policy,
        "rows_excluded_for_missing_prior_label": missing_prior_label,
        "rows_excluded_for_missing_selected_arm": missing_current_arm,
        "arm_transport_audit": arm_transport_audit(records, current_stratum),
        "experiment_input": {
            "path": fws._relative(path),
            "sha256": hashlib.sha256(experiment_bytes).hexdigest(),
            "byte_length": len(experiment_bytes),
            "line_count": experiment_bytes.count(b"\n")
            + (1 if experiment_bytes and not experiment_bytes.endswith(b"\n") else 0),
        },
    }


def decline_rates(rater: str, min_cell: int) -> tuple[dict, dict, dict, list[str]]:
    """Backward-compatible missingness-bound interface used by focused tests."""
    estimate = estimate_decline_rates(rater, min_cell)
    return (
        estimate["missingness_low"],
        estimate["missingness_high"],
        estimate["evidence"],
        estimate["notes"],
    )


def load_weighting_context() -> tuple[dict[str, set[str]], dict[str, float]]:
    onet_to_group: dict[str, str] = {}
    group_share: dict[str, float] = {}
    for row in csv.DictReader((RU_DIR / "onet_to_okz2.csv").open(encoding="utf-8")):
        if row["group_share"]:
            onet_to_group[row["onet_id"]] = row["okz2"]
            group_share[row["okz2"]] = float(row["group_share"])
    conn = duckdb.connect(str(get_db_path()), read_only=True)
    pairs = conn.execute(wwm.TASK_OCCUPATION_SQL).fetchall()
    conn.close()
    mapped = wwm.mapped_tasks_by_group(pairs, onet_to_group)
    return {group: mapped[group] for group in sorted(mapped)}, dict(sorted(group_share.items()))


def deterministic_weighted_index_summary(
    tasks_by_group: dict[str, set[str]],
    counts_by_group: dict[str, dict[str, float]],
    group_share: dict[str, float],
    categories: tuple[str, ...],
) -> dict[str, object]:
    """Equivalent to the weighting helper, with canonical traversal and stable summation."""
    eligible_groups = [
        group for group in sorted(tasks_by_group) if group in group_share and tasks_by_group[group]
    ]
    mapped_employment = math.fsum(float(group_share[group]) for group in eligible_groups)
    if mapped_employment <= 0:
        raise ValueError("no mapped employment groups")

    fully_settled_groups: list[str] = []
    raw_contributions: dict[str, list[float]] = {
        category: [] for category in categories + ("unsettled",)
    }
    for group in eligible_groups:
        share = float(group_share[group])
        total = len(tasks_by_group[group])
        counts = counts_by_group.get(group, {})
        observed = math.fsum(float(counts.get(category, 0.0)) for category in categories)
        if observed > total + 1e-9:
            raise ValueError(f"{group}: {observed} observed task mass exceeds {total} mapped tasks")
        if abs(observed - total) <= 1e-9:
            fully_settled_groups.append(group)
        for category in categories:
            raw_contributions[category].append(share * float(counts.get(category, 0.0)) / total)
        raw_contributions["unsettled"].append(share * (total - observed) / total)

    raw = {
        category: math.fsum(raw_contributions[category]) for category in categories + ("unsettled",)
    }
    weighted = {
        category: raw[category] / mapped_employment for category in categories + ("unsettled",)
    }
    fully_settled_employment = math.fsum(
        float(group_share[group]) for group in fully_settled_groups
    )
    return {
        "mapped_employment_share": mapped_employment,
        "fully_settled_group_employment_share": fully_settled_employment,
        "groups_fully_settled": len(fully_settled_groups),
        "settled_statement_index_share": 1.0 - weighted["unsettled"],
        "weighted_index": weighted,
    }


def corrected_weighted_summary(
    final: dict[str, str],
    stratum: dict[str, str],
    rates_low: dict[tuple[str, str], float],
    rates_high: dict[tuple[str, str], float],
    tasks_by_group: dict[str, set[str]],
    group_share: dict[str, float],
) -> dict[str, object]:
    """Propagate one explicitly named pair of rate tables to the weighted estimand."""
    contributions: dict[str, dict[str, dict[str, list[float]]]] = {
        "low": collections.defaultdict(lambda: collections.defaultdict(list)),
        "high": collections.defaultdict(lambda: collections.defaultdict(list)),
    }
    missing_stratum = sorted(activity_id for activity_id in final if activity_id not in stratum)
    if missing_stratum:
        raise ValueError(
            f"{len(missing_stratum)} settled labels have no derived stratum; first={missing_stratum[0]}"
        )
    for group in sorted(tasks_by_group):
        for activity_id in sorted(tasks_by_group[group]):
            mode = final.get(activity_id)
            if not mode:
                continue
            arm = stratum[activity_id]
            for which, table in (("low", rates_low), ("high", rates_high)):
                probability = table[(arm, mode)]
                contributions[which][group][mode].append(1.0 - probability)
                contributions[which][group]["unknown"].append(probability)

    per_group: dict[str, dict[str, dict[str, float]]] = {"low": {}, "high": {}}
    for which in ("low", "high"):
        per_group[which] = {
            group: {
                category: math.fsum(contributions[which][group][category])
                for category in sorted(contributions[which][group])
            }
            for group in sorted(contributions[which])
        }

    summaries = {}
    weighted: dict[str, dict[str, float]] = {}
    for which in ("low", "high"):
        summaries[which] = deterministic_weighted_index_summary(
            tasks_by_group,
            per_group[which],
            group_share,
            MODES + ("unknown",),
        )
        weighted[which] = summaries[which]["weighted_index"]

    strict = [
        min(weighted[which]["screen"] for which in ("low", "high")),
        max(
            weighted[which]["screen"] + weighted[which]["unknown"] + weighted[which]["unsettled"]
            for which in ("low", "high")
        ),
    ]
    generous = [
        min(weighted[which]["screen"] + weighted[which]["mixed"] for which in ("low", "high")),
        max(
            weighted[which]["screen"]
            + weighted[which]["mixed"]
            + weighted[which]["unknown"]
            + weighted[which]["unsettled"]
            for which in ("low", "high")
        ),
    ]
    return {
        "summaries": summaries,
        "weighted_after_correction": weighted,
        "digital_share_strict": strict,
        "digital_share_generous": generous,
    }


def _range_delta(after: dict[str, object], before: dict[str, object]) -> dict[str, list[float]]:
    return {
        key: [after[key][index] - before[key][index] for index in (0, 1)]
        for key in ("digital_share_strict", "digital_share_generous")
    }


def _rate_json(table: dict[tuple[str, str], float]) -> dict[str, float]:
    return {f"{arm}/{mode}": table[(arm, mode)] for arm in STRATA for mode in MODES}


def uncertainty_component_contracts(sampling_coverage: float) -> dict[str, dict[str, object]]:
    """Names and claim ceilings shared by the JSON output and contract tests."""
    return {
        "missingness_partial_identification": {
            "range_kind": (
                "partial-identification bounds for unanswered experiment attempts; "
                "not a confidence interval"
            ),
            "coverage_ceiling": "none; no stochastic coverage claim",
        },
        "sampling_answered_attempts": {
            "method": "two-sided Wilson score interval",
            "confidence_level": sampling_coverage,
            "range_kind": (
                "sampling sensitivity envelope from marginal Wilson intervals among "
                "answered attempts; separate from missingness; not a headline confidence interval"
            ),
            "coverage_ceiling": (
                f"{sampling_coverage:.1%} marginal per fitted rate cell conditional on "
                "answered attempts and selected backoff; no simultaneous/headline coverage claim"
            ),
        },
        "directional_not_triple_rated_forced_contested": {
            "range_kind": "directional partition sensitivity; not a confidence interval",
            "coverage_ceiling": "none",
        },
    }


def verify_experiment_binding(
    snapshot: dict[str, object], rater: str, experiment_input: dict[str, object]
) -> dict[str, object]:
    matches = [
        manifest
        for manifest in snapshot.get("inputs", [])
        if manifest.get("role") == "unclear_experiment" and manifest.get("identity") == rater
    ]
    if len(matches) != 1:
        raise ValueError(
            f"snapshot must contain exactly one unclear_experiment input for {rater}; "
            f"found {len(matches)}"
        )
    manifest = matches[0]
    for field in ("sha256", "byte_length", "line_count"):
        if manifest.get(field) != experiment_input.get(field):
            raise ValueError(
                f"experiment binding mismatch for {field}: snapshot={manifest.get(field)!r} "
                f"current={experiment_input.get(field)!r}"
            )
    return {
        "snapshot_input_path": manifest["path"],
        "sha256": manifest["sha256"],
        "byte_length": manifest["byte_length"],
        "line_count": manifest["line_count"],
        "binding_verified": True,
    }


@click.command()
@click.option(
    "--rater", default="glm-5.2", show_default=True, help="Rater whose two arms were run."
)
@click.option(
    "--min-cell", default=20, show_default=True, help="Observations needed to trust a cell."
)
@click.option("--corpus-size", default=18796, show_default=True)
@click.option(
    "--state-snapshot",
    type=click.Path(path_type=Path, exists=True),
    help="Hash-bound state to correct. Live one-read state is diagnostic-only when omitted.",
)
@click.option(
    "--baseline-snapshot",
    type=click.Path(path_type=Path, exists=True),
    help="Optional baseline for deterministic transition tables and range comparison.",
)
@click.option(
    "--experiment-arm-policy",
    type=click.Choice(["historical", "current"]),
    default="historical",
    show_default=True,
    help="Historical is default; current re-partitioning requires this explicit switch.",
)
@click.option("--sampling-coverage", default=0.95, show_default=True, type=float)
@click.option(
    "--min-experiment-rows",
    default=100,
    show_default=True,
    type=int,
    help="Route guard; excludes short failed stubs from robustness claims.",
)
@click.option(
    "--write", "write_path", default=str(WM_DIR / "corrected_result.json"), show_default=True
)
def main(
    rater: str,
    min_cell: int,
    corpus_size: int,
    state_snapshot: Path | None,
    baseline_snapshot: Path | None,
    experiment_arm_policy: str,
    sampling_coverage: float,
    min_experiment_rows: int,
    write_path: str,
) -> None:
    state = load_work_mode_state(state_snapshot)
    final = state["final"]
    stratum = state["stratum"]
    n_raters = state["n_raters"]
    source = state["label_source"]
    prior = {
        activity_id: per_rater[rater]
        for activity_id, per_rater in state["readings"].items()
        if per_rater.get(rater) in MODES
    }
    try:
        estimate = estimate_decline_rates(
            rater,
            min_cell,
            prior=prior,
            current_stratum=stratum,
            arm_policy=experiment_arm_policy,
            sampling_coverage=sampling_coverage,
            enforce_route=True,
            minimum_rows=min_experiment_rows,
        )
        experiment_binding = (
            verify_experiment_binding(state["snapshot"], rater, estimate["experiment_input"])
            if state_snapshot
            else {"binding_verified": False, "reason": "no explicit state snapshot"}
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    rates_low = estimate["missingness_low"]
    rates_high = estimate["missingness_high"]
    sampling_low = estimate["sampling_low"]
    sampling_high = estimate["sampling_high"]
    evidence = estimate["evidence"]
    notes = estimate["notes"]

    click.echo(f"settled labels: {len(final)} of {corpus_size} = {len(final) / corpus_size:.1%}")
    click.echo(f"\nDECLINE RATE MEASURED ON {rater}   (low-high; the gap is lost attempts)")
    click.echo(f"{'':12s} {'screen':>16s} {'mixed':>16s} {'physical':>16s}")
    for arm in STRATA:
        cells = "  ".join(f"{rates_low[(arm, m)]:6.1%}-{rates_high[(arm, m)]:<6.1%}" for m in MODES)
        ev = evidence[f"{arm}/ALL"]
        click.echo(
            f"{arm:12s} {cells}\n{'':12s} attempted {ev['attempted']}, answered "
            f"{ev['answered']}, LOST {ev['lost']}, declined {ev['declined']}"
        )
    lost = sum(evidence[f"{a}/ALL"]["lost"] for a in STRATA)
    att = sum(evidence[f"{a}/ALL"]["attempted"] for a in STRATA)
    if att and lost / att > 0.05:
        click.echo(
            f"  {lost} of {att} attempts ({lost / att:.1%}) never came back. They are carried as "
            f"the width\n  between the two rates, not discarded: a call that failed is not a "
            f"rater who declined to decline."
        )
    for note in notes:
        click.echo(f"  thin cell — {note}")
    if evidence["control/ALL"]["answered"] < 100:
        click.echo(
            "  WARNING: the control arm is small. It is what proves the option is not simply "
            "tempting, so the correction is provisional until it grows."
        )

    tasks_by_group, group_share = load_weighting_context()
    try:
        missingness_result = corrected_weighted_summary(
            final, stratum, rates_low, rates_high, tasks_by_group, group_share
        )
        sampling_result = corrected_weighted_summary(
            final, stratum, sampling_low, sampling_high, tasks_by_group, group_share
        )
        alternate_arm_policy = "current" if experiment_arm_policy == "historical" else "historical"
        alternate_estimate = estimate_decline_rates(
            rater,
            min_cell,
            prior=prior,
            current_stratum=stratum,
            arm_policy=alternate_arm_policy,
            sampling_coverage=sampling_coverage,
        )
        if (
            alternate_estimate["experiment_input"]["sha256"]
            != estimate["experiment_input"]["sha256"]
        ):
            raise ValueError("experiment input changed between historical/current arm audits")
        alternate_result = corrected_weighted_summary(
            final,
            stratum,
            alternate_estimate["missingness_low"],
            alternate_estimate["missingness_high"],
            tasks_by_group,
            group_share,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    summaries = missingness_result["summaries"]
    weighted = missingness_result["weighted_after_correction"]

    click.echo(
        f"\nmapped groups {len(tasks_by_group)} of {len(group_share)}, "
        f"employment mapping {summaries['low']['mapped_employment_share']:.1%}"
    )
    click.echo(
        f"fully settled groups {summaries['low']['groups_fully_settled']} of "
        f"{len(tasks_by_group)}, carrying "
        f"{summaries['low']['fully_settled_group_employment_share']:.1%} of employment"
    )
    click.echo(
        "settled share of the employment-weighted statement index "
        f"{summaries['low']['settled_statement_index_share']:.1%}"
    )
    click.echo(
        "\nWEIGHTED BY RUSSIAN EMPLOYMENT, AFTER THE CORRECTION\n"
        "  columns are the two ways the lost attempts could have gone: 'none declined' first,\n"
        "  'all declined' second. More declining means more unknown and less of everything else."
    )
    for m in MODES + ("unknown", "unsettled"):
        click.echo(
            f"  {m:9s} none-declined {weighted['low'][m]:6.1%}   all-declined {weighted['high'][m]:6.1%}"
        )

    strict_low, strict_high = missingness_result["digital_share_strict"]
    gen_low, gen_high = missingness_result["digital_share_generous"]
    click.echo("\nDIGITAL SHARE OF THE EMPLOYMENT-WEIGHTED STATEMENT INDEX")
    click.echo(f"  strict   (screen only)     {strict_low:5.1%} – {strict_high:5.1%}")
    click.echo(f"  generous (screen + mixed)  {gen_low:5.1%} – {gen_high:5.1%}")
    click.echo(
        "  The low end assigns neither unknown nor unsettled mass to screen work; the high end "
        "assigns both.\n  Neither is a selected point. This is a sensitivity range conditional "
        "on the fitted decline rates, not a confidence interval."
    )

    forced_stratum = dict(stratum)
    not_triple = {activity_id for activity_id, count in n_raters.items() if count < 3}
    changed_to_contested = {
        activity_id
        for activity_id in not_triple
        if activity_id in forced_stratum and forced_stratum[activity_id] != "contested"
    }
    for activity_id in not_triple:
        if activity_id in forced_stratum:
            forced_stratum[activity_id] = "contested"
    directional_result = corrected_weighted_summary(
        final, forced_stratum, rates_low, rates_high, tasks_by_group, group_share
    )
    component_contracts = uncertainty_component_contracts(sampling_coverage)
    policy_results = {
        experiment_arm_policy: missingness_result,
        alternate_arm_policy: alternate_result,
    }
    arm_transport_component = dict(estimate["arm_transport_audit"])
    arm_transport_component["employment_weighted_material_effect"] = {
        "historical_arm_policy": {
            "digital_share_strict": policy_results["historical"]["digital_share_strict"],
            "digital_share_generous": policy_results["historical"]["digital_share_generous"],
        },
        "current_rederived_arm_policy": {
            "digital_share_strict": policy_results["current"]["digital_share_strict"],
            "digital_share_generous": policy_results["current"]["digital_share_generous"],
        },
        "delta_current_minus_historical": _range_delta(
            policy_results["current"], policy_results["historical"]
        ),
    }

    transition = None
    if baseline_snapshot:
        baseline = fws.load_snapshot(baseline_snapshot)
        baseline_state = _snapshot_state(baseline)
        transition = fws.transition_audit(baseline, state["snapshot"])
        baseline_range = corrected_weighted_summary(
            baseline_state["final"],
            baseline_state["stratum"],
            rates_low,
            rates_high,
            tasks_by_group,
            group_share,
        )
        transition["range_under_each"]["baseline"]["employment_weighted_partial_identification"] = {
            "digital_share_strict": baseline_range["digital_share_strict"],
            "digital_share_generous": baseline_range["digital_share_generous"],
        }
        transition["range_under_each"]["final"]["employment_weighted_partial_identification"] = {
            "digital_share_strict": missingness_result["digital_share_strict"],
            "digital_share_generous": missingness_result["digital_share_generous"],
        }
        transition.pop("audit_payload_sha256", None)
        transition["audit_payload_sha256"] = fws.payload_sha256(transition)

    result = {
        "schema": CORRECTED_SCHEMA,
        "rater_of_the_experiment": rater,
        "settled_labels": len(final),
        "corpus_size": corpus_size,
        "label_source": source,
        "state_snapshot_payload_sha256": state["snapshot"]["snapshot_payload_sha256"],
        "state_snapshot_status": state["snapshot"]["snapshot_status"],
        "experiment_input_binding": experiment_binding,
        "route_receipt": estimate["route_receipt"],
        "experiment_arm_policy": experiment_arm_policy,
        "experiment_rows_excluded_for_missing_prior_label": estimate[
            "rows_excluded_for_missing_prior_label"
        ],
        "experiment_rows_excluded_for_missing_selected_arm": estimate[
            "rows_excluded_for_missing_selected_arm"
        ],
        "decline_rates_low": _rate_json(rates_low),
        "decline_rates_high": _rate_json(rates_high),
        "decline_evidence": evidence,
        "thin_cells_backed_off": notes,
        "employment_mapping_share": summaries["low"]["mapped_employment_share"],
        "groups_fully_settled": summaries["low"]["groups_fully_settled"],
        "fully_settled_group_employment_share": summaries["low"][
            "fully_settled_group_employment_share"
        ],
        "settled_statement_index_share": summaries["low"]["settled_statement_index_share"],
        "weighted_after_correction": weighted,
        "lost_attempts": {arm: evidence[f"{arm}/ALL"]["lost"] for arm in STRATA},
        "digital_share_strict": [strict_low, strict_high],
        "digital_share_generous": [gen_low, gen_high],
        "range_kind": (
            "partial-identification sensitivity range under missing-attempt extrema and "
            "unsettled-label extrema; not a confidence interval"
        ),
        "coverage_ceiling": "none; deterministic extrema conditional on inputs and mapping",
        "components": {
            "missingness_partial_identification": {
                **component_contracts["missingness_partial_identification"],
                "decline_rates_low": _rate_json(rates_low),
                "decline_rates_high": _rate_json(rates_high),
                "digital_share_strict": missingness_result["digital_share_strict"],
                "digital_share_generous": missingness_result["digital_share_generous"],
            },
            "sampling_answered_attempts": {
                **component_contracts["sampling_answered_attempts"],
                "decline_rate_low": _rate_json(sampling_low),
                "decline_rate_high": _rate_json(sampling_high),
                "digital_share_strict": sampling_result["digital_share_strict"],
                "digital_share_generous": sampling_result["digital_share_generous"],
            },
            "directional_not_triple_rated_forced_contested": {
                **component_contracts["directional_not_triple_rated_forced_contested"],
                "assumption": "every activity with fewer than three successful bulk raters is contested",
                "all_not_triple_rated_activities": len(not_triple),
                "settled_not_triple_rated_activities": len(not_triple & set(final)),
                "activities_changed_to_contested": len(changed_to_contested),
                "base": {
                    "digital_share_strict": missingness_result["digital_share_strict"],
                    "digital_share_generous": missingness_result["digital_share_generous"],
                },
                "forced_contested": {
                    "digital_share_strict": directional_result["digital_share_strict"],
                    "digital_share_generous": directional_result["digital_share_generous"],
                },
                "impact_forced_minus_base": _range_delta(directional_result, missingness_result),
            },
            "arm_transport": arm_transport_component,
        },
        "transition_audit": transition,
        "uncertainty_not_included": [
            "sampling uncertainty of decline-rate estimates",
            "transport from the current to the final contested/control partition",
        ],
        "component_separation": (
            "sampling and arm transport are reported beside, not fused into, the top-level "
            "partial-identification range"
        ),
        "caveat": (
            "The top-level range retains unknown outcomes of lost attempts and unsettled corpus "
            "labels. Sampling and arm transport have separate ceilings; none upgrades this to a CI."
        ),
        "incomplete": weighted["low"]["unsettled"] > 0,
    }
    result["result_payload_sha256"] = fws.payload_sha256(result)
    fws.atomic_write_json(Path(write_path), result)
    click.echo(f"\nwritten {write_path}")


if __name__ == "__main__":
    main()
