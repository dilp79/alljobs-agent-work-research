---
creator: codex
purpose: Identify the retained ECBench arithmetic fixture and its evidence ceiling.
why: Prevent local mock outcomes from being represented as measured model performance.
version: 1
updated: 2026-09-06T20:33:51+03:00
---

`mock-real-kernel-30d.json` contains allowlisted observations from 16 completed
episodes: 30 simulated days, eight paired seeds, BASE and LEDGER. The existing
ECBench kernel ran with a deterministic local mock transport. No model API calls
occurred. Expense estimates and reservations are zero; provider credit charges
and actual invoices are unavailable. Identical paired outcomes demonstrate
arithmetic consistency only.

The fixture was exported by `scripts/reproduce_ecbench.py`. Source result and
receipt SHA256 values bind retained private evidence bytes. They do not make those
bytes public or independently prove execution. Only safe derived observations
are included. No upstream source, conversation, reasoning, signature, credential,
or private filesystem path is redistributed.

Upstream: https://github.com/QwenLM/E-CommerceBench at
`0c48f76f2577779cba786998f73b7992078b932d`, Apache-2.0. Fetch that repository
independently for environment execution. This fixture and recomputation script
only replay final-state and receipt arithmetic, not environment trajectories.

From `workforce-graph`, with a fresh output path:

```bash
python scripts/reproduce_ecbench.py recompute \
  --bundle tests/fixtures/ecbench/mock-real-kernel-30d.json \
  --output /tmp/ecbench-mock-recomputed.json
```
