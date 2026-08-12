---
creator: codex
purpose: Contract for the first executed OSWorld 2.0 to AllJobs successor review.
why: Preserve a useful blocked review without promoting a public false-positive score or lexical similarity into a workforce bound.
version: 1
updated: 2026-08-12
---

# OSWorld transfer review v1

## Frozen instance

The sole artifact is
`workforce-graph/data/evidence/successors/osworld-v2-2026.06.24/010__23d778e73061800ae3732b1f34a750c5/review.json`.
It binds OSWorld code tag `v2026.06.24` at commit
`2b9b7b4eb73243d557bdbf2998fe18d8e18e19c6`, gated task-repository commit
`e7996f4cc850be108e510bd8433c63ee7b8303dd`, public trajectory-file commit
`458824aec9f07ffbe504f3b9306d941695387b00`, workflow `010`, and AllJobs activity
`23d778e73061800ae3732b1f34a750c5`.

The workflow was selected before the AllJobs candidate because it had a public complete demo
trajectory and a binary final result. The AllJobs match is a candidate review, not an admitted
semantic equivalence.

## Decision derivation

`build_osworld_transfer_successor.py` owns the decision. Callers cannot supply coverage, outcome,
scope, admission status, or demonstrated level. The builder emits only
`HOLD_SOURCE_OR_AUTHORITY_GAP`, a contextual unresolved edge, and a null
`item_outcome_receipt` under this schema.

The hold is required because:

- the exact gated task class, task-hash manifest, and pinned task assets were unavailable to the
  unauthenticated acquisition;
- the public trajectory reports 1.0 but its own analysis identifies a wrong required budget code
  and an evaluator that does not check the decisive DOCX table cells;
- the broad AllJobs statement uses illustrative examples and has no independent authority for
  channel, permissions, failure semantics, or mandatory components; and
- the public trajectory dataset declares no redistribution licence, so only retrieval receipts are
  tracked.

This is not a finding that the model cannot perform the workflow or activity. It does not change
the frozen current-study registry, corrected estimate, or completion report.

## Input and publication rules

External files stay in a temporary acquisition directory. The tracked artifact retains each
logical filename, exact source locator, byte count, and SHA-256. It does not redistribute the
trajectory bytes. Local inputs are path/hash bound, including the activity corpus, Workbank O*NET
extract, final work-mode model judgments, external audit, and zero-bound evidence registry.

`freeze` publishes atomically with no-replace semantics. A byte-identical concurrent result is
accepted as unchanged; a non-identical file is never replaced. `check` verifies the embedded
payload hash and every local base receipt. If the gated task returns HTTP 200 or the public result
changes, the builder fails and a successor contract is required.

## Reproduction

Reacquire the source locators recorded in `source_pack.source_receipts` into a fresh directory using
their recorded logical filenames. For `code-revision.txt`, record the exact output of
`git rev-parse HEAD` after checking out the recorded code commit. Preserve the full HTTP response
headers for the gated task-class request as `task-class-http-status.txt`.

Then generate to a fresh path and compare; do not overwrite the frozen artifact:

```bash
replay_dir=$(mktemp -d)
workforce-graph/.venv/bin/python \
  workforce-graph/scripts/build_osworld_transfer_successor.py freeze \
  --source-root SOURCE_ROOT \
  --base-commit 8a7274fe74451e6b6875b07a80afb33e62837c52 \
  --output "$replay_dir/review.json"
cmp "$replay_dir/review.json" \
  workforce-graph/data/evidence/successors/osworld-v2-2026.06.24/010__23d778e73061800ae3732b1f34a750c5/review.json
workforce-graph/.venv/bin/python \
  workforce-graph/scripts/build_osworld_transfer_successor.py check
```

The source URLs may later return changed bytes. A mismatch is source drift, not permission to
regenerate the frozen artifact.

