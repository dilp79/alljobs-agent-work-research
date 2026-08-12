---
creator: codex
purpose: Fail-closed contract for the clean public AllJobs research release.
why: Publish the reproducible research surface without private laboratory records, local paths or unlicensed raw data.
version: 1
updated: 2026-08-12
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

## Rollback

The public repository can be archived without changing the private source repository or frozen
research artifacts. A replacement release must use a new source commit and manifest; it must not
silently overwrite the accepted public commit.
