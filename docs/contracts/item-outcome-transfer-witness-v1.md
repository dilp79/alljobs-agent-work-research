---
creator: codex
purpose: Contract for exact benchmark-item receipts and admitted transfer witnesses.
why: Prevent aggregate, failed, detached, or caller-invented outcomes from authorising AllJobs task bounds.
version: 1
updated: 2026-08-12
---

# Item-outcome transfer witness v1

## Authority and consumers

`workforce-graph/src/workforce_graph/evidence/gate.py` owns
`evidence/item-outcome-receipt/1`. Its consumers are `admit()`, `status_for_task()`, and
`bound_for_task()`. The persisted `evidence/1` registry is an upstream source inventory, not an
item-outcome receipt and not a migration target.

## Required receipt fields

| Field | Invariant |
|---|---|
| `schema_version` | exactly `evidence/item-outcome-receipt/1` |
| `result_id` | non-empty and exactly equal to the `BenchmarkResult.id` presented to the gate |
| `item_id` | non-empty exact benchmark workflow or item identifier |
| `outcome` | typed `passed`, `failed`, `partial`, or `unknown` |
| `demonstrated_level` | non-negative integer only when outcome is `passed`; otherwise null |
| `success_criterion` | non-empty and exactly equal to the benchmark profile criterion |
| `source_release` | non-empty and exactly equal to the benchmark profile version |
| `transfer_edge_sha256` | lowercase 64-hex SHA-256 of the exact canonical reviewed edge |
| `item_spec_sha256` | lowercase 64-hex SHA-256 of the exact item specification |
| `outcome_record_sha256` | lowercase 64-hex SHA-256 of the exact item outcome record |
| `source_bundle_sha256` | lowercase 64-hex SHA-256 of the pinned release/source bundle receipt |

## Admission rules

A bound-authorising edge has scope `whole_task` or `component_only`. Admission succeeds only when:

- edge, result, and profile identities join exactly;
- the edge is reviewed `eligible`, has no unknowns, matches the independently required task
  channel, and does not concern physical work;
- whole-task scope covers every mandatory component;
- profile and result both publish item-level evidence and the profile defines an absolute success
  threshold;
- a structurally valid receipt is present, joins to the result, release, and criterion, and records
  `passed`; and
- its canonical transfer-edge digest equals the edge presented to the gate, so a passed item
  receipt cannot be detached and reused for a different task, scope, rationale, or review state.

Contextual edges may remain in source inventories but `admit()` never mints a witness from one.
Subfamily and suite-aggregate results cannot authorise an individual task or component.

## Witness and routing rules

The normal `Witness` constructor is factory-closed; `admit()` mints it after all gates pass. Its
level is a property of the passing receipt. `status_for_task()` accepts whole-task witnesses only
in the whole-task list and component-only witnesses with a component identifier only in the
component list. Both `status_for_task()` and `bound_for_task()` require an explicit task ID and
reject a witness admitted for another task. `bound_for_task()` returns the maximum demonstrated
lower-frontier level and has no upper-bound counterpart.

These are evidence integrity controls, not a security boundary against hostile Python code. They
make accidental bypass fail loud and give tests a precise contract.

## Change protocol

A new field, outcome state, hash rule, or admission rule requires a successor schema and synchronized
producer, consumer, tests, decision record, and review protocol. Existing frozen current-study files
must remain byte-identical. A persisted successor receipt must be written to a new dated path and
bind the base registry SHA-256 and repository commit in its enclosing review artifact.
