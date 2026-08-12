---
creator: codex
purpose: Re-audit the external computer-use evidence after the a16z article and OSWorld 2.0 release.
why: The existing seven-anchor inventory said no source published item-level results; OSWorld 2.0 makes that statement stale without automatically authorising a corpus-task claim.
version: 1
updated: 2026-08-11
---

# Computer-use evidence update

## Decision boundary

This update answers two questions only:

1. Does the a16z article supply evidence that can validate the AllJobs task-vote index?
2. Does any newly available primary benchmark change the external-evidence registry or the
   transfer gate?

It does not estimate a share of work, endorse a vendor, or approve a transfer edge. Sources were
accessed on 2026-08-11. The historical seven-source audit remains unchanged; this file is its
additive successor.

## Source audit

| Source claim | Evidence tier | Audit result | AllJobs consequence |
|---|---|---|---|
| OSWorld-Verified rose from 42% to 85%, above the old 72.36% human baseline | `BENCHMARK`, but reported through a secondary leaderboard | `QUALIFY`. The score is for short OSWorld 1.0 desktop tasks and a model-plus-harness configuration, not 85 of every 100 business processes. The human comparison is the original study's participant result, not a production reliability threshold. | Context only. Do not use it as a task share, production success rate, or evidence that computer use is solved. |
| Narrow computer-use workflows are running in production at high volume | `HISTORICAL` self-report | `QUALIFY`. The article gives several anonymous cases, but no interview count, sampling frame, workflow-level denominator, failure distribution, raw outcomes, or independent verification. | Useful roadmap signal for failure handling and observability; not admissible outcome evidence. |
| Computer-use inference costs roughly $6-8 per agent-hour | `INFERRED` | `QUALIFY`. The article says the figure begins with a founder estimate and is cross-checked against token-cost and labour-cost sources. It is an order-of-magnitude scenario, not a measured market price or AllJobs unit-cost input. | Do not enter the evidence registry or economic headline. |
| Protocol-following work with immediate machine-observable success, tolerable failure consequences, and explicit escalation is the current deployment contour | `INFERRED` synthesis of interviews | `SUPPORTED` as a design heuristic, not as a population fact. | Consistent with the existing mission design and with retaining verification, escalation, and substitution guards. No new feature is licensed by it. |
| OSWorld 2.0 tests 108 long-horizon workflows and publishes task trajectories | `BENCHMARK` primary source | `SUPPORTED`. arXiv v2 reports the exact model/harness table; the project publishes the environment, tasks, release manifests, and downloadable per-task trajectories. | Add an item-level benchmark profile. Remove the claim that no examined source publishes item-level results. |
| The best reported 500-step OSWorld 2.0 configuration completes 20.6% strictly and earns 54.8% partial reward | `BENCHMARK` primary source | `SUPPORTED` for Claude Opus 4.8 with maximum thinking and batched actions on release `v2026.06.24`. The paper publishes no uncertainty interval. Model-based evaluation contributes 11.53% of the score and some tasks include a bounded simulated user. | Record the full system contour and qualifiers. Do not compare it numerically with AllJobs deterministic conformance. |

## Primary-source facts admitted

- Paper: [OSWorld 2.0, arXiv v2](https://arxiv.org/abs/2606.29537v2), revised
  2026-07-13. It defines 108 tasks, a median skilled-human duration near 1.6 hours, a 500-step
  primary evaluation, and the 20.6% binary / 54.8% partial result for the named top
  configuration.
- Reproducibility surface: [OSWorld-V2 repository](https://github.com/xlang-ai/OSWorld-V2).
  The paper's runs use release `v2026.06.24`; `v2026.08.08` is a later active release and must
  not be silently substituted when quoting the paper result.
- Item-level publication: [trajectory dataset](https://huggingface.co/datasets/xlangai/osworld2.0-trajectory).
  It exposes per-model, per-task trajectories and checkpoint-result files. This clears the
  source-granularity objection only.
- Secondary source reviewed: [a16z, “Can Agents Use a Computer Yet? We've Got the Data”](https://a16z.com/can-agents-use-a-computer-yet-weve-got-the-data/),
  published 2026-08-10. It is retained as market context, not as a benchmark record.

## Transfer decision

`NO_CHANGE` to the gate. OSWorld 2.0 publishes task-level outcomes, but none of its workflows
has been reviewed against an AllJobs task's mandatory components, channel, permissions,
environment, or failure semantics. No `TransferEdge` is created by this update, so the number of
edges authorising a bound remains zero.

The safe current wording is:

> One of eight examined benchmarks publishes item-level results. None yet has a reviewed,
> source-backed transfer edge that authorises a number for an AllJobs corpus task.

## Roadmap disposition

- `ADD`: OSWorld 2.0 profile and named paper result to the evidence registry.
- `DROP`: the stale no-item-level-source sentence.
- `NO_CHANGE`: finish the third work-mode rater; close the remaining audit defects;
  defer the consolidated report until recomputation on full triples.
- `WATCH`: whether a future reviewed OSWorld 2.0 workflow matches a mandatory-component set in
  the AllJobs graph. The cheapest valid next test is one explicit mapping review, not a bulk
  semantic join.
