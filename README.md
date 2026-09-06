---
creator: codex
purpose: Describe the public AllJobs research package and its verification entry point.
why: Public readers need the evidence ceiling and current reproducible runtime without broad compatibility claims.
version: 2026-09-06.3
updated: 2026-09-06
---

# AllJobs agent-work research

AllJobs studies a deceptively simple question: can inexpensive model judgments identify work that
software agents can actually perform?

The answer from this release is narrower than a headline automation percentage. Three requested
model routes produced task-level opinions over an O\*NET corpus, but agreement is not task truth.
A tool-enabled synthetic read-only successor produced 44 passes and 26 failures; adding the three
vote doses worsened held-out prediction rather than improving it. This does not prove that no
relationship exists. It means the current vote index is not validated as a capability predictor by
this experiment.

## New analytical note — September 2026

[От оценки задачи к проверке результата: три ограничения измерения способностей агента](docs/reports/research-note_06--092026_19-13.md)
provides three figures and an offline calculation command. It separates sensitivity to
historical definitions, scaffold/checker outcomes, and predictive validity. The legacy
L0–L4 scale is retired; its numerical sensitivity is not an automation forecast.

The final-partition diagnostic spans 0.025406–78.631813% across 90 eligible conventions
from a grid of 108. This is an additive calculation on the frozen August 12 partition,
not a revision of the historical 0.025406–78.331215% checkpoint. The note explains which
inputs are sufficient aggregate statistics and which outcomes can be regraded publicly.

## ATE reproducibility appendix

[ATE: descriptor coverage and exact O*NET joins](docs/reports/ate-appendix_06--092026_19-32.md)
recalculates 1,380/9,423 software-eligible task nodes with at least one `good` descriptor
match (14.645018%). This measures labelled catalogue coverage, not executable tools or
successful work. The appendix separates a public-source calculation from a local AllJobs
join whose database remains unavailable in this release.

After the environment setup below, run from `workforce-graph`:

```bash
# Explicit network download to an external user cache; verified cached bytes are reused.
uv run python scripts/reproduce_ate_audit.py fetch
# Offline calculation from the pinned cache, then focused tests.
uv run python scripts/reproduce_ate_audit.py audit --output /tmp/ate-descriptive.json
uv run pytest -q tests/test_reproduce_ate_audit.py
```

Both commands accept `--cache <directory>` for an existing source cache. Raw downloads
are excluded from the release. The published local-join JSON contains aggregates, public
task-ID inventories and hashes; its presence does not make the private database reproducible.

## Controlled tool-access experiment

[Инструменты, дефекты данных и правильность исполнения](docs/reports/tool-defect-study_06--092026_20-38.md)
reports 684/684 observed trials over 171 complete paired base cases. The tool-present minus
tool-absent contrast in **fully correct execution within fixed budgets** was −6.725 percentage
points (descriptive 95% stratified base-bootstrap interval −9.942 to −3.801).
Of 33 failures, 28 exhausted an agent-turn or tool-call budget and five failed exact final-state
grading. Numeric caps were not disclosed to the model; the no-tools branch ended after
its first answer. This result concerns the frozen model, tools and three synthetic templates; it does
not establish a general disadvantage of tools or an occupational automation rate.

The public package contains every original synthetic case, exact terminal answer strings,
typed failures and numeric attempt receipts. All grading, analytical and accounting fields
match the frozen private summary. It excludes conversations, reasoning, signatures and credentials.

```bash
cd workforce-graph
uv run python scripts/reproduce_tool_defect.py replay \
  --package data/tool_defect_public_2026_09_06 --output /tmp/alljobs-tool-defect-replay
uv run pytest -q tests/test_reproduce_tool_defect.py
# Optional original PNG/SVG; use a different new output directory.
uv run --locked --python 3.14.7 --with matplotlib==3.10.8 \
  python scripts/reproduce_tool_defect.py replay \
  --package data/tool_defect_public_2026_09_06 --output /tmp/alljobs-tool-defect-figure --plot
```

