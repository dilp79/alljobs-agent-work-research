# AllJobs agent-work research

AllJobs studies a deceptively simple question: can inexpensive model judgments identify work that
software agents can actually perform?

The answer from this release is narrower than a headline automation percentage. Three requested
model routes produced task-level opinions over an O\*NET corpus, but agreement is not task truth.
A stronger synthetic read-only tool successor produced 44 passes and 26 failures; adding the three
vote doses worsened held-out prediction rather than improving it. This does not prove that no
relationship exists. It means the current vote index is not validated as a capability predictor by
this experiment.

## Results

- 18,796 O\*NET task statements in the corpus; one third-route task remains an explicit,
  non-imputed nonresponse.
- Employment-weighted model-response index: 2.4% under unanimity, 5.9% under majority and 13.1%
  under any-route inclusion. These are model-response frequencies, not shares of jobs, hours or
  output.
- Work-location partial-identification ranges: 30.7–62.6% screen-only and 35.2–67.1%
  screen-plus-mixed. They are sensitivity ranges, not confidence intervals.
- Powered successor: 44/70 conformant, 26/70 non-conformant; difficulty-only held-out log loss
  0.4363 versus 0.5197 after adding votes; 1,999 category-blocked permutations, one-sided
  `p=0.9765`.

Read in this order:

1. [Business outcome and development potential](docs/reports/2026-08-12-business-outcome-RU.md)
2. [Research completion report](docs/reports/2026-08-12-research-completion.md)
3. [Predictive-validity successor](docs/reports/2026-08-12-predictive-validity-successor.md)
4. [Public release boundary](PUBLIC_RELEASE.md)
5. [Third-party data policy](THIRD_PARTY_DATA.md)

## What is published

This is a clean research release built from an exact private source commit. It includes final
reports, current contracts/audits, selected frozen aggregate artifacts, the accepted synthetic
mission suite and the focused code/tests used by the published analysis.

It does not include laboratory working records, local paths, upstream raw data, raw model
generations or the generated legacy site dataset. The Apache-2.0 licence covers original code and
documentation, not third-party material. See `release-manifest.json` for the exact file inventory.

## Verification

Python 3.12 or later and [uv](https://docs.astral.sh/uv/) are recommended:

```bash
cd workforce-graph
uv sync --locked --extra dev
uv run pytest -q \
  tests/test_predictive_validity_successor.py \
  tests/test_run_predictive_validity_successor.py \
  tests/test_analyze_predictive_validity_successor.py \
  tests/test_osworld_transfer_successor.py \
  tests/test_freeze_layer_two.py \
  tests/test_research_completion_report.py \
  tests/test_run_missions.py \
  tests/test_semantic_match.py
uv run python scripts/verify_public_release.py --root ..
```

Some production freeze commands in the historical reports require private raw model logs. Their
absence is deliberate; the public verifier checks the emitted frozen artifacts and manifest without
claiming that omitted raw calls can be reconstructed.

## Claim ceiling

Allowed: this release measured model responses and synthetic deterministic conformance under named
conditions, retained missingness and uncertainty, and did not detect incremental predictive value
from the frozen vote doses in the exact successor contour.

Not allowed: a percentage of jobs or working time is automatable; a named model succeeds on the same
share of real office work; no predictor relationship exists; the system has demonstrated customer
ROI or production reliability.

Licensed under Apache-2.0. External source rights remain with their owners.
