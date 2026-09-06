---
creator: codex
purpose: Fail-closed contract for the clean public AllJobs research release.
why: Publish the reproducible research surface without private laboratory records, local paths or unlicensed raw data.
version: 3
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
- WEF and WORKBank raw files, all other upstream raw/source material and model-generation logs;
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
It does not redistribute raw model generations or upstream restricted data, so a third party cannot
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

No new upstream source text, raw model generation, survey PDF, ATE source table, WEF/WORKBank
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

## Rollback

The public repository can be archived without changing the private source repository or frozen
research artifacts. A replacement release must use a new source commit and manifest; it must not
silently overwrite the accepted public commit.
