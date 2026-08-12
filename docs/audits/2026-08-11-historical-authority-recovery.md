---
creator: codex
purpose: Record the byte recovery of the RLI row authority and the bounded logical recovery of the historical HH projection inputs.
why: Close two reproducibility failures without deriving an independent fixture from the artifact it is meant to check or relabelling current data as historical data.
version: 1.0
updated: 2026-08-11
layer: knowledge
status: complete
---

# Historical authority recovery

## Outcome

The two previously named evidence-suite failures are resolved by two different recovery routes.

- The RLI authority is an exact byte recovery of the original independent 15-row capture.
- The HH reproducibility artifact is a bounded logical witness built from the current recovery
  database. It preserves the old DuckDB digest as historical provenance and is accepted only
  because it reproduces the already accepted projection exactly when combined with the
  immutable legacy annotation release. It is not authority for the historical identity of its
  individual relation rows.

Neither route changes a published value or strengthens its claim class.

## RLI: exact byte recovery

The original local artifact had been ignored by Git and disappeared during repository
consolidation. Its complete bytes remained in the original capture-session transcript:

- session ID: `019f6296-e7bf-7383-9369-717ff71f8727`;
- transcript file SHA-256:
  `3b5793bafb6987567ac91f6817f622538b61810ad5e137bdffdd98504f35cf4e`;
- retained tool-call ID: `call_ZUYXNJ9yCUcENaconbPJzVGr`;
- recovered artifact SHA-256:
  `07203de074a2733dd4667a35025dd70a51764dcda2c5938b0e4833c19008c419`.

The tracked recovery is
`workforce-graph/research/authorities/rli-15row-canonical.json`. A byte comparison against the
retained tool output passes. Its 15 ordered rows still produce the independent canonical TSV
receipt: 784 bytes, SHA-256
`dc12a3179b56860e22d34e6d522e94bd6b18d0064a0e92adfb62839a61325b33`.

This recovers the projected row authority, not the raw HTML. The source page had no retained
raw-page hash, global leaderboard version, denominator or confidence interval; all remain
absent.

## HH: recovered logical slice, not recovered database bytes

The accepted historical projection names DuckDB SHA-256
`744b3c03133b8bc40efe8f725fb33ec8727c3f3948d33ca50e9e5a043f7218b6`. Those full bytes are
not present. The current database has SHA-256
`ea1e38cfc42e334cd0e9ba86e34daa9530111dc225143fa1d5c94c7228d4dde9` and cannot be substituted:
running the old query against its current profile changes, among other values, weighted
exposure from `3.67` to `3.39`, low-exposure share from `56.6%` to `61.7%`, and the L3-majority
threshold share from `25.9%` to `9.3%`.

The current database contains HH and O*NET relation rows sufficient to replay the accepted
projection. The accepted release
already contains the historical 18,797-row `legacy_e1.parquet` at SHA-256
`52fb6a27a59fe4ed649a74ddc53e12be193b5c780cfb683b1523bbe7d9960df9`. The recovery therefore
freezes the query-relevant rows from that current recovery database as a logical witness:

| Current-DB witness relation | Frozen rows |
|---|---:|
| HH occupation/category mappings | 270 |
| HH market signals | 270 |
| Task links for mapped occupations | 2,359 |

The canonical current-DB logical witness is
`workforce-graph/research/authorities/content_27_hh.2026-04-12.logical-slice.v1.json`, 361,793
bytes, SHA-256
`9c31852440e6bd49dbabd3cc1ae7e0e36213c970cba35a181d369d8846304001`. The freeze builder
requires the exact recovery-database digest, exact release manifest, exact legacy E1 bytes and
exact accepted projection bytes. It writes only after the recovered inputs reproduce the full
accepted projection object byte-for-byte.

The artifact declares both its row source and ceiling in machine-readable form:
`current_recovery_database_not_missing_historical_database` and
`does_not_establish_historical_relation_row_identity_or_recover_historical_duckdb_bytes`.
It is a witness for offline reproduction of this accepted projection. It is not evidence that
any one of the 270/270/2,359 current relation rows is byte-identical to a missing historical row,
and it does not prove that the entire old and current databases are identical.

## Reproduction

From `workforce-graph/` in the locked environment:

```bash
uv sync --locked --extra dev
.venv/bin/python scripts/freeze_content27_hh_logical_slice.py check
.venv/bin/pytest -q \
  tests/evidence/test_content27_projection.py \
  tests/evidence/test_research.py
```

The first command verifies exact artifact/release hashes and full projection equality without
opening the mutable source database. The tests also fail on any logical-slice byte drift and
pin the exact recovered RLI artifact bytes.
