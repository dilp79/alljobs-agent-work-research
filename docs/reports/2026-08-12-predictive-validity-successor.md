---
schema: alljobs.predictive-validity-successor-report/v1
report_date: 2026-08-12
successor_status: NO_DETECTED_INCREMENTAL_ASSOCIATION
current_study_status: RESEARCH_COMPLETE_WITH_PARTIAL_IDENTIFICATION
publication_status: HOLD_SEPARATE_GATE_NOT_CLEARED
---

# Powered predictive-validity successor

**Result: `NO_DETECTED_INCREMENTAL_ASSOCIATION` in one exact synthetic read-only tool harness.**

This successor does not change the frozen current-study status or headline numbers. It tests the
narrow question the original three semantic failures could not support: whether the three frozen
model-vote doses improve held-out prediction of new deterministic-conformance outcomes after
category and preregistered difficulty are included.

## Design that actually ran

- exact route: `google/gemini-3.5-flash-lite` through OpenRouter to `Google AI Studio`, fallback
  disabled and verified on every response;
- exact harness: one required local read-only `read_case` tool call, then one JSON deliverable;
- outcome: the independent typed domain checker, which is necessary deterministic conformance and
  not the suite's unperformed human holistic review;
- frame: 70 independent main missions, seven per each of ten categories, all with complete frozen
  vote joins;
- scaffold: one different, category-matched checker-approved worked example, selected by the frozen
  pilot rule; and
- analysis: five-fold held-out ridge-logistic log loss, comparing category plus difficulty against
  the same model plus `can_do`, `no_human_review`, and `requires_tool_access`; 1,999 joint
  vote-vector permutations within category.

The worked example conveys reusable semantics and serialization. The result is therefore about the
agent-plus-scaffold configuration, not isolated model capability or a format-only effect.

## Gates and outcomes

The schema-only V2 pilot failed its instrument gate: all 20 cases failed under each of four shape
doses. It made no V2 main calls. V3 kept every target case/input hash/vote vector unchanged and added
independent category-matched worked examples.

V3 pilot results:

| Scaffold | Pass | Fail | Decision |
|---|---:|---:|---|
| worked example | 15 | 5 | selected by tie-break |
| worked example + recursive shape | 15 | 5 | eligible, not selected |

The selected main run returned 44 passes and 26 failures. This is inside the preregistered 14–28
failure contour.

| Category | Pass | Fail |
|---|---:|---:|
| data reconciliation | 0 | 7 |
| draft generation | 6 | 1 |
| escalation preparation | 7 | 0 |
| exception handling | 7 | 0 |
| follow-up scheduling | 3 | 4 |
| information retrieval | 7 | 0 |
| intake classification | 6 | 1 |
| policy interpretation | 7 | 0 |
| quality verification | 1 | 6 |
| record preparation | 0 | 7 |

Only four categories contain both outcomes. The preregistered overall failure target passed, but
this concentration reduces realized within-category sensitivity below the approximate pre-study
large-effect power contour.

## Predictive comparison

| Metric | Difficulty-only | Difficulty + votes |
|---|---:|---:|
| Five-fold held-out log loss | 0.436257 | 0.519719 |

The preregistered improvement statistic is difficulty-only minus augmented log loss. It was
**−0.083462**: adding votes made held-out prediction worse. In 1,999 blocked permutations, 1,952
null improvements were at least as large; one-sided `p = 0.9765`.

Therefore the successor did not detect incremental predictive value from the three vote doses in
this configuration. This is not proof that no relationship exists. It does rule out promoting the
current vote index as validated by this harder synthetic agent outcome.

## Spend and request accounting

Successful exact-route V2/V3 work used:

| Phase | Responses | Input tokens | Output tokens | Estimated catalog-price cost |
|---|---:|---:|---:|---:|
| V2 schema-only pilot | 160 | 75,608 | 11,746 | $0.0520474 |
| V3 worked-example pilot | 80 | 96,428 | 5,158 | $0.0418234 |
| V3 main | 140 | 173,287 | 13,567 | $0.0859036 |
| **Total observed model responses** | **380** | **345,323** | **30,471** | **$0.1797744** |

An earlier V1 direct-endpoint attempt produced 80 HTTP 401 receipts before any model response.
Those attempts have zero observed outcomes; token use and cost are not asserted.

## Frozen authority

| Artifact | Payload SHA-256 |
|---|---|
| V3 frame | `10e4864476c5ef7700961f4b7f0258040bd6573956fb8d39eb053700e3b1d76e` |
| V3 pilot | `8166cfac37d0f9190ec3c8a6a39f8be65f276a73e039532f1f61b62448612f26` |
| V3 main | `e6260496b2afd33917a6adb0b383580e067e5bb93ae5f84d7d5cf94f256d1dfa` |
| V3 analysis | `63055d4377a3a9b5cbac3c6ff348b21ea0360f51cbf4d2725a293d6d56dd476d` |

Reproduction from the retained local raw trial logs under
`workforce-graph/data/predictive_validity/raw/` is fail-closed and no-replace. The raw logs are
intentionally ignored and are not part of the redistributed evidence artifact:

```bash
workforce-graph/.venv/bin/python workforce-graph/scripts/run_predictive_validity_successor.py freeze-pilot
workforce-graph/.venv/bin/python workforce-graph/scripts/run_predictive_validity_successor.py freeze-main
workforce-graph/.venv/bin/python workforce-graph/scripts/analyze_predictive_validity_successor.py
```

Each command must report `unchanged`. Frozen current-study evidence remains byte-identical.

## Claim ceiling

Allowed: the three frozen model-vote doses did not improve held-out prediction of deterministic
conformance in this exact category-balanced synthetic read-only tool harness under this exact model
route and worked-example scaffold.

Not allowed: no association exists; the vote models are inaccurate; Gemini cannot perform these
activities; benchmark failure is an upper capability bound; the result estimates workforce share,
mission success, GUI computer use, or production reliability.
