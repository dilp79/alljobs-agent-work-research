---
creator: codex
purpose: Fail-closed contract for the clean public AllJobs research release.
why: Publish the reproducible research surface without private laboratory records, local paths or unlicensed raw data.
version: 5
updated: 2026-09-06
owner: founder-dilp79
compatibility: additive clean release; private source history and frozen research artifacts unchanged
---

# Public release contract v1

## Authority and boundary

The private source repository remains authoritative for full research history. A clean public
repository is derived only by `workforce-graph/scripts/build_public_release.py` from an exact
committed source revision. The public tree has a new history and does not rewrite or replace the
private repository.

The public release contains:

- Apache-2.0-licensed original code and reader documentation;
- the three final 2026-08-12 reports and their current contracts/audits;
- the 2026-09-06 supplementary research note, original sufficient-statistic inputs, derived
  trial outcomes, analytical tables and three original figures, with its offline replay script;
- the ATE appendix, original fetch/audit code and tests, descriptive aggregates and a
  local-join aggregate receipt containing counts, public task identifiers and source hashes;
- the accepted support/back-office mission suite required by current research code;
- selected frozen aggregate/research artifacts, including their claim ceilings and payload hashes;
- only the current research scripts, source modules and focused tests needed to inspect the
  published methodology.

It excludes:

- `prd.md`, `readme.md`, `HANDOFF.md`, `PUBLICATION-READINESS.md`, `docs/archive/`,
  `docs/decisions/`, `docs/plans/`, `docs/questions/`, old reviews and other laboratory records;
- WEF and WORKBank raw files, all other upstream raw/source material and model-generation logs,
  except the narrowly defined synthetic terminal-answer projection below;
- generated `workforce-graph/site/data.json` and the old dashboard surface;
- files containing `/home/` absolute paths, key-like material, symlinks or undisclosed paths.

## Lifecycle

Authority: this contract and the builder's exact allowlist. Consumers: the public repository,
`README.md`, `PUBLIC_RELEASE.md`, `THIRD_PARTY_DATA.md` and `release-manifest.json`. The builder
copies bytes without rewriting evidence. Mapped public-only files are explicit source templates.

The release manifest binds every emitted path, byte count and SHA-256 plus the exact private source
commit. A verifier rejects added, missing or changed files, forbidden paths, local absolute paths,
symlinks and secret-like tokens. Build refuses an existing output directory.

## Reproduction ceiling

The clean release allows offline inspection, payload/hash verification and focused fixture tests.
It does not redistribute raw model generations outside the synthetic terminal-answer exception
or upstream restricted data, so a third party cannot
re-run every historical model call or regenerate every frozen aggregate from first principles.
Historical reports retain their checkpoint-time publication status; `PUBLIC_RELEASE.md` is the
authority for the later release decision.

The September supplement extends that ceiling precisely: the 108-convention diagnostic is recalculated
from original aggregate cells (counts and weight sums), and historical arm frequencies from
derived per-mission outcomes. Private source extraction remains separately hash-bound, not publicly
reproducible from unavailable raw logs. V3 includes published inputs and deliverables: its replay
reruns the domain grader, held-out logistic predictions and 1,999 blocked permutations. The final
August 12 work-mode partition used by the new diagnostic differs from the historical unfrozen
partition; its recalculated range is additive and does not replace the earlier report.

No new upstream source text, raw model generation outside the exception below, survey PDF, ATE source table, WEF/WORKBank
extract, labour-force microdata or private path is admitted by this supplement. Its precise files
are enumerated in `FIXED_FILES`; no broad publication directory glob expands that boundary.

The ATE appendix adds a separate reproducible path: explicit `fetch` obtains the pinned
upstream MANIFEST and eight source tables into an external user cache; offline `audit`
recalculates the published descriptive aggregate from checksum-verified bytes. No source
table, tool description or task text is redistributed. The local-join receipt contains only
counts, task-ID difference inventories, versions, provenance and hashes; repeating that join
requires the matching AllJobs database and effective bindings. A public aggregate receipt
does not reconstruct the unavailable database. Descriptor-match coverage is not execution,
adoption, labour-share or ROI evidence. These five additions are exact allowlist entries;
the appendix does not admit experimental live runs or broaden directory globs.

## Synthetic terminal-answer replay exception

The tools-by-defects result package may include exact final non-reasoning assistant answer
content for the project's original synthetic fixtures, including malformed JSON and duplicate
members, solely to reproduce the strict complete-state grader. Reserializing a parsed object
would destroy this evidence. Full conversations, intermediate assistant/tool messages, request
bodies, reasoning/thought content, signatures, headers, credential metadata, free-form provider
errors and private paths remain excluded. Unexpected sensitive content holds export; it is not
silently redacted while claiming full answer replay.

The public projection preserves every planned synthetic case, explicit not-started cases,
typed terminal classifications, numeric/status attempt receipts and resource uncertainty.
Only frozen original cases/tools and extracted pure parser/analysis functions accompany it;
live runners and provider modules are excluded. Extraction binds the original source hashes
and checks every reported private-summary field against public recalculation. A sanitized
configuration has its own public hash and is never labelled byte-identical to the private one.

Public replay recomputes strict grades, paired family-weighted contrasts, base-bootstrap
intervals, missing-cell bounds and projected resource accounting without network or model calls.
Optional matplotlib 3.10.8 rendering produces one original scientific PNG/SVG. Degenerate
bootstrap intervals do not establish equivalence; opaque source receipts do not reproduce
private transcripts, verify invoices or establish occupational performance. Result data and
frozen source snapshots use exact allowlist entries. The emitted main package contains all 684
planned trials, 171 complete paired bases and no infrastructure/missing outcomes. Its contrast
is within-budget complete-state correctness: 28 of 33 failures are explicit agent-turn/tool-call
budget terminations. It does not conflate those terminations with wrong submitted final answers.
The published JSON/CSV remain the primary analytical result; the figure is a deterministic view.

## ECBench derived-result projection

The ECBench supplement admits original final-state and numeric-cost projections for three
preserved technical pilots and the separately planned final 30-day seed pair, plus the
original stdlib calculator, its tests, one explicitly MOCK fixture plus its README and the bounded
study report. All thirteen additional files are exact `FIXED_FILES` entries. Historical
private runs and earlier exports remain intact; current public recomputations use the
published calculator without rewriting those historical receipts.

The closed bundle schema permits only the pinned upstream repository/revision/licence,
model route and evidence mode, planned horizon/seeds, source hashes, episode status,
selected final economic state and numeric actor/NPC cost summaries. Full trajectories,
observations, prompts, actions, model replies, reasoning, signatures, headers, private
request/response receipts, credentials and local paths are excluded. Source hashes bind
private extraction inputs; they do not make those inputs publicly reproducible.

Offline replay recomputes final-state and resource arithmetic, not environment or model
trajectories. Missing episodes remain missing, unknown billing remains reserved and actual
invoice cost remains null. Technical truncation suppresses the overall paired result;
verified finalized bankruptcy is a separate economic terminal, not horizon completion.
MOCK arithmetic is labelled separately and has no model-effect estimate. A single final
seed pair has no confidence interval or power claim. Simulated currency is distinct from
API expense and cannot establish customer ROI, occupational performance or a 365-day result.
The emitted final pair has both arms technically truncated by local cost limits, at days 14
and 17 of a planned 30; it has zero economic terminal pairs and null paired estimate/interval.
The package records that limitation rather than treating partial states as final outcomes.

## Rollback

The public repository can be archived without changing the private source repository or frozen
research artifacts. A replacement release must use a new source commit and manifest; it must not
silently overwrite the accepted public commit.
