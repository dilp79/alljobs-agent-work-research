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

The clean release also excludes raw model generations, private source material and the generated
`workforce-graph/site/data.json`. Tracked aggregate/frozen research artifacts state their own
provenance and claim ceilings; their inclusion does not broaden the rights in an upstream source.
