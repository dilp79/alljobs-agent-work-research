---
creator: codex
purpose: Fail-closed contract for the powered harder-mission predictive-validity successor.
why: Separate a frozen vote predictor from a new tool-using deterministic outcome without turning synthetic conformance into mission success.
version: 1
updated: 2026-08-12
---

# Predictive-validity successor v1

## Authority and frozen frame

`workforce-graph/data/predictive_validity/successor_2026-08-12/frame.json` is the immutable
preregistration. It binds the prior layer-two freeze, semantic operator/profile sources, current
completion report, frame builder, runner, analyzer, exact OpenRouter catalog and endpoint receipts,
base repository commit, every predictor dose, every transformed input, every expected-output hash,
and every selection/analysis rule.

The frame contains 20 pilot cases and 70 main cases. Pilot uses one development mission per each of
ten categories under two transformations. Main uses seven distinct, complete-vote missions per
category; each mission appears once. Repeated transformed variants are not counted as independent
main observations.

## Competence and difficulty gate

Every case starts from a typed semantic operator. `semantic_shift` changes a decisive input fact.
`dense_semantic_shift` adds deterministic local distractors or work while preserving the declared
operator semantics. Before selection, the separately implemented domain checker must accept the
new derived output and reject the stale pre-shift output. Failed transformations are recorded by
name and cannot enter the frame.

This checker establishes deterministic conformance only. It does not execute the required human
holistic rubric and therefore cannot establish mission success.

## Exact model and harness

The only allowed route is `google/gemini-3.5-flash-lite` through OpenRouter, pinned to provider
`Google AI Studio` with fallback disabled. Both response objects must report that exact model and
provider. Any HTTP, model, or provider drift is not an outcome and blocks finalization.

The agent sees the case only after exactly one `read_case` function call. The tool is local and
read-only; no network, write, approval, communication, publication, or physical-action tool exists.
A missing/malformed tool call and an unparseable final JSON object are agent conformance failures.
Transport failures are not.

The maximum planned spend is 150 case runs and 300 requests: 20 cases under four pilot scaffolds,
then 70 main cases only if the pilot gate passes. Prices are frozen at $0.30/M input tokens and
$2.50/M output tokens. The hard estimated-cost ceiling is $2.25. There are no automatic retries.

## Pilot rule

The four schema-guidance doses are, from least to most revealing: field names, top-level types,
partial recursive shape, and full recursive shape. They contain no case or answer values. Each is
run on the same 20 pilot cases.

A scaffold is eligible only with 4–8 failures (20–40%). Select the eligible scaffold closest to six
failures; ties prefer the less revealing scaffold. If none qualifies, freeze
`HOLD_INSTRUMENT_RANGE_MISS` and make no main calls. Main results never tune the scaffold.

## Main analysis

The main instrument must again produce 14–28 failures among 70 independent missions. Outside that
range, stop without fitting the predictive comparison.

Inside the range, compare:

- difficulty-only: category plus the preregistered scalar difficulty index; and
- augmented: the same terms plus `can_do`, `no_human_review`, and `requires_tool_access` frozen vote
  doses.

Both use ridge penalty 2.0 and deterministic five-fold held-out log loss. The primary statistic is
difficulty-only minus augmented log loss. Its one-sided p-value uses 1,999 joint vote-vector
permutations within category. Report an incremental predictive association only if log loss
improves and `p <= 0.05`.

Seventy independent mission clusters give approximate 80% Wald power only for a large residual
standardized predictor odds ratio of at least 2.2 at 30% failures. Smaller signals remain
underpowered. The blocked permutation is the primary inferential check.

## Claim ceiling

An association, if detected, concerns frozen model-vote doses predicting deterministic conformance
in one exact synthetic read-only tool harness under one model route. It is not causal, GUI/OSWorld
computer use, human-validated mission success, workforce share, or production reliability.

