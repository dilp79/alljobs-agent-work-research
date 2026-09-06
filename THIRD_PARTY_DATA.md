---
creator: codex
purpose: Define original-work licensing and excluded third-party material.
why: Keep the public analytical supplement distinct from redistribution of its sources.
version: 2026-09-06.4
updated: 2026-09-06
---

# Third-party data policy

The Apache-2.0 licence in this repository covers only original code and documentation distributed
in the clean public release. It does not relicense third-party data or publications.

The public release intentionally excludes:

- `workforce-graph/data/raw/wef/2025/wef_skill_trends.csv`. It is a manually transformed extract
  from the World Economic Forum's *Future of Jobs Report 2025*. The Forum's current default terms
  are CC BY-NC-ND 4.0 and do not authorize distributing this transformed CSV as an Apache-licensed
  file. Consult the [WEF licence terms](https://www.weforum.org/about/licence-terms-on-the-use-of-forum-publications-and-materials/)
  and obtain the report from the publisher.
- `workforce-graph/data/raw/workbank/v1/expert_rated_technological_capability.csv`. The
  [WORKBank dataset card](https://huggingface.co/datasets/SALT-NLP/WORKBank) and
  [project repository](https://github.com/SALT-NLP/workbank) expose the dataset and request
  citation, but the reviewed pages do not declare a dataset redistribution licence. Obtain the
  data from its maintainers and comply with their current terms.

The clean release also excludes raw model transcripts, private source material and the generated
`workforce-graph/site/data.json`. Tracked aggregate/frozen research artifacts state their own
provenance and claim ceilings; their inclusion does not broaden the rights in an upstream source.

The September analytical supplement adds original aggregate counts, weight sums,
derived trial outcomes, calculations and figures. It adds no upstream task/tool text,
raw ATE tables, survey reports or magazine PDFs. Consult the source publishers for
McKinsey, Thomson Reuters and Harvard Business Review materials; those documents are
contextual research inputs, not files licensed by this project.

The ATE appendix contains original audit code, aggregate counts, public task identifiers
and source hashes. It does not redistribute ATE Parquet tables, verbatim tool descriptions,
O*NET task text, private database rows or additional binding rows. The pinned
[CohereLabs/ATE source](https://huggingface.co/datasets/CohereLabs/ATE/tree/4b567ba98acc6ddf27b2abb9004844581083c5d8)
does not declare a package-wide redistribution licence. Readers obtain source bytes directly
from the maintainer using the explicit fetch command and retain the source's applicable rights;
the Apache licence does not relicense those downloads. The local-join aggregate includes
database and logical-input hashes for provenance, without exposing their source rows.

The tools-by-defects replay exception covers final answer content generated for original
synthetic fixtures and numeric/status accounting projections. It does not admit external task
text, ATE descriptions, model reasoning, full conversations, signatures or private source rows.
Original fixture code and pure analytical source are hash-bound to the run; upstream model or
dataset ownership is not transferred by publishing a reproducibility projection.

The ECBench supplement contains original derived state/cost summaries, original arithmetic
code and an explicitly MOCK arithmetic fixture. Its upstream kernel is
[QwenLM/E-CommerceBench at 0c48f76](https://github.com/QwenLM/E-CommerceBench/tree/0c48f76f2577779cba786998f73b7992078b932d),
whose [Apache-2.0 licence](https://github.com/QwenLM/E-CommerceBench/blob/0c48f76f2577779cba786998f73b7992078b932d/LICENSE)
remains authoritative for upstream code. This release does not redistribute that kernel,
its trajectories, observations, prompts, NPC or actor replies, private provider receipts
or credentials. Hashes identify extraction sources without exposing them. Public arithmetic
reproduction does not reproduce upstream execution or expand rights in model/provider content.
