---
schema: alljobs.research-completion-report/v1
report_date: 2026-08-12
research_status: RESEARCH_COMPLETE_WITH_PARTIAL_IDENTIFICATION
publication_status: HOLD_SEPARATE_GATE_NOT_CLEARED
generated: true
---

# Что исследование AllJobs действительно установило

**Статус исследования: `RESEARCH_COMPLETE_WITH_PARTIAL_IDENTIFICATION`. Публичный релиз: `HOLD`.**

Последний оценщик вернул 18,795 успешных work-mode меток из 18 796; сохранён 1 hash-bound explicit nonresponse точного маршрута. Метка не была подставлена: задача осталась unsettled. Receipt доказывает отсутствие валидной метки, но не per-attempt content outcome и не причину на стороне провайдера. После сохранения расхождений и пропусков как неопределённости settled остаются 17,846, unsettled — 950. Это измерение ответов моделей об описаниях задач, а не подтверждение того, какую долю работы можно передать ИИ.

## Слой 1 — где происходит работа

| Показатель | Значение |
|---|---:|
| Corpus | 18796 |
| screen | 8990 |
| mixed | 1341 |
| physical | 7515 |
| unsettled | 950 |
| Explicit third-rater nonresponses | 1 |
| Ровно три успешных bulk-rater ответа | 17932 |
| Adjudicated из ранее существовавшего входа | 2059 |

Employment-weighted partial-identification sensitivity ranges:

- strict (`screen`): **30.7%–62.6%**;
- generous (`screen + mixed`): **35.2%–67.1%**.

Это `partial-identification sensitivity range under missing-attempt extrema and unsettled-label extrema; not a confidence interval`. Coverage ceiling: `none; deterministic extrema conditional on inputs and mapping`. Ни одна граница не выбрана как point estimate.

Неопределённости сохранены раздельно:

- unanswered experiment attempts: partial identification; lost attempts {'contested': 253, 'control': 66};
- answered-attempt sampling: `sampling sensitivity envelope from marginal Wilson intervals among answered attempts; separate from missingness; not a headline confidence interval`; `95.0% marginal per fitted rate cell conditional on answered attempts and selected backoff; no simultaneous/headline coverage claim`;
- directional partition sensitivity: 864 задач с менее чем тремя ответами принудительно рассматриваются как contested;
- historical/current arm transport остаётся отдельной диагностикой; изменение strict endpoints = [0.0014083447147772987, -0.006197894130035353], generous endpoints = [0.003944787229746727, -0.003661451615065925].

Переход baseline → final:

- stratum 2×2: `{"baseline_contested__final_contested": 2537, "baseline_contested__final_control": 0, "baseline_control__final_contested": 401, "baseline_control__final_control": 15788}`;
- settlement 2×2: `{"baseline_settled__final_settled": 17160, "baseline_settled__final_unsettled": 321, "baseline_unsettled__final_settled": 686, "baseline_unsettled__final_unsettled": 629}`;
- ранее settled, но теперь split-awaiting-adjudication: 320.

## Слой 2 — deterministic mission evidence

Из 120 bound missions измерены 82; у 78 есть полный vote join. Primary outcome намеренно не выбран.

| Outcome | Все измеренные | Complete vote join | Ceiling |
|---|---:|---:|---|
| Suite/domain checker | 69/82 pass; 13 fail | 67/78 pass; 11 fail | necessary deterministic conformance, not mission success |
| Hardened semantic | 78/82 pass; 4 fail | 75/78 pass; 3 fail | compared decisions and memberships only; exempt prose unverified |

Exclusions: 38 mission rows по primary reason; ещё 4 measured missions не входят в complete-vote анализ.

Инструментальные ограничения, которые нельзя снять высокой долей pass:

- 77/78 complete missions получили хотя бы один requires-tool endorsement, но measured arm не имел tools;
- exact historical prompt bytes verified: `False`; rendered hashes present: 0/82;
- measurement trial router receipts: 82/82, но это не независимая backend attestation; predictor vote receipts verified: false;
- worked examples разделяют хотя бы один exact non-ID output literal в 67/82 measured missions;
- redacted-example arm: `HOLD` — 82/82 competence failures; запуска модели не было.

## Внешняя проверка computer-use

OSWorld 2.0 учтён как item-level GUI benchmark с 108 long-horizon workflows. Статья a16z используется как вторичный обзор, а не как первичная выборка. В registry собрано 8 profiles и 15 candidate edges; edges, способных authorise an AllJobs bound: **0**.

Следовательно, внешние данные уточняют дизайн successor study, но не задают верхнюю или нижнюю границу capability для задач AllJobs.

## Восстановленная authority и её предел

- RLI: 15 canonical rows, `EXACT_CANONICAL_MATCH`; raw page capture retained: `False`.
- HH: current-recovery-database logical witness воспроизводит accepted projection; relation row source = `current_recovery_database_not_missing_historical_database`; limitation = `does_not_establish_historical_relation_row_identity_or_recover_historical_duckdb_bytes`.

## Input receipts

