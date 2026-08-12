---
creator: codex
purpose: Document the frozen support/back-office candidate roster and its nonfinal product-review boundary.
why: Preserve E0 graph provenance while preventing candidate titles and preliminary labels from being mistaken for executable missions or validated safety classifications.
version: 2026-07-15.1
updated: 2026-07-15
---

# Support/back-office v1 candidate roster

This directory freezes 120 graph-derived candidates: ten categories with 12
candidates each, split 30 development / 72 held-out / 18 OOD, with 24 stability
members. `candidate_bindings.csv` is a byte-identical copy of the root planning
authority. This candidate-stage artifact is E0 taxonomy provenance only; it is
not an executable mission suite or evidence of usage, task success, automation,
replacement, or labor outcomes.

The roster is intentionally nonfinal. Weak candidates include:

- physical, field, or operational actions such as surveillance, press-conference
  attendance, cleaning work areas, vehicle/equipment reporting, emergency visits,
  certified mail, received-product inspection, and conformance inspection;
- medical, legal, and financial judgment involving eligibility, insurance or
  medical claims, disease processes, refractive correction, law/policy, credit,
  payments, payroll, and bank reconciliation;
- semantically similar titles for complaint response, scheduling, supervisor
  notification, record maintenance, reconciliation, and report writing;
- preliminary risk labels: 33 `approval_required` and 87 `low`. These are review
  inputs, not validated safety classifications.

Six valid graph activities currently lack release task/occupation mappings and
must not receive fabricated occupation IDs:

- `1d5b90e8edb8daf5c5da6708e2c76d21`
- `4e8f7398b2466455b8e71d1ff6c24587`
- `8868fa74ddfd7af7b62d0555f2be3b7e`
- `b7075c551b2db4426b52ff929f90f599`
- `c56e294e23843d5348ebd42d4b9291fa`
- `dd4cbddb1476ecfd1ad7ec4a84e4b4bb`

Task 4 human product review may supersede a candidate only through the immutable
review flow, using an existing graph activity ID, a recorded reason, preserved
category/split/stability/risk requirements, and unchanged totals of 120, 12 per
category, 30/72/18 splits, and 24 stability members. No Task 4 decision is
recorded here.
