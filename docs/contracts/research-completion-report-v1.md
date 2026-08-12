---
creator: codex
purpose: Contract for the generated AllJobs research-completion report.
why: Keep the final narrative bound to current machine-readable evidence and fail closed while the study is incomplete.
version: 2026-08-12.2
updated: 2026-08-12
---

# Research completion report v1

## Owner and compatibility

`workforce-graph/scripts/build_research_completion_report.py` owns the contract
`alljobs.research-completion-report/v1` and the generated Markdown bytes. The report supersedes
the two dated 2026-08-08 reports as the current synthesis; those files remain immutable historical
records. A change to an input schema, a gate below, a published number, or a claim ceiling requires
a new contract version and synchronized producer, consumer, fixture, and documentation changes.
`workforce-graph/scripts/freeze_work_mode_snapshot.py` is the upstream snapshot producer: a
collection-complete assertion must pass the same exact corpus, input-receipt and per-activity gates
before any new frozen path is written. The ordinary `complete` path requires 18,796 successful
readings. The only narrower alternative is `complete_with_explicit_nonresponse`: exactly one
named activity may lack a label when the frozen raw input proves at least five cache-busted records
and 20 unique exact-route attempt receipts. That activity is forced to remain `unsettled`; agreement
by the other two raters is never imputed as the missing label. Both paths require a hash-valid
baseline, bind its payload hash, require an identical activity-ID inventory, and refuse to replace
an existing snapshot.
Snapshot publication is atomic no-replace: an identical competitor converges as `unchanged`; a
non-identical or vanished competitor fails loud and no competing byte is overwritten.

## Required inputs

The generator accepts explicit paths and records a SHA-256 and byte count for each:

1. the frozen baseline and final `alljobs.work-mode-snapshot/v1` files;
2. `alljobs.work-mode-corrected-result/v1`, computed from that final snapshot and baseline;
3. `alljobs.layer-two-freeze.v1`;
4. evidence registry `evidence/1`;
5. RLI authority `alljobs.rli.ordered-tsv-canonical.v1`;
6. HH witness `alljobs.content27.hh-logical-slice.v1`;
7. the dated computer-use evidence audit.

Numbers are read from JSON only. The Markdown audit contributes a bound file receipt and citation,
not parsed numeric authority.

## Research-complete gates

Generation is fail-closed. Every gate must pass:

- both snapshots have valid embedded payload hashes and exactly 18,796 identical activity IDs;
- the final snapshot embeds the baseline payload hash used as its inventory authority;
- the final snapshot names `gemini-3.5-flash-lite` as third rater and declares its collection
  complete. It either contains 18,796 unique successful labels, or 18,795 plus exactly one
  hash-bound explicit nonresponse under the narrow receipt contract above;
- the set of activities without a successful third-rater reading exactly equals the declared
  nonresponse set. Its member has `label: null`, source `third_rater_explicit_nonresponse` and
  settlement `unsettled`; the receipt proves no valid label after the exact-route attempts and
  five terminal `None` outcomes, but does not infer other per-attempt content or provider cause;
- corrected-result has a valid embedded payload hash and binds the final snapshot hash; the
  transition audit binds both snapshot hashes, and no activity is added or removed;
- its corpus and settlement denominators reproduce the final snapshot; the headline endpoints
  reproduce from the weighted extrema and match the missingness, directional-base and selected-arm
  components; Wilson sampling remains separate; all four uncertainty components are complete;
- an unresolved share is allowed only as an explicit partial-identification sensitivity range that
  says it is not a confidence interval. `incomplete: true` is therefore not itself a failed gate;
- the experiment input binding and requested-route guard pass;
- layer two keeps both current outcomes, all reported-number checks pass, and
  `claim_ceiling.primary_outcome` remains `not_selected`;
- the tool-access mismatch, missing historical prompt bytes, absent predictor backend receipts,
  redacted-arm `HOLD`, and worked-example literal overlap remain visible;
- the evidence registry has zero edges authorising an AllJobs bound;
- RLI remains an exact 15-row canonical recovery without raw-page authority;
- HH remains a current-recovery-database logical witness for exact accepted-projection replay and
  explicitly does not establish historical relation-row identity or recover the lost DuckDB bytes.

The generator must report all failed gates and must not create or replace an output file on `HOLD`.

## Output and claim ceilings

The one Markdown report contains the input receipt table, exact reproduction commands, denominators,
exclusions, missingness, both layer-two outcomes, external-transfer status, authority limits, and a
separate publication status. It may say the study is research-complete with partial identification.
It must not turn model agreement into task truth, the partial-identification range into a confidence
interval, deterministic conformance into mission success, or the external evidence registry into an
AllJobs capability bound.

Research completion never grants publication completion. Licence, third-party redistribution,
absolute-path, remote, and working-record decisions remain governed by `PUBLICATION-READINESS.md`.

Writes are deterministic, UTF-8, newline-terminated, atomic, and no-replace. `--check` compares exact
bytes; `--preflight` performs every gate without writing.