| Role | Path | Bytes | SHA-256 |
|---|---|---:|---|
| work_mode_baseline | `workforce-graph/data/work_mode/work_mode_baseline_2026-08-11_incomplete-third-rater.json` | 8078423 | `8030717b904553ed3fe4be32c3350d51bbaa6e0df6f1c748886039512b55161a` |
| work_mode_final | `workforce-graph/data/work_mode/work_mode_final_2026-08-12.json` | 8313735 | `3c79b4bf6e2f3141d512505511774b9b8c93d744293d62f9dfb67ecd4b5a21c4` |
| work_mode_corrected | `workforce-graph/data/work_mode/corrected_result_full_glm_2026-08-12_final-collection.json` | 343134 | `474ea91d35f540679e6f1333dfd9af785a054509b145b6c225d5e8ad2984e29c` |
| layer_two_freeze | `workforce-graph/data/benchmark_relevance/layer_two_freeze.json` | 629855 | `bfc797d06de65e36dc48e11e2458db60d6cb3ad7567cae13ca4793d0ed31e5b2` |
| evidence_registry | `workforce-graph/data/evidence/registry.json` | 22516 | `0acb9ccdc1d4021a696308c63def790b5ffd60d0d5bff010efa13ecff77eac97` |
| rli_authority | `workforce-graph/research/authorities/rli-15row-canonical.json` | 3617 | `07203de074a2733dd4667a35025dd70a51764dcda2c5938b0e4833c19008c419` |
| hh_logical_witness | `workforce-graph/research/authorities/content_27_hh.2026-04-12.logical-slice.v1.json` | 361793 | `9c31852440e6bd49dbabd3cc1ae7e0e36213c970cba35a181d369d8846304001` |
| computer_use_evidence_audit | `docs/audits/2026-08-11-computer-use-evidence-update.md` | 5608 | `0496e34d119a8dde5d71e0d76b3ff61b2827b3db1c0041572dd0005b61370850` |

Embedded bindings:

- baseline snapshot payload: `8abab689d258c045e679f4c3658cf1a554fb7a04c50937339e003567bb6b12ca`;
- final snapshot payload: `abbcb8ebe082548c86766ac0038b5c6f8af83c7ec2a38b6b1b03443d0b1081cf`;
- transition audit payload: `c7ce785301679d6bfcd5379993fb92476a6829d5470683a358caadef75d16e98`;
- layer-two input set: `61fee907f87ce958d220ff63267944fe86c073d86e69fdd188f65b115aa2e75f`.

## Reproduction

Run from `workforce-graph/` in the locked environment:

```bash
replay_dir=$(mktemp -d /tmp/alljobs-research-replay.XXXXXX)
final_replay="$replay_dir/work-mode-final.json"
corrected_replay="$replay_dir/work-mode-corrected.json"
uv run python scripts/freeze_work_mode_snapshot.py freeze --output "$final_replay" --snapshot-date 2026-08-12 --third-rater gemini-3.5-flash-lite --third-rater-status complete_with_explicit_nonresponse --third-rater-nonresponse b7fb0c38fa9814f02a92795e78f809e2 --third-rater-request-model google/gemini-3.5-flash-lite --baseline-snapshot data/work_mode/work_mode_baseline_2026-08-11_incomplete-third-rater.json --expected-corpus-size 18796 --experiment-rater glm-5.2
cmp "$final_replay" data/work_mode/work_mode_final_2026-08-12.json
uv run python scripts/correct_for_uncertainty.py --state-snapshot "$final_replay" --baseline-snapshot data/work_mode/work_mode_baseline_2026-08-11_incomplete-third-rater.json --rater glm-5.2 --write "$corrected_replay"
cmp "$corrected_replay" data/work_mode/corrected_result_full_glm_2026-08-12_final-collection.json
uv run python scripts/freeze_layer_two.py --check
uv run python scripts/build_research_completion_report.py --check --baseline data/work_mode/work_mode_baseline_2026-08-11_incomplete-third-rater.json --final-snapshot data/work_mode/work_mode_final_2026-08-12.json --corrected data/work_mode/corrected_result_full_glm_2026-08-12_final-collection.json --layer-two data/benchmark_relevance/layer_two_freeze.json --evidence-registry data/evidence/registry.json --rli-authority research/authorities/rli-15row-canonical.json --hh-witness research/authorities/content_27_hh.2026-04-12.logical-slice.v1.json --external-audit ../docs/audits/2026-08-11-computer-use-evidence-update.md --report-date 2026-08-12 --output ../docs/reports/2026-08-12-research-completion.md
```

Повторная генерация snapshot/corrected-result должна выполняться в новые временные пути и сравниваться byte-for-byte: tracked evidence не перезаписывается для проверки.

## Claim ceiling и publication gate

Допустимая итоговая формулировка: исследование измерило ответы трёх запрошенных model routes о 18796 work-task statements и сохранило несогласие, missingness, sampling и transport как отдельные источники неопределённости. Оно не проверило центральный capability/automation тезис из-за отсутствия независимого task-truth и переносимых внешних границ — не из-за доказанного отсутствия связи.

`RESEARCH_COMPLETE` не означает `PUBLICATION_COMPLETE`. Лицензия, условия redistribution, absolute local paths, public remote и working-record treatment остаются отдельными блокерами в `PUBLICATION-READINESS.md`.

Исторические отчёты `2026-08-08-vote-index-onet-corpus-EN.md` и `2026-08-08-индекс-голосов-российский-рынок-RU.md` не являются текущим источником чисел.