### Arm resource accounting

The tool-defect `trials.csv` includes arm, token counts and accounted cost; HTTP request counts
are available in the public numeric attempt projection. To reproduce the full arm resource
table from `workforce-graph` with the standard library:

```bash
python - <<'PY'
import json
from decimal import Decimal
from pathlib import Path
p = json.loads(Path('data/tool_defect_public_2026_09_06/replay_inputs.json').read_text())
arm = {c['case_id']: c['tools_available'] for c in p['suite']['cases']}
print('arm trials HTTP_attempts tool_calls known_input known_output accounted_USD unknown_usage_attempts')
for enabled, label in [(False, 'absent'), (True, 'present')]:
    rows = [r for r in p['trials'] if arm[r['case_id']] == enabled and r['kind'] != 'not_started']
    attempts = [a for r in rows for a in r['attempts']]
    cost = sum((Decimal(a['accounted_cost_usd']) + Decimal(a['unknown_billing_reserved_usd'] or '0')
                for a in attempts), Decimal(0))
    print(label, len(rows), len(attempts), sum(len(r['tool_calls']) for r in rows),
          sum(a['input_tokens'] or 0 for a in attempts),
          sum(a['output_tokens'] or 0 for a in attempts), cost,
          sum(a['unknown_billing_reserved_usd'] is not None for a in attempts))
PY
```

These are observed arm totals, not family-weighted causal cost estimates. Unknown token usage
is omitted from known-token sums and reported separately; it is not assumed to be zero.

## Earlier study results

- 18,796 O\*NET task statements in the corpus; one third-route task remains an explicit,
  non-imputed nonresponse.
- Employment-weighted model-response index: 2.4% under unanimity, 5.9% under majority and 13.1%
  under any-route inclusion. These are model-response frequencies, not shares of jobs, hours or
  output.
- Work-location partial-identification ranges: 30.7–62.6% screen-only and 35.2–67.1%
  screen-plus-mixed. They are sensitivity ranges, not confidence intervals.
- Synthetic successor: 44/70 conformant, 26/70 non-conformant; category-and-complexity held-out log loss
  0.4363 versus 0.5197 after adding votes; 1,999 category-blocked permutations, one-sided
  `p=0.9765`. Six categories have uniform outcomes; sensitivity within categories is
  limited, and power for plausible small effects is not established.

Read in this order:

1. [New analytical note and three figures](docs/reports/research-note_06--092026_19-13.md)
2. [Business outcome and development potential](docs/reports/2026-08-12-business-outcome-RU.md)
3. [Research completion report](docs/reports/2026-08-12-research-completion.md)
4. [Predictive-validity successor](docs/reports/2026-08-12-predictive-validity-successor.md)
5. [Public release boundary](PUBLIC_RELEASE.md) and [third-party data policy](THIRD_PARTY_DATA.md)

## What is published

This is a clean research release built from an exact private source commit. It includes final
reports, current contracts/audits, selected frozen aggregate artifacts, the accepted synthetic
mission suite and the focused code/tests used by the published analysis.

It does not include laboratory working records, local paths, upstream raw data, raw model
transcripts or the generated legacy site dataset. The narrow tools-by-defects replay exception
admits exact final synthetic answer text and numeric/status receipts so malformed or duplicate
JSON can be graded again. Reasoning, intermediate messages, signatures and credentials remain
excluded. The distributed main package contains the completed 684-trial series and its replay;
this does not establish customer, occupational or provider-trajectory reproducibility.
The Apache-2.0 licence covers original code and
documentation, not third-party material. See `release-manifest.json` for the exact file inventory.

## Verification

Ordinary CPython 3.14.7 and [uv](https://docs.astral.sh/uv/) are required:

```bash
cd workforce-graph
uv sync --locked --python 3.14.7 --extra dev
uv run --locked --python 3.14.7 --with matplotlib==3.10.8 \
  python scripts/reproduce_research_note.py --output /tmp/alljobs-research-note
uv run pytest -q \
  tests/test_reproduce_research_note.py \
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
