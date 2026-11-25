# Соответствие критериям приёмки

Каждый критерий приёмки комплекта ТЗ сопоставлен с реализацией и **проверяемым** способом
подтверждения. Статусы: ✅ подтверждено автотестом/инструментом · 🟡 реализовано, требует
пилотной выборки или ключей · ⛔ вынесено в промышленный контур (`ROADMAP.md`).

## ТЗ-01 §9

| Критерий | Реализация | Проверка | Статус |
|---|---|---|---|
| Тематическая точность поиска на размеченной выборке | `search/relevance.py`, разметка 0/1/2 в UI-04, метрики Precision@10 / nDCG@10 в UI-26 | `tests/test_search.py` (пороги, компоненты, метрики); численные значения — после разметки ≥ 30 документов | 🟡 |
| Корректность фильтра «Выбрать все страны» | UI-02 и UI-22, toggle-поведение | `tools/ui_check.mjs`: включение всех и снятие выбора повторным нажатием | ✅ |
| Трассируемость утверждений к источникам | `knowledge_claims` ↔ `evidence_items` ↔ `content_documents`, переход по клику из UI-07/19 | `tests/test_system.py::test_fact_requires_evidence`, `test_cross_research_evidence_rejected`; UI-19 открывает Evidence из утверждения | ✅ |
| Раздельное отображение TRL и реализуемости | отдельные экраны UI-08 и UI-09, разные сущности и формулы | `tools/ui_check.mjs` (оба экрана), `tests/test_analytics.py` | ✅ |
| Восстановление заданий | `workflow/engine.py`: идемпотентные ключи, `resume` только незавершённых этапов | `test_create_workflow_idempotent`, `test_resume_keeps_completed_stages`, `test_offline_pipeline_completes` | ✅ |
| Журналирование | `workflow_events`, `audit_log`, `audit_api_calls`, `core_state_history`, экспорт TXT/JSON/CSV | `tools/api_check.py` (logs, logs/export), UI-24 | ✅ |
| Ролевой доступ | 6 ролей, `ROLE_RIGHTS`, проверка на каждом маршруте | `tools/api_check.py --login observer/expert/auditor/analyst/admin/lead` — 63/63 для каждой из 6 ролей | ✅ |
| Экспорт всех форматов | HTML, PDF, DOCX, XLSX, JSON, CSV | `test_formats_generated`, `test_pdf_generated_with_cyrillic_font`, `tools/api_check.py --run` (выдача всех файлов) | ✅ |
| Защита ключей | шифр. хранилище + HMAC, маска в логах, в UI только факт наличия | `test_secret_roundtrip_and_mask`, `test_encryption_is_not_plaintext` | ✅ |
| Отсутствие платных вызовов без согласия | `allow_paid_ai = False`, группа `paid` исключается из маршрутизации | `test_paid_ai_blocked_by_default`, UI-06 «Платные (заблокированы политикой)» | ✅ |
| Численные критерии качества уточняются на пилоте | статус «калибровка не завершена» во всех экранах и отчётах | UI-26, `warnings()` отчёта | 🟡 |

## ТЗ-02 §7

| Критерий | Реализация | Проверка | Статус |
|---|---|---|---|
| Официальный тестовый вызов | `ai/adapters.py::check_connection`, UI-06 «Проверить» | `tools/api_check.py` (ai/providers, ai/route); живой вызов требует ключа | 🟡 |
| Работа агента минимум с двумя адаптерами | реестр 18 провайдеров / 11 моделей + локальный экстрактор, fallback-цепочка | `ai/orchestrator.py::candidates/select_route`, UI-06 «Маршрутизация» | ✅ |
| Блокировка платного вызова без разрешения | `paid_blocked`, запрет в DEV на уровне конфигурации | `test_paid_ai_blocked_by_default` | ✅ |
| Обработка rate limit | Retry-After + экспоненциальная задержка, статус `rate_limited` | живой S2AG → 429 зафиксирован (`docs/REGISTRY_NOTES.md`), `search/http.py` | ✅ |
| Корректность JSON Schema | валидация + одна попытка исправления → `schema_error` → fallback | `ai/orchestrator.py`, схема агента A07 (`suggested_level: integer|null`) | ✅ |
| Сохранение разногласий | `ai_consensus.conflicts`, 4 режима коллективного анализа | UI-18, `analytics`/`ai/collective.py` | ✅ |
| Воспроизводимость вызова | `prompt_version`, `prompt_hash`, `input_hash` расчётов | `test_reproducible_hash_and_version` | ✅ |
| Ключи маскируются, privacy_class проверяется | `storage/secrets.py::mask`, `ai/safety.py` | `test_secret_roundtrip_and_mask` (в т.ч. `Authorization: Bearer …`) | ✅ |

## ТЗ-03 (математические требования)

| Требование | Проверка | Статус |
|---|---|---|
| `R = 0,30S+0,25T+0,15C+0,15E+0,10K+0,05F`, пороги 0,80/0,60 | `test_components_and_weights`, `test_direct_match`, `test_irrelevant_is_excluded` | ✅ |
| TRL — максимальный уровень, усреднение запрещено | `test_max_level_not_average`, `test_no_evidence_means_level_one` | ✅ |
| Имитационные документы не подтверждают высокие уровни | `test_simulated_documents_do_not_confirm` | ✅ |
| `F = 100·Σ(wᵢxᵢ)/Σ(wᵢaᵢ)`, покрытие `C`, неизвестный ≠ 0 | `test_formula_and_coverage`, `test_unknown_factor_not_zero`, детерминированный расчёт 55 % / 34 % | ✅ |
| Диапазон и консервативная оценка | `test_range_contains_score` | ✅ |
| Чувствительность (исключение фактора, вес +30 %) | `test_weights_override_and_sensitivity` | ✅ |
| 11 классов барьеров, отсутствие ≠ отсутствие барьера | `test_empty_research_does_not_crash`, `test_detected_barriers_have_scale` | ✅ |
| 6 горизонтов, 3 сценария, монотонность `P(T≤t)` | `test_monotonic_and_wide_horizons` | ✅ |
| На 20–50 годах только качественные сценарии | тот же тест (`probability is None`, `qualitative` заполнен) | ✅ |
| Метрики валидации и статус калибровки | `test_validation_metrics_without_sample`, `test_brier_without_sample`, UI-26 | ✅ |
| Версионирование методик и контрольные суммы | `methodology_version` + `input_hash` в TRL/реализуемости/прогнозе/отчёте | ✅ |

## ТЗ-04 §8

| Критерий | Проверка | Статус |
|---|---|---|
| Все экраны UI-01…UI-30 доступны по ролям | `tools/ui_check.mjs` — 54/54 (в т.ч. UI-27…30 v1.1) | ✅ |
| Корректно отображаются состояния | `initial/loading/partial/success/empty/warning/error/offline/permission_denied` в `app.js`; пустая выдача объясняет причину | ✅ |
| Фильтр стран работает | UI-02/UI-22 + тест toggle | ✅ |
| Evidence открывается из вывода | UI-07 → карточка документа, UI-19 → панель доказательств | ✅ |
| Графики обновляются по фильтрам | UI-04 (фильтры), UI-17 (целевое состояние/вкладки), UI-21 (фильтры реестра) | ✅ |
| Журнал выгружается | TXT/JSON/CSV, `tools/api_check.py` | ✅ |
| Экспорт читаем | PDF: извлечение кириллицы (`tools/pdf_check.mjs`), XLSX/DOCX — валидный OOXML | ✅ |
| Интерфейс адаптивен | CSS-брейкпоинты 1500/1250/900, сворачиваемые меню и контекст | ✅ |
| UI не пересчитывает научные показатели | все значения из API + `methodology_version`; в `web/*.js` нет формул TRL/F/R | ✅ |
| Легенды, единицы, tooltip, текстовая альтернатива, экспорт графиков | `charts.js::wrap()` — легенда, единицы, `<title>`, таблица данных, CSV | ✅ |

## Промышленные критерии, не проверяемые в DEV

| Критерий | Состояние |
|---|---|
| Доступность ≥ 98 %/мес | ⛔ эксплуатационная метрика: нужен промышленный контур и мониторинг за период |
| Главная ≤ 3 с, исследование ≤ 5 с при 100k–1M+ документов | ⛔ требуется PostgreSQL/OpenSearch и нагрузочный прогон; в DEV на 806 источниках и ~60 документах отклик < 1 с |
| TLS, OIDC/SSO, аудит по SIEM | ⛔ граница развёртывания (reverse proxy + IdP), см. `ROADMAP.md` |
| Калибровка метрик на пилотной выборке | 🟡 механизм разметки и расчёта готов, нужны эталонные данные |

## Ведомость корректирующих изменений v1.1 (ИД-01…ИД-12)

Матрица трассируемости «нормативное исправление → реализация → контрольное испытание».
Идентификаторы испытаний совпадают с ведомостью (`tests/test_change_register.py`),
дополнительные проверки контура — `tools/api_check.py`, `tools/ui_check.mjs`.

| ИД | Приоритет | Реализация (модуль · таблица · маршрут) | Контрольное испытание | Статус |
|---|---|---|---|---|
| ИД-01 RELEVANCE_V1 | P0 | `search/relevance.py` (6 компонент, веса, причины) · `search_results.score_s…score_f`, `weights`, `methodology_id`, `reason_codes` · `GET /api/v1/search-results` | `RELTests::test_REL_01_identical_score_same_methodology`, `::test_REL_01_components_persisted` | ✅ |
| ИД-02 FEASIBILITY_V1 | P0 | `analytics/feasibility.py` (`F=100·Σw·x·a/Σw·a`, `C=Σw·a/Σw`, `is_available`) · `analytics_feasibility.coverage/range_low/range_high/coverage_warning` · `GET /api/v1/feasibility-assessments`, `POST /api/v1/analytics/{id}/recompute` | `FEASTests::test_FEAS_01_unknown_factors_excluded`, `::test_FEAS_02_repeatable`, `::test_FEAS_03_all_unknown_gives_null`, `::test_FEAS_04_negative_value_is_assessment`, `::test_FEAS_05_low_coverage_warning` | ✅ |
| ИД-03 модель дедупликации | P0 | `search/dedup.py` (blob → document → occurrence → cluster; шаги 1–5, REVIEW) · `content_blobs` (UNIQUE `content_sha256`), `content_documents`, `content_occurrences`, `content_clusters`, `content_cluster_members`, `content_relations` · `GET /api/v1/documents`, `/document-clusters`, `/document-relations` | `DEDUPTests::test_DEDUP_01_preprint_and_published_are_linked` (2 вхождения, 1 кластер, `PREPRINT_OF`), `::test_DEDUP_02_five_urls_one_document` (Т-006: 5 URL → 5 вхождений), `::test_DEDUP_03_blob_uniqueness` | ✅ |
| ИД-04 единый каталог API | P1 | `api/server.py` (`ROUTES`, 76 маршрутов, мн. число, UUID, ISO 8601+TZ, единый `error`, `limit/cursor`, идемпотентность) · `openapi.json` (OpenAPI 3.1, 69 paths) · legacy → `410 Gone` + новый путь | `APITests::test_API_01_canonical_catalog_in_openapi`, `::test_API_02_legacy_route_gone`; `tools/api_check.py` — 63/63 × 6 ролей | ✅ |
| ИД-05 представление прогнозов | P0 | `analytics/forecast.py` + `methodologies.presentation_policy()` (серверная политика по `years_from`) · `forecast_points.probability_value` (внутренняя точность NUMERIC(7,6)), `display_mode`, `display_precision`, `uncertainty_class` · `GET /api/v1/forecasts/{id}` | `FCSTTests::test_FCST_01_long_horizon_is_scenario` (40 лет, 0,734821 → SCENARIO без точечного %), `::test_FCST_02_presentation_policy_by_horizon`, `::test_FCST_03_points_stored_with_policy` | ✅ |
| ИД-06 extraction_status ≠ relevance | P0 | `content_documents.extraction_status` (FSM извлечения) и `search_results.relevance_class`/`decision` (на исследование и запрос) · view `research_documents` | `DOCStatusTests::test_DOC_01_extraction_and_relevance_independent`, `::test_DOC_02_one_document_two_researches`, `::test_DOC_03_manual_exclusion_keeps_class` (`MANUAL_EXCLUDE`, класс не меняется) | ✅ |
| ИД-07 три класса релевантности | P1 | `search/relevance.py::classify()` — единственный источник порогов (DIRECT ≥ 0,80 / ADJACENT ≥ 0,60 / BELOW_THRESHOLD), `CLASS_ALIASES` только для UI | `RELTests::test_REL_02_class_boundaries` (0,82/0,80/0,79/0,60/0,59) | ✅ |
| ИД-08 единая шкала TRL | P1 | `analytics/trl.py` (цепочка обязательных критериев, `validate_no_averaging`) · `analytics_trl_criteria.criterion_code TRL<n>-C<nn>`, `analytics_trl_criterion_evidence` · нормативные названия уровней в UI-08 | `TRLTests::test_TRL_01_mandatory_gap_blocks_level`, `::test_TRL_02_averaging_rejected`, `::test_TRL_03_criterion_codes_stable` | ✅ |
| ИД-09 реестр методик | P0 | `analytics/methodologies.py` (`bootstrap`, `create_version`, `set_approval`, `used_in_research`) · `analytics_methodologies` (formula/parameters/thresholds, valid_from/to, PROVISIONAL/VALIDATED/DEPRECATED, `config_checksum`, `validation_examples`, `previous_version_id`) · `GET /api/v1/methodologies`, UI-27 | `METHTests::test_METH_01_new_version_keeps_history`, `::test_METH_02_repeatability_precision`, `::test_METH_03_registry_fields`; `REPRTests::test_REPR_04_report_shows_bound_methodology` | ✅ |
| ИД-10 разделение F / P / уверенности | P0 | `analytics_feasibility` (F, 0–100), `forecast_points` (P(T≤t), 0–1), `analytics_confidence` (уверенность, 0–1) — три независимые записи; P не выводится из F · `GET /api/v1/analytics/{research_id}` (`S.analytics_bundle`) | `SEPTests::test_SEP_01_feasibility_probability_confidence_separate`, `::test_SEP_02_api_returns_separate_indicators` (КИ-014) | ✅ |
| ИД-11 независимость Evidence | P0 | `analytics/evidence.py::assign_independence()` (PRIMARY / INDEPENDENT_CONFIRMATION / REPRINT / SUMMARY / DERIVATIVE / CONTRADICTORY, явный `derived_from`) · `evidence_items.origin_class`, `independence_group_id`, `evidence_independence_groups` · `GET /api/v1/independence-groups`, UI-28 | `EVIDTests::test_EVID_01_reprints_one_group` (5 перепечаток → 1 группа, 6 участников), `::test_EVID_02_independent_confirmation_adds_group` | ✅ |
| ИД-12 воспроизводимость | P0 | `analytics/snapshot.py` (`capture`, `replay`, `start_run/finish_run`) · поля `research_id`, `document_set_version`, `methodology_id`+`version`, `model_id`+`version`, `prompt_version`, `input_snapshot`, `parameters`, `config_checksum`, `input_hash`/`output_hash`, `assessed_by` · `POST /api/v1/replay`, UI-30 | `REPRTests::test_REPR_01_replay_identical`, `::test_REPR_02_old_result_reproducible_after_version_change`, `::test_REPR_03_snapshot_fields_present` | ✅ |

Итог по ведомости: **12/12 исправлений реализованы**, 33 контрольных испытания
`tests/test_change_register.py` проходят; сводный прогон на момент закрытия ведомости — **96/96** модульных тестов,
**63/63** проверок API для каждой из 6 ролей, **54/54** проверок интерфейса (на момент закрытия ведомости; текущие итоги — в разделе 1.2.0 ниже).

Открытые вопросы, требующие утверждения заказчиком (не блокируют приёмку механизма):
порог покрытия `C = 0,60` и веса факторов F имеют статус `PROVISIONAL`; калибровка
метрик (Precision@10, nDCG@10, TRL MAE, Brier, покрытие интервалов) не завершена —
статус выводится в UI-26, отчётах и `GET /api/v1/quality`.

## Следующий этап ROADMAP (редакция 1.2.0)

| Пункт плана | Реализация | Контрольное испытание | Статус |
|---|---|---|---|
| P4 · граф связей с раскрытием по щелчку и фильтром типов | `service.document_graph()`, `GET /api/v1/document-graph`, `Charts.network()`, UI-30 «Граф связей» (легенда типов, единицы, текстовая альтернатива, экспорт рёбер) | `GRAPHTests::test_GRAPH_01_nodes_edges_and_isolated`, `::test_GRAPH_02_type_filter_applied_on_server`; `tools/ui_check.mjs` (SVG, фильтр, переход в карточку) | ✅ |
| P4 · сравнение версий расчётов | `service.assessment_diff()`, `GET /api/v1/assessments/diff`, UI-29 «Сравнение версий расчётов» (Δ значений, версии методик, факторы, критерии TRL) | `DIFFTests::test_DIFF_01_values_and_methodology`, `::test_DIFF_02_identical_results`, `::test_DIFF_03_trl_criteria_and_guards`; `tools/ui_check.mjs` (выбор A/B → результат) | ✅ |
| P6 · трассировка request_id / correlation_id | `isheika/telemetry.py`, заголовки `X-Request-ID`/`X-Correlation-ID`, `workflow_events.correlation_id`, `audit_log.correlation_id`, `audit_api_calls.request_id`, наследование трассировки фоновым потоком, `GET /api/v1/trace/{id}`, UI-24 | `TRACETests::test_TRACE_01_events_and_audit_carry_correlation`, `::test_TRACE_02_background_run_inherits_correlation`, `::test_TRACE_03_external_id_sanitized`; `tools/api_check.py` (проброс заголовков, 422 на некорректный id) | ✅ |
| P6 · метрики латентности и доли partial | `workflow_jobs.duration_ms`, `api/metrics.py`: `isheika_workflow_stage_duration_ms_avg/max`, `isheika_workflow_partial_share`, `isheika_traced_events_total`, `isheika_api_calls_duration_ms_avg` | `METRTests::test_METR_01_stage_latency_and_partial_share`, `::test_METR_02_api_call_latency_by_target` | ✅ |
| Миграция схемы под трассировку | `storage/migrate.py::migrate_0003_observability` (идемпотентное `ALTER TABLE`, индексы по correlation_id) | `MIGRTests::test_MIGR_01_observability_columns_idempotent` | ✅ |
| Единый файл запуска (задача 2) | `tools/build_exe.py` → `release/ISHEIKA-NTR-AI.exe`: 7zSD.sfx + config + 7z(CPython 3.11 x64 + приложение), данные в `%LOCALAPPDATA%\IsheikaNTR-AI` | Структура PE/config/архива (`BUILD-INFO.json.structure`), запуск образа под wine64 (`--verify-wine`: API 200, UI 200), **112/112 тестов внутри образа** (`--verify-tests`) | ✅ |
| Трассируемость ИД ↔ испытания | Матрица в разделе «Ведомость корректирующих изменений v1.1» выше | `tests/test_change_register.py` (33 испытания) | ✅ |

Сводные проверки редакции 1.2.0: **112/112** модульных тестов,
**69/69** проверок API для каждой из 6 ролей (**82/82** в режиме `--run`),
**61/61** проверок интерфейса, **112/112** тестов внутри Windows-образа.


## Исправление «белого экрана» и журнал загрузки (замечание пользователя)

**Симптом:** браузер открывает `127.0.0.1:8000`, заголовок страницы есть, содержимое —
пустой белый экран, никаких сообщений.

**Причина (установлена измерением):** обработчик статики разбирал путь через
`os.path.normpath`; на Windows это даёт `\app.js`, `lstrip("/")` не снимает обратный
слэш, `os.path.join(WEB_DIR, "\app.js")` отбрасывает каталог интерфейса, файл не
находится — и обработчик подставлял `index.html`. Замер в Windows-образе: все
8 ресурсов возвращались как `text/html` по 4348 Б вместо своих файлов. Без CSS и
сценариев оба контейнера (`#login`, `#app`) остаются скрытыми — белый экран.

| Исправление | Реализация | Контрольное испытание | Статус |
|---|---|---|---|
| Разбор пути не зависит от ОС | `server.static_target()` — POSIX-правила, отсечение обхода каталога и путей вида `C:\…` | `STATTests::test_STAT_01_path_resolution_is_os_independent`, `::test_STAT_02_traversal_and_absolute_paths` | ✅ |
| Типы содержимого заданы явно | `server.STATIC_TYPES` / `static_ctype()` — не из реестра ОС | `::test_STAT_03_content_types_are_explicit`; `tools/api_check.py` (тип и размер каждого ресурса) | ✅ |
| Отсутствующий ресурс — 404 | `_static()` больше не подставляет HTML вместо `.js`/`.css` | `::test_STAT_04_missing_asset_is_404_not_html`; `api_check` (`/no-such-file.js` → 404) | ✅ |
| Скрытие контейнеров | `[hidden]{display:none !important}` в `styles.css` | `tools/ui_check.mjs` (70/70) | ✅ |
| Отказ ресурсов ОС — 503 | `server.Server.process_request()` отвечает 503 с причиной и пишет в журнал | `::test_STAT_06_resource_exhaustion_answers_503` | ✅ |
| Проверка ресурсов в сборке | `build_exe.verify_wine` сверяет размер и тип **каждого** ресурса внутри Windows-образа | `--verify-wine`: **ресурсов 8/8** (до исправления — 0/8) | ✅ |
| Журнал операций при загрузке | `isheika/boot.py`: шаги запуска, самопроверка, консоль, файлы `boot-log.txt/json`, `GET /api/v1/boot-log` (публичный), `…/history`, `…/export?fmt=txt\|json` | `BOOTTests::test_BOOT_01…07`; `api_check` (журнал, самопроверка, выгрузка) | ✅ |
| Экран загрузки в браузере | `index.html`: журнал виден до инициализации, перехват ошибок сценариев и ресурсов, сторож 12 с, кнопки «Повторить»/«Скачать журнал»; кнопка 🧾 после входа | `tools/ui_check.mjs`: 6 проверок журнала, включая показ диагностики при отказе | ✅ |
| Устойчивость инициализации | `app.js`: безопасное связывание обработчиков (`on()`), таймаут запросов 45 с, форма входа показывается всегда | `tools/ui_check.mjs` (70/70), `STAT`/`BOOT` | ✅ |

Сводные проверки после исправления: **144/144** модульных тестов, **94/94** проверок
API, **70/70** проверок интерфейса; распакованный итоговый образ отдаёт все 8 ресурсов
с правильными размером и типом, `boot-log` — «исправно», отсутствующий ресурс — 404.

**Ограничение проверки (честно).** Проверка Windows-образа (`--verify-wine`,
`--verify-launch`, `--verify-tests`) выполнена для сборки `5129d5f38e1f759c…`:
**ресурсов 8/8**, **143/143** тестов внутри образа, цепочка запуска HTTP 200 / UI 200.
Итоговый артефакт `86f04ee290a5b524…` отличается от неё только защитой 503 при
исчерпании потоков, текстом памятки и документацией; повторно прогнать wine не
удалось — в песочнице исчерпан лимит процессов (791 зомби-процесс wine,
`can't start new thread` / `Resource temporarily unavailable`). Итоговый артефакт
проверен на Linux: структура PE/конфигурации/архива, побайтовое совпадение ресурсов,
типы содержимого, журнал загрузки, 404 на отсутствующий ресурс, все наборы тестов.
Сведения зафиксированы в `release/BUILD-INFO.json` (`environment_note`,
`prior_windows_verification`, `linux_verification`).


## Эксплуатационный контур (редакция 1.3.0, ROADMAP P6)

| Пункт плана | Реализация | Контрольное испытание | Статус |
|---|---|---|---|
| P6 · SLO доступности ≥ 98 %/мес | `isheika/slo.py`: самопроверки `api`/`database`/`storage` (шаг 60 с), окна 24 ч/7 сут/30 сут, бюджет ошибок 2 %, `GET /api/v1/slo`, `POST /api/v1/slo/probes`, планировщик `start_slo_scheduler()` | `SLOTests::test_SLO_01_probes_measure_real_subsystems`, `::test_SLO_03_availability_and_error_budget`; `tools/api_check.py` (окна и цель 98 %) | ✅ |
| P6 · запрет выдуманных показателей | при отсутствии измерений — `NO_DATA` и `null` (принцип ИД-10) | `SLOTests::test_SLO_02_no_data_is_not_fabricated` | ✅ |
| P6 · скорость расхода бюджета ошибок | `slo.burn_rate()`, порог 14,4× при ≥ 10 измерениях | `SLOTests::test_SLO_04_burn_rate` | ✅ |
| P6 · алерты с основаниями | 6 детерминированных правил, `ops_alerts`, автозакрытие по устранении причины, `GET /api/v1/alerts`, `POST /api/v1/alerts/evaluate`, `POST /api/v1/alerts/{id}/acknowledge` | `SLOTests::test_SLO_05_alert_lifecycle`, `::test_SLO_06_acknowledge_is_not_close`, `::test_SLO_07_rules_carry_evidence` | ✅ |
| P6 · RBAC эксплуатационных маршрутов | чтение — `logs.read`, самопроверки/правила — `settings.read`, создание копии — `keys.write` | `SLOTests::test_SLO_08_routes_and_rbac`; `tools/api_check.py` для 6 ролей | ✅ |
| P6 · резервные копии | `isheika/backup.py`: снимок БД через sqlite backup API, ключи в шифрованном виде, манифест с SHA-256, реестр `ops_backups`, `GET/POST /api/v1/backups`, `POST /api/v1/backups/{id}/verify` | `BackupTests::test_BKP_01_create_and_verify`, `::test_BKP_06_backup_registered_in_alert_rule` | ✅ |
| P6 · обнаружение повреждения копии | проверка CRC, сумм, `integrity_check`, состава схемы и счётчиков | `BackupTests::test_BKP_02_corruption_detected`, `::test_BKP_04_restore_rejects_bad_copy` | ✅ |
| P6 · восстановление с подтверждением | `run.py --restore … --yes`, копия прежнего состояния (`pre-restore`), событие в журнале; без подтверждения — `E_STATE` | `BackupTests::test_BKP_03_restore_requires_confirmation`, `::test_BKP_05_cli_roundtrip` (сквозной цикл в изолированном каталоге данных) | ✅ |
| P6 · экран эксплуатации | **UI-31** «Эксплуатация: SLO и резервные копии» (3 вкладки, экспорт таблиц, действия оператора) | `tools/ui_check.mjs` — 64/64, включая `ops`, `ops?tab=alerts`, `ops?tab=backups` | ✅ |
| P6 · метрики и регламент | `isheika_slo_*`, `isheika_alerts_open`, `isheika_backups_total`; `docs/RECOVERY.md` | `tools/api_check.py` (`GET /metrics`), вычитка регламента | ✅ |
| Миграция схемы | `storage/migrate.py::migrate_0004_ops` — `service_probes`, `ops_alerts`, `ops_backups` (идемпотентно) | применение к существующей БД и к свежей схеме | ✅ |

Сводные проверки редакции 1.3.0: **131/131** модульных тестов, API — все проверки
пройдены для каждой из 6 ролей (78–82 в зависимости от роли), **93/93** в режиме
`--run`, **64/64** проверок интерфейса, **87** маршрутов REST, **131/131** тестов
внутри Windows-образа. Регламент эксплуатации — `docs/RECOVERY.md`.


## Исправление запуска единого файла (замечание пользователя)

**Симптом:** при запуске `ISHEIKA-NTR-AI.exe` модуль 7-Zip показывал
«Не удается найти указанный файл».

**Причина (установлена по исходнику `CPP/7zip/Bundles/SFXSetup/SfxSetup.cpp`, LZMA SDK):**
`RunProgram` выполняется как `CreateProcess(NULL, dirPrefix + RunProgram)`, где
`dirPrefix` по умолчанию `".\"`. Конфигурация `RunProgram="cmd /c start.cmd"`
превращалась в командную строку `".\cmd /c start.cmd"`, то есть исполняемым файлом
считался `.\cmd` → `ERROR_FILE_NOT_FOUND` → именно это сообщение.

**Исправление:** запуск переведён на `ExecuteFile="cmd.exe"` +
`ExecuteParameters="/c isheika.cmd"` — ветка `ShellExecuteEx` не добавляет префикс,
`cmd.exe` находится в System32, рабочий каталог уже установлен в каталог распаковки.
Дополнительно: браузер открывает сама программа (`--open-browser`), при занятом
порте берётся следующий свободный (`--port-auto`), номер порта в `isheika.cmd`
принимается только числом (SFX дописывает свои ключи в командную строку),
проверка выполняется средствами cmd без `findstr`.

| Проверка | Что подтверждает | Статус |
|---|---|---|
| `PKGTests::test_PKG_01_sfx_launch_uses_shellexecute` | в конфигурации нет `RunProgram`, запуск только через `ExecuteFile` — регрессия исключена | ✅ |
| `PKGTests::test_PKG_02_launch_cmd_contract` | сценарий `isheika.cmd` (имя не совпадает с внутренней командой cmd) ведёт к `python\python.exe`, данные вне temp, числовая проверка порта | ✅ |
| `PKGTests::test_PKG_03_structure_parser` | структура файла: PE + конфигурация + сигнатура 7z, механизм запуска распознан | ✅ |
| `PKGTests::test_PKG_04_cli_flags_present` | точка входа поддерживает `--open-browser` / `--port-auto` | ✅ |
| `PKGTests::test_PKG_05_port_fallback` | занятый порт → следующий свободный; без флага — понятная ошибка `E_STATE` | ✅ |
| `tools/build_exe.py --verify-launch` | цепочка `cmd.exe /c isheika.cmd` → `python.exe` → сервер: HTTP 200, интерфейс 200 | ✅ |
| `release/ISHEIKA-NTR-AI-portable.zip` | запасной путь поставки без SFX (распаковать → `isheika.cmd`) | ✅ |

32-битный SFX-заголовок в песочнице сборки не исполняется (seccomp блокирует
32-битный загрузчик wine), поэтому проверка разделена: семантика запуска
сверена с исходником модуля, а цепочка запуска проверяется реальным исполнением
`cmd.exe /c isheika.cmd` внутри распакованного образа.

**Второе замечание, найденное исполнением:** сценарий с именем `start.cmd`
не запускался — парсер `cmd` принимает `start` за внутреннюю команду `START`,
а `.cmd` за её аргумент, и выдаёт «ShellExecuteEx failed: File not found».
Сценарий переименован в `isheika.cmd`; проверка `--verify-launch` выполняется
тем же вызовом, что и в конфигурации SFX.

## ИД-13. Ложный отказ диагностики загрузки (редакция 1.3.1, замечание пользователя)

**Замечание.** В журнале загрузки браузера на исправно работающем интерфейсе:

```
FAIL 16 мс Объект Charts — не определён
OK   19 мс Объект Screens — 33 экранов
OK   19 мс Объект App — загружен
```

Все шаги сервера — `OK` (806 источников, 89 маршрутов, ресурсы 8/8), но экран
журнала загрузки не скрывался и оставался поверх формы входа.

**Причина (найдена исполнением в DOM).** `charts.js` объявлял модуль как
`const Charts = (() => …)()`. `const` в классическом сценарии создаёт **лексическую
привязку глобальной области**, а не свойство `window`: соседние сценарии видят
`Charts`, но `window.Charts === undefined`. Диагностика в `index.html` проверяла
именно `window.Charts`, поэтому писала отказ на рабочем модуле, а `B.hide()`
отказывался скрывать экран при `B.failed === true`. Дефект диагностики, не графики:
все 33 экрана и инфографика работали (проверено `tools/ui_check.mjs`, 70/70 до правки).

**Исправление.**

1. `charts.js` публикует модуль: `window.Charts = Charts` — тот же приём, что
   `window.App` и `window.Screens` в остальных сценариях.
2. Диагностика разрешает объект двумя способами (`B.mod`): свойство `window` и
   лексический global через `typeof` в `try` (до исполнения сценария привязка в TDZ).
   Ложный отказ исключён, настоящий отказ сопровождается подсказкой, какой сценарий
   не выполнился.
3. Отказ диагностики больше не запирает интерфейс: при готовом `App` показывается
   кнопка **«Продолжить работу»** (`B.dismiss`), а после её нажатия поздние отказы
   не перехватывают экран (`B.show` уважает `B.dismissed`). Журнал доступен по 🧾.

| Проверка | Что подтверждает | Статус |
|---|---|---|
| `StaticTests::test_STAT_07_every_module_publishes_its_global` | каждый сценарий из разметки публикует свой объект в `window`; комментарии не считаются кодом (проверено внесением дефекта — тест падает) | ✅ |
| `BootTests::test_BOOT_08_diagnostics_tolerate_lexical_globals` | проверка объектов не опирается только на `window.X` | ✅ |
| `BootTests::test_BOOT_09_failed_diagnostics_do_not_lock_the_ui` | кнопка «Продолжить работу», `B.dismiss`, защита от повторного перехвата | ✅ |
| `BootTests::test_BOOT_10_expected_scripts_match_markup` | список ожидаемых сценариев в диагностике совпадает с разметкой | ✅ |
| `tools/ui_check.mjs` | «модуль Charts опубликован в window», «Charts рисует SVG из данных», «журнал загрузки: отказов при загрузке нет», «отказ закрывается кнопкой» | ✅ |
| Отрицательная проверка (исполнение в jsdom) | `charts.js` временно убран → `FAIL … сценарий charts.js не выполнился`, экран показан, кнопка «Продолжить работу» доступна, повторный отказ экран не перехватывает | ✅ |

### Сопутствующие замечания, устранённые в той же редакции

**RPT-05. Ссылки на отсутствующие файлы отчёта.** Запись отчёта в БД переживает
сами файлы (перенос состояния без `var/files`, восстановление, чистка каталога).
Интерфейс рисовал ссылку на каждый формат из записи — клик давал голый 404.
Теперь `GET /api/v1/reports` отдаёт `files_available` и `missing_files`, интерфейс
показывает неактивную кнопку с пояснением и предложение сформировать отчёт заново,
а `tools/api_check.py` помечает такие проверки `SKIP` с указанием причины вместо
`FAIL` (проверка `ReportTests::test_missing_report_file_is_reported_not_linked`).

**RBAC. История загрузок.** `/api/v1/boot-log/history` требовала только
аутентификации, тогда как остальные журналы, SLO, алерты и копии требуют
`logs.read`: наблюдатель читал эксплуатационный журнал (пути к каталогу данных,
платформа, причины прошлых отказов). Право приведено к общему правилу; публичным
остаётся только текущий журнал `/api/v1/boot-log` — диагностика «белого экрана»
(проверка `BootTests::test_BOOT_11_history_requires_logs_read`).

**Версия в шапке интерфейса.** Надпись была зашита в разметку (`v0.1 · DEV`) и
не соответствовала версии сервера (1.3.x). Теперь она берётся из
`GET /api/v1/system` (`paintStatus`), заголовок `Server` тоже формируется из
версии пакета; проверка «версия в шапке берётся с сервера» в `tools/ui_check.mjs`.

**Проверка интерфейса на чистой установке.** `tools/ui_check.mjs` падал на 422
«Не указан research_id», если в БД нет исследований (только что распакованный
образ). Теперь проверка сама создаёт демо-исследование, дожидается 12 этапов и
продолжает; на пустой БД Windows-образа пройдено **75/75**.

**Сборка.** `tools/build_exe.py --verify-linux` — воспроизводимая проверка образа
без wine: побайтовое совпадение ресурсов с исходными, типы содержимого, отдача
интерфейса, журнал загрузки, 404 на отсутствующий ресурс и приёмочные тесты из
каталога `app` самого образа. Результат пишется в `release/BUILD-INFO.json`
(`linux_verification`), а не вносится вручную. Консоль 7-Zip ищется и под именем `7zz`.

### Прогоны редакции 1.3.1 (фактические)

| Набор | Результат |
|---|---|
| `python3 -m unittest discover -s tests -t .` | **150/150** |
| `tools/api_check.py` по ролям admin / lead / analyst / expert / observer / auditor | **96 / 96 / 94 / 94 / 93 / 94** — все пройдены |
| `tools/api_check.py --run` (создание → 12 этапов → отчёт → выгрузки) | **108/108** |
| `node tools/ui_check.mjs` | **75/75** |
| Образ Windows под wine (`--verify-wine`) | CPython 3.11.9, API 200, ресурсы **8/8** |
| Цепочка запуска образа (`--verify-launch`) | `cmd.exe /c isheika.cmd` → HTTP 200, интерфейс 200 |
| Тесты внутри образа Windows (`--verify-tests`) | **150/150** |
| Проверка образа на Linux (`--verify-linux`) | ресурсы **8/8** побайтово, журнал загрузки «исправно», 404 на отсутствующий ресурс, тесты **150/150** |
| Журнал загрузки браузера **в Windows-образе** (jsdom → сервер образа под wine) | все шаги `OK`, в том числе «Объект Charts — загружен: 12 функций инфографики»; `failed=false`, экран журнала скрыт, форма входа показана |
| `node tools/ui_check.mjs --base <образ под wine>` на **пустой БД** | **75/75** (демо-исследование создано самой проверкой, 12 этапов выполнены) |

Артефакт: `release/ISHEIKA-NTR-AI.exe`, версия 1.3.1; контрольная сумма — в
`release/ISHEIKA-NTR-AI.exe.sha256` и `release/BUILD-INFO.json` (в документ сумму
не вписываем: документ входит в образ и меняет его сумму). Дубликат `ISHEIKA-NTR-AI-portable (1).zip` удалён: он
побайтово повторял архив предыдущей сборки (`b613c953…`) и содержал неисправленную
статику — его можно было принять за актуальный образ.

**Восстановление исходников в репозитории.** В загруженном дереве отсутствовали
файлы редакции 1.3.0 (`isheika/boot.py`, `slo.py`, `backup.py`,
`web/screens_ops.js`, `tests/test_boot_static.py`, `test_ops_slo.py`,
`test_release_packaging.py`) и были устаревшие версии `api/server.py`,
`api/service.py`, `config.py`, `storage/*`, `web/index.html`, `web/app.js`,
`web/styles.css`, `tools/*`: ядро собиралось, но давало 112 тестов, 79 маршрутов и
803 источника вместо 144 / 89 / 806. Файлы восстановлены из payload выпущенного
образа `release/ISHEIKA-NTR-AI-portable.zip` (единственный носитель актуальной
редакции), после чего расхождения исчезли. Документ `docs/ACCEPTANCE.md` сохранён
в более новой репозиторной версии.

## Журнал действий и поиск противоречий (редакция 1.4.0, задача пользователя)

**Формулировка задачи:** «доработай программу, чтобы она вела во время работы журнал (лог)
действий, чтобы можно было найти ошибки, баги и противоречия».

Реализация: `isheika/journal.py` (журнал), `isheika/diagnostics.py` (правила противоречий),
таблица `ops_journal` + 7 индексов (миграция `0006_journal`), 8 маршрутов API,
экран **UI-32 «Журнал действий и диагностика»** (M33, право `logs.read`),
приём ошибок браузера в `web/app.js` (`reportClient`) и `web/index.html` (FAIL-шаги загрузки).

### Критерии приёмки журнала

| Код | Критерий | Проверка |
|---|---|---|
| JRN-01 | запись несёт `request_id`/`correlation_id` и находится фильтрами уровня, вида, действия | `test_JRN_01` |
| JRN-02 | пароли, токены, ключи, `Bearer …`, `?key=…` не попадают в журнал **на любой глубине** вложенности | `test_JRN_02` |
| JRN-03 | одинаковые падения с разными идентификаторами дают **одну** подпись дефекта | `test_JRN_03` |
| JRN-04 | обёртка действия пишет длительность, при отказе — traceback, и **не глушит** исключение | `test_JRN_04` |
| JRN-05 | сбой записи журнала не роняет операцию и не теряется молча (резервный файл + счётчик) | `test_JRN_05` |
| JRN-06 | минимальный уровень записи и полное отключение журнала соблюдаются | `test_JRN_06` |
| JRN-07 | доменное действие (аудит) видно и в журнале действий | `test_JRN_07` |
| JRN-08 | отказ этапа и предупреждение ИИ попадают в журнал с уровнем и кодом | `test_JRN_08` |
| JRN-09 | ошибка браузера принимается **без входа**, проверяется и ограничивается по частоте | `test_JRN_09` |
| JRN-10 | выгрузка TXT/JSON/CSV содержит записи и не раскрывает секреты | `test_JRN_10` |
| JRN-11 | политика хранения ограничивает журнал по сроку и по объёму | `test_JRN_11` |
| JRN-12 | запись отдаёт контекст своей трассировки; неизвестный идентификатор — 404 | `test_JRN_12` |
| JRN-13 | журнал читает роль с `logs.read`; приём ошибок браузера публичный | `test_JRN_13` |
| JRN-14 | каждое обращение к API даёт запись с методом, кодом и длительностью; путь сводится к шаблону; успешный `GET` — уровень `debug` | `test_JRN_14` |
| JRN-15 | маршруты журнала в контракте OpenAPI 3.1 (канонические ресурсы), RBAC соблюдён | `test_JRN_15` |
| JRN-16 | экран UI-32 подключён к оболочке, защищён правом, содержит фильтры и выгрузку | `test_JRN_16` |

### Критерии приёмки диагностики

Правило проверяется **внесением противоречия** в данные, а не только отсутствием находок
на чистом состоянии; отдельно проверяется, что штатное состояние находок **не даёт**.

| Код | Противоречие | Проверка |
|---|---|---|
| DIA-01a/b/c | «completed» с проваленным этапом; «running» без активных заданий; задание висит > 30 мин | `test_DIA_01` |
| DIA-02 | переход состояния в обход конечного автомата (по истории состояний) | `test_DIA_02` |
| DIA-03 | отчёт «готов», но файлов на диске нет | `test_DIA_03` |
| DIA-04 | утверждение SUPPORTED/PARTIAL без доказательств | `test_DIA_04` |
| DIA-05 | доказательство привязано к чужому исследованию (в т. ч. в области проверки) | `test_DIA_05` |
| DIA-06/07 | класс релевантности не по порогу; не все шесть компонент расчёта | `test_DIA_06_07` |
| DIA-08 | TRL выше уровня с выполненными обязательными критериями (усреднение запрещено) | `test_DIA_08` |
| DIA-09 | неизвестный фактор учтён как число (ИД-02: неизвестное ≠ 0) | `test_DIA_09` |
| DIA-10 | интерпретация разрешена ниже порога покрытия либо запрет не объяснён | `test_DIA_09`, `test_DIA_10_interpretation_allowed_below_coverage_threshold` |
| DIA-11/12 | немонотонная `P(T ≤ t)`; количественный прогноз на 20–50 лет | `test_DIA_11_12` |
| DIA-13 | платный провайдер при запрете платного ИИ (и **не** находка при разрешении) | `test_DIA_13` |
| DIA-14 | расход квоты сверх лимита реестра | `test_DIA_14` |
| DIA-15 | одна подпись дефекта ≥ 3 раз — устойчивый баг | `test_DIA_15` |
| DIA-16 | повторяющиеся ошибки интерфейса | `test_DIA_16` |
| DIA-17 | похожая на секрет строка журнала — критично | `test_DIA_17` |
| DIA-18 | сбои записи журнала не замалчиваются | `test_DIA_18` |
| DIA-19 | версия методики вне реестра; формат «CODE version» из реестра — **не** находка | `test_DIA_19`, `test_DIA_19_registry_version_format_is_not_a_finding` |
| — | отказ одного правила не отменяет остальные (`broken_rules` + запись в журнал); чистое исследование — без находок | `test_DIA_run_survives_broken_rule_and_reports_clean_scope` |

### Ложные находки, обнаруженные прогоном на реальных данных и устранённые

Диагностика прогонялась не только на посеянных противоречиях, но и на исследовании,
прошедшем все 12 этапов. Это выявило **две ложные находки самого анализатора**:

1. **DIA-19** объявляла невоспроизводимым каждый нормальный расчёт: в расчётах версия
   хранится как `«RELEVANCE_V1 1.0.0»` (`analytics/snapshot.py`), а правило сравнивало её
   только с полем `version` реестра (`1.0.0`). Теперь сравниваются оба представления —
   пара `(code, version)` и строка `CODE version`.
2. **DIA-10** считала противоречием штатное поведение: словесная интерпретация
   рассчитывается всегда, а показывает её интерфейс по флагу `interpretation_allowed`
   с предупреждением `coverage_warning`. Теперь находка возникает, только если
   интерпретация **разрешена** ниже порога покрытия (или без оценки) либо запрет
   **не объяснён** предупреждением.

После исправления на реальном исследовании остались только настоящие находки —
повторяющиеся ошибки интерфейса, оставленные самими проверочными сценариями
(`api_check.browser`, `ui_check.test`, `boot.Проверка закрытия`), то есть DIA-15/DIA-16
сработали по назначению. Регрессионные испытания на ложные находки добавлены: `test_DIA_10_interpretation_allowed_below_coverage_threshold`,
`test_DIA_19_registry_version_format_is_not_a_finding`.

### Прогоны редакции 1.4.0 (фактические)

| Набор | Результат |
|---|---|
| `python3 -m unittest discover -s tests -t .` | **185/185** |
| `tools/api_check.py` по ролям admin / lead / analyst / expert / observer / auditor | **112 / 111 / 109 / 109 / 103 / 109** — все пройдены |
| `tools/api_check.py --run` (создание → 12 этапов → отчёт → выгрузки → журнал) | **123–127 / всё пройдено** (число проверок зависит от числа доступных форматов отчёта) |
| `node tools/ui_check.mjs` | **89/89** |
| Образ Windows под wine (`--verify-wine`) | CPython 3.11.9, SQLite 3.45.1, API 200, ресурсы **9/9** |
| Цепочка запуска образа (`--verify-launch`) | `cmd.exe /c isheika.cmd` → HTTP 200, интерфейс 200 |
| Тесты внутри образа Windows (`--verify-tests`) | **185/185** |
| Проверка образа на Linux (`--verify-linux`) | ресурсы **9/9** побайтово, журнал загрузки «исправно» (миграция `0006_journal` применена, 97 маршрутов), 404 на отсутствующий ресурс, тесты **185/185** |
| `node tools/ui_check.mjs --base <образ под wine>` на **пустой БД** | **89/89**, включая экран UI-32 и приём ошибки интерфейса сервером образа |
| Диагностика на исследовании, прошедшем 12 этапов (образ под wine, пустая БД) | **0 находок** — ложных срабатываний нет; журнал образа: 33 записи, 3 ошибки браузера, 0 сбоев записи |

Артефакт: `release/ISHEIKA-NTR-AI.exe`, версия 1.4.0; контрольная сумма — в
`release/ISHEIKA-NTR-AI.exe.sha256` и `release/BUILD-INFO.json` (в документ сумму
не вписываем: документ входит в образ и меняет его сумму).

**Изменения в проверочных инструментах.** `tools/ui_check.mjs` теперь выбирает
исследование **с документами**, а не просто самое свежее: пустое исследование,
созданное проверкой API, приводило к ложным отказам экранов «Документ» и «Граф связей».

## ИД-14. Недоступность сервера не восстанавливалась сама (редакция 1.4.1, замечание пользователя)

**Что сообщил пользователь:**

1. «Ошибка `E_NETWORK`. Сервер недоступен. Проверьте соединение — данные могли устареть.
   Сетевая недоступность. Результаты могут быть частичными. этап: UI-24 · request_id: req-iik4c5wm».
2. «Журнал работы и журнал действий и диагностика недоступен».

**Разбор.** Сервер и оба экрана были исправны: проверено прямыми запросами к живому
серверу — `GET /api/v1/logs?kind=all&limit=400` → 200 (310 КБ, 18 мс),
`GET /api/v1/journal?limit=300` → 200 (271 КБ, 9 мс), `/journal/stats`, `/journal/errors`,
`/diagnostics` → 200; в журнале сервера нет ни одного отказа по этим маршрутам,
а `request_id` из сообщения пользователя на сервере **отсутствует** — значит запрос
до сервера не дошёл. Отказ возник на участке браузер ↔ сервер (остановленный или
перезапускающийся процесс, ответ шлюза), и **интерфейс не восстанавливался сам**:

* `api()` не повторял запрос и не различал ответ шлюза (502/503/504 с чужим телом)
  и ответ API;
* при отказе `S.online = false`, но пробы сервера не было — экран оставался с ошибкой
  до перезагрузки страницы; именно это пользователь видел на UI-24 и UI-32;
* `reportClient()` после первой неудачной отправки ставил `jrnMuted = true` **навсегда** —
  то есть журнал терял именно те ошибки, которые случались при недоступности сервера.

**Исправлено (ред. 1.4.1).**

| Что | Как |
|---|---|
| Повтор запросов | безопасные (`GET`/`HEAD`) и идемпотентные (`Idempotency-Key`) — до 3 попыток с растущей паузой; изменяющие не повторяются |
| Ответ шлюза | 502/503/504 без тела API → `E_NETWORK` с указанием HTTP-кода, а не «E_INTERNAL HTTP 502» |
| Автопереподключение | проба `GET /api/v1/system` по таймеру 4 с → 15 с; при успехе экран перерисовывается сам, всплывает уведомление |
| Очередь журнала | недоставленные события в `localStorage` (`isheika.journal.queue`, ≤ 50), досылка после восстановления с `queued_at`; вечный запрет отправки удалён |
| Строка состояния | «недоступно — переподключение, попытка N · событий журнала в очереди: M» |
| Экран журнала | отказ сводки не лишает ленты (`Promise.allSettled` + предупреждение); вкладка «Ошибки браузера» показывает очередь и кнопку «Отправить очередь» |
| Блок ошибки | кнопки «Повторить» и «Переподключиться», пояснение про автоповтор и очередь |
| Сервер | `journal.client_event` сохраняет `client.queued_at` и `delivered_with_delay` — задержка доставки видна и не путается со «свежим» отказом |

### Критерии приёмки

| Код | Критерий | Проверка |
|---|---|---|
| NET-01 | безопасный запрос повторяется, изменяющий — нет | `test_NET_01`, «сеть: безопасный запрос повторяется сам» |
| NET-02 | ответ шлюза 502/503/504 без тела API — недоступность | `test_NET_02`, «сеть: ответ шлюза 502 распознан как E_NETWORK» |
| NET-03 | автопереподключение с растущей паузой и перерисовкой экрана | `test_NET_03`, «сеть: восстановление происходит само по таймеру» |
| NET-04 | отказ доставки не отключает журнал; событие ждёт в очереди и досылается | `test_NET_04`, «журнал: событие сохранено в очереди браузера», «журнал: очередь дослана с отметкой queued_at» |
| NET-05 | строка состояния показывает недоступность, попытку и очередь | `test_NET_05` |
| NET-06 | блок ошибки даёт повтор и переподключение | `test_NET_06` |
| NET-07 | экран журнала переживает частичный отказ | `test_NET_07` |
| NET-08 | вкладка «Ошибки браузера» показывает очередь и досылает её | `test_NET_08` |
| JRN-17 | сервер сохраняет время постановки в очередь | `test_JRN_17` |

### Прогоны редакции 1.4.1 (фактические)

| Набор | Результат |
|---|---|
| `python3 -m unittest discover -s tests -t .` | **194/194** |
| `node tools/ui_check.mjs` | **98/98**, в том числе 9 проверок недоступности и восстановления |
| `tools/api_check.py --run` | все проверки пройдены |
| Образ Windows (`--verify-wine`, `--verify-launch`, `--verify-tests`) | ресурсы **9/9**, цепочка запуска 200, тесты внутри образа **194/194** |
| Проверка образа на Linux (`--verify-linux`) | ресурсы **9/9** побайтово, журнал загрузки «исправно», тесты **194/194** |
| `node tools/ui_check.mjs --base <образ под wine>` на **пустой БД** | **98/98**, включая очередь журнала и автоматическое восстановление связи |

Артефакт: `release/ISHEIKA-NTR-AI.exe`, версия 1.4.1; контрольная сумма — в
`release/ISHEIKA-NTR-AI.exe.sha256` и `release/BUILD-INFO.json`.

## ИД-15. Дефекты, найденные по журналу с машины пользователя (редакция 1.4.2)

Пользователь прислал `journal.json` (выгрузка UI-32) и `isheika-log.txt` (лог событий,
состояний и аудита) со своей машины: Windows, `%LOCALAPPDATA%\IsheikaNTR-AI`, версии
1.4.0 и 1.4.1. Журнал действий сработал по назначению — по записям, подписям дефектов
и traceback найдены **три настоящих дефекта**, которые не воспроизводились автотестами.

### Что было в журнале

| Время | Запись | Подпись | Что означало |
|---|---|---|---|
| 17:19:23 | `error workflow stage.source_search` · `E_INTERNAL` · `'parsed_query'` | `603cff37826ac92b` | этап 3 упал при **попытке 2** (продолжение исследования) |
| 17:19:23 | `error browser render.monitor` · `Cannot set properties of null (setting 'innerHTML')` | `4feab91dc5141042` | отказ отрисовки UI-23 (`screens_registry.js:555`) |
| 17:18:55, 17:37:55 | `error browser render.dashboard` · то же сообщение | `949fa65b1fb3c1d2` | отказ отрисовки UI-01 **сразу после входа** (`screens_core.js:82`) |
| 17:18:49 | `error workflow system.error` · `COMPONENT_DOWN` · `FileNotFoundError … '.slo-probe'` | — | ложный алерт отказа хранилища |
| 17:18:50, 17:37:52 | `warn api GET /api/v1/auth/me` · `E_AUTH` 401 | — | **норма**: восстановление сессии до входа |
| 16:24:58 | `warning search.source_failed CON-OPENAIRE` · `E_NETWORK` | — | **норма**: таймаут внешнего источника, помечен повторимым |

### Причины и исправления

**1. Продолжение исследования падало на этапе 3 (`KeyError: 'parsed_query'`).**
`_run_stages` начинает с пустого контекста; завершённые этапы пропускаются и кладут
в контекст только сохранённый результат, а живые объекты (`parsed_query`, `expansion`)
создаются лишь при фактическом выполнении этапа. Этапы 3 и 5 брали их напрямую.
Исправлено в `workflow/pipeline.py`: восстановители `_parsed_query`, `_expansion`
(из сохранённой модели запроса, включая ветви), `_run_id` (незавершённый запуск
воспроизводимости продолжается, а не остаётся «running»).

**2. Параллельные отрисовки одного экрана.** `afterLogin` устанавливал
`location.hash` (это вызывает отрисовку по `hashchange`) и **сам** вызывал отрисовку.
Две отрисовки шли параллельно: вторая подменяла разметку, первая после ожидания
запроса писала в отсоединённый узел → `null.innerHTML`. Исправлено в `web/app.js`:
очередь отрисовок с объединением повторных вызовов (`RENDER.seq`/`chain`), проверка
устаревания (`stale(body)`), безопасная запись `App.setHTML`, снятие слушателей
экрана при любой перерисовке (`App.onCleanup`). Все экраны переведены на `setHTML` —
небезопасных записей `document.getElementById(...).innerHTML` не осталось.

**3. Гонка проб хранилища.** Планировщик, самопроверка загрузки и запрос
`POST /api/v1/slo/probes` писали и удаляли **один и тот же** файл `.slo-probe`.
На Windows это давало `FileNotFoundError` и ложный алерт `COMPONENT_DOWN`.
Исправлено в `slo.py`: уникальное имя пробы, проверка записи чтением, удаление
терпимо к отсутствию файла, каталог создаётся явно.

**4. Видимость противоречия в сводке этапа 4.** В журнале: `documents_total 91,
unique 0, duplicates 91`. Это не ошибка расчёта: «дубль» означает «документ уже
известен общему корпусу», в том числе из другого исследования (повторный запрос
«6G»). Чтобы сводка не читалась как противоречие, добавлены `new_in_corpus` и
`known_before`, а сообщение этапа поясняет, сколько документов были известны ранее.

### Критерии приёмки

| Код | Критерий | Проверка |
|---|---|---|
| RES-01 | этап 3 выполняется при пустом контексте (запрос из состояния) | `test_RES_01` (до исправления — `KeyError`) |
| RES-02 | этап 5 выполняется при пустом контексте | `test_RES_02` |
| RES-03 | расширение восстанавливается из сохранённой модели, включая ветви | `test_RES_03` |
| RES-04 | продолжение после сбоя этапа 3 доходит до конца без `parsed_query` | `test_RES_04` |
| RES-05 | незавершённый запуск воспроизводимости закрывается | `test_RES_05` |
| RES-06 | сводка различает новые и ранее известные документы, суммы сходятся | `test_RES_06` |
| RND-01 | отрисовки сериализованы, повторные объединяются | `test_RND_01` |
| RND-02 | устаревшая отрисовка не пишет в DOM и не считается дефектом | `test_RND_02` |
| RND-03 | ни один экран не пишет `innerHTML` без проверки узла | `test_RND_03` |
| RND-04 | слушатели экрана снимаются при любой перерисовке | `test_RND_04` |
| RND-05 | `setHTML`/`stale`/`onCleanup` опубликованы | `test_RND_05` |
| SLO-09 | 24 параллельные пробы хранилища — ни одного ложного отказа | `test_SLO_09` |
| — | вход в систему с параллельными вызовами отрисовки не ломает UI-01 | «отрисовка: параллельные вызовы не ломают экран» |
| — | событие SSE после перерисовки UI-23 не даёт ошибки | «отрисовка: событие после перерисовки не даёт ошибки» |

### Прогоны редакции 1.4.2 (фактические)

| Набор | Результат |
|---|---|
| `python3 -m unittest discover -s tests -t .` | **206/206** |
| `node tools/ui_check.mjs` | **101/101** |
| `tools/api_check.py --run` | **127/127** |
| Образ Windows (`--verify-wine`, `--verify-launch`, `--verify-tests`) | ресурсы **9/9**, цепочка запуска 200, тесты внутри образа **206/206** |
| Проверка образа на Linux (`--verify-linux`) | ресурсы **9/9** побайтово, журнал загрузки «исправно», тесты **206/206** |
| `node tools/ui_check.mjs --base <образ 1.4.2 под wine>` на **пустой БД** | **101/101**, включая вход с параллельными отрисовками и событие после перерисовки |

Артефакт: `release/ISHEIKA-NTR-AI.exe`, версия 1.4.2; контрольная сумма — в
`release/ISHEIKA-NTR-AI.exe.sha256` и `release/BUILD-INFO.json`.

## ИД-16. Отказ проверки сертификата источника (редакция 1.4.3)

Пользователь прислал вторую выгрузку с рабочей машины: `journal.txt` (журнал действий,
34 записи) и `1_isheika-log.txt` (события, состояния, аудит) — Windows, версии
1.4.0…1.4.2. Выгрузка подтверждает исправления ИД-15 и вскрывает один новый дефект
поставки.

### Что было в журнале

| Время | Запись | Что означало |
|---|---|---|
| 17:19:23 | `error workflow stage.source_search` · `KeyError: 'parsed_query'` | дефект ИД-15 на версии **1.4.1** (до обновления) |
| 17:18:55, 17:37:55, 18:19:42 | `error browser render.dashboard` / `render.monitor` · `null.innerHTML` | дефект ИД-15 на версиях **1.4.0/1.4.1** (до обновления) |
| 18:57:50 | `action research.start` → `job.started` | запуск на версии **1.4.2** |
| 18:58:00 | `job.completed` · `sources_planned 17, sources_ok 14, documents_found 106`, `research.completed` | **ИД-15 закрыт**: исследование дошло до конца, `parsed_query` не падает |
| 18:57:50 | `search.source_failed CON-USPTO-ODP` · `E_POLICY` (RESTRICTED) | **норма**: источник требует ключа |
| 18:57:51 | `search.source_failed CON-S2AG` · `E_POLICY` HTTP 403 | **норма**: источник требует ключа |
| 18:57:52…18:58:00 | `search.source_failed CON-ARXIV` · `E_NETWORK` · `SSL: CERTIFICATE_VERIFY_FAILED … unable to get local issuer certificate` | **дефект поставки**: три одинаковых отказа подряд |

Ошибок отрисовки после 18:57 нет — исправления ИД-15 на машине пользователя работают.

### Причина и исправление

Сертификат `export.arxiv.org` подписан удостоверяющим центром **«Certainly Root R1/E1»**.
Встраиваемый CPython в Windows-сборке доверял только хранилищу сертификатов ОС; этого
корня там не было (автообновление корней не доставило его), поэтому запрос обрывался
на проверке сертификата. Сеть исправна: в браузере тот же адрес открывается, а в Linux
источник отвечал — корень есть в системном наборе.

1. **Собственный набор корней в поставке.** `isheika/data/cacert.pem` — корни Mozilla
   NSS (150 сертификатов, MPL-2.0, снимок 2026-11-24). Загружается вместе с системным
   доверием в `isheika/tls.py`; контекст единый для поискового контура
   (`search/http.py`, включая `robots.txt`) и адаптеров ИИ (`ai/adapters.py`).
   Контрольный опыт: контекст **только** на этом наборе, без системного доверия,
   получает от `export.arxiv.org` **HTTP 200**; контекст с пустым доверием
   воспроизводит сообщение пользователя дословно.
2. **Свой набор оператора.** `ISHEIKA_CA_BUNDLE=<файл .pem>` добавляет корни
   корпоративного прокси или своего УЦ. Проверка сертификатов **не отключается**:
   `check_hostname=True`, `verify_mode=CERT_REQUIRED`, небезопасного режима нет.
3. **Отказ не повторяется впустую.** Проверка сертификата не лечится повтором, поэтому
   `E_NETWORK` поднимается с `retryable=False` и пояснением `details.tls_hint`
   (что проверить и как подключить свой набор). В журнале одна запись вместо трёх.
4. **Видимость состояния доверия.** Самопроверка загрузки «Доверенные сертификаты на
   месте» (число корней системных и приложения), строка «Доверие сертификатам» в окне
   журнала загрузки, поле `tls` в `/api/v1/boot-log` (только счётчики, без путей),
   правила диагностики **DIA-20** «Источник не прошёл проверку сертификата» и
   **DIA-21** «Набор корневых сертификатов не найден».

### Критерии приёмки

| Код | Критерий | Проверка |
|---|---|---|
| TLS-01 | набор корней поставляется с приложением (≥100 сертификатов), проверка сертификатов обязательна | `test_TLS_01` |
| TLS-02 | запрос к серверу с неизвестным УЦ падает — воспроизведение отказа пользователя | `test_TLS_02` (локальный HTTPS-сервер, `tests/fixtures/tls`) |
| TLS-03 | тот же запрос проходит с `ISHEIKA_CA_BUNDLE`, проверка остаётся включённой | `test_TLS_03` (до исправления — отказ) |
| TLS-04 | отказ сертификата неповторим, несёт пояснение, в журнале одна запись | `test_TLS_04` (до исправления — 3 записи, `retryable=True`) |
| TLS-05 | состояние доверия видно в журнале загрузки и в диагностике (DIA-20), ложной DIA-21 нет | `test_TLS_05` |
| — | окно журнала загрузки показывает число доверенных корней | «журнал загрузки: видно состояние доверия сертификатам» |

Испытания используют настоящий TLS-сервер на тестовом удостоверяющем центре
(`tests/fixtures/tls`, ключи тестовые, никому не доверенные). Защита от SSRF
в испытании локального адреса подменяется только на время запроса — в рабочем
контуре она остаётся запрещать loopback.

### Прогоны редакции 1.4.3 (фактические)

| Набор | Результат |
|---|---|
| `python3 -m unittest discover -s tests -t .` | **211/211** |
| `node tools/ui_check.mjs` | **102/102** |
| `tools/api_check.py --run` | **127/127** |
| Контрольный опыт вне автотестов | контекст только на наборе приложения → `export.arxiv.org` **HTTP 200**; контекст с пустым доверием → дословное сообщение пользователя |
| Образ Windows (`--verify-wine`, `--verify-launch`, `--verify-tests`) | ресурсы **9/9**, цепочка запуска 200, тесты внутри образа **211/211**, самопроверка «Доверенные сертификаты на месте» — 150 сертификатов набора |
| Проверка образа на Linux (`--verify-linux`) | ресурсы **9/9** побайтово, журнал загрузки «исправно», тесты **211/211** |
| `node tools/ui_check.mjs --base <образ 1.4.3 под wine>` на **пустой БД** | **102/102** |

Артефакт: `release/ISHEIKA-NTR-AI.exe`, версия 1.4.3, 10 181 383 байта; sha256
`bcc5128fdd5b0f7d338d5e4e8ae7ce550c163a1fb83e618a3610cae9babc9b34` — также в
`release/ISHEIKA-NTR-AI.exe.sha256` и `release/BUILD-INFO.json`.


---

## Редакция 1.5.0. Технический перевод и исправления по полным прогонам

Основание — требование заказчика: исправить ошибки, обеспечить технический перевод
найденной НТ-информации на русский язык и прогнать программу целиком на живых источниках.
Дефекты ИД-18…ИД-20 найдены **собственными полными прогонами**, а не по журналу пользователя.

### ИД-18. Короткие обозначения терялись при разборе запроса

| Наблюдение (прогон 1.4.3/1.5.0-dev, запрос «6G») | Разбор |
|---|---|
| `search_model` → `tokens: []`, `object_terms: []` | `tokenize` отбрасывал слова длиной ≤ 2 |
| 76 найденных материалов, 0 включённых, 0 доказательств | все оценки `BELOW_THRESHOLD`, S = T = K = 0 |
| TRL 1, F по умолчанию | расчётное ядро получило пустую доказательную базу |

Исправление: `SHORT_TECH` (6g, 5g, thz, rf, mimo, ris, isac, …), новый `tokenize`
(длина > 2 **или** короткое обозначение **или** шаблон «цифры + буквы»), сущности
`mobile_generation`, `terahertz`, `ris`, `isac`, ветви тезауруса RU/EN, назначение
`communication` для 6g/5g/imt-2030. Порог релевантности **не менялся**.

Испытания QRY-01…QRY-03 (`tests/test_query_terms.py`). До правки QRY-01 падал
(`tokens` пуст), после — проходит.

### ИД-19. Документовский токенизатор не видел коротких обозначений

Контрольный опыт на живом корпусе (67 материалов по «6G», после ИД-18 включался 1):

| Документ | S | K | R | Класс |
|---|---|---|---|---|
| The ITU Vision and Framework for 6G: Scenarios, Capabilities, and Enablers | 0.064 | 0.027 | 0.531 | BELOW_THRESHOLD |
| Complexation-Induced Ring Opening of a Rhodamine 6G-Pyridoxal Schiff Base Probe | 0.000 | 0.000 | 0.510 | BELOW_THRESHOLD |

Причина: `relevance._WORD = {3,}` — запрос и документ разбирались **по разным правилам**,
обозначение «6g» не попадало в термины документа, ядро не подтверждалось.

Исправление: единое правило токенизации (`_terms_of` использует `SHORT_TECH` и тот же
шаблон), плюс защита от омонимов `AMBIGUOUS_SHORT`: обозначение засчитывается только при
независимом подтверждении предметной области (иное слово/фраза ядра либо ключ сущности
или назначения, не совпадающий с самим обозначением). После правки:

| Документ | S | K | R | Класс |
|---|---|---|---|---|
| The ITU Vision and Framework for 6G | 0.92 | 0.89 | **0.874** | DIRECT |
| A Broader Survey on 6G Radio Resource Management | 0.92 | 0.76 | **0.862** | DIRECT |
| Rhodamine 6G-Pyridoxal Schiff Base Probe | 0.06 | 0.03 | 0.281 | BELOW_THRESHOLD (gate не пройден) |
| Rhodamine 6G based fluorescent chemosensor for sensing of Fe3+ | 0.06 | 0.03 | 0.281 | BELOW_THRESHOLD (gate не пройден) |

Испытания QRY-04…QRY-05. QRY-04 до правки падал (S = 0.064, класс BELOW_THRESHOLD).

### ИД-20. Гонка параллельной записи обнаружений

Симптом — **плавающий** провал `tests/test_system.WorkflowTests.test_resume_keeps_completed_stages`
на полном наборе (примерно 1 прогон из 4): этап `ai_tasks` при продолжении получал
`attempts` 2 вместо 1. Разбор показал цепочку:

1. две ветви одного источника (`CON-SIM` в испытании, живые ветви в работе) находят один URL;
2. проверка «есть ли вхождение/блоб» и вставка не атомарны → `UNIQUE constraint failed:
   content_occurrences.research_id, content_occurrences.source_code, content_occurrences.canonical_url`
   (и аналогично `content_blobs.content_sha256`);
3. исключение роняет **весь источник** в `failed` → этап `source_search` = `partial`;
4. при продолжении этап выполняется заново, результат меняется → по ИД-17 пересчитываются
   этапы 4–12 (это поведение верное, неверной была потеря источника).

Воспроизведение вне испытаний: 12 последовательных прогонов CON-SIM дали 11 `completed`
и 1 `partial` с дословной ошибкой UNIQUE.

Исправление: `dedup._insert_idempotent(table, data, lookup_sql, params)` — при нарушении
UNIQUE запись переиспользуется (её создал соседний поток). Применено на всех уровнях:
`content_blobs` (по `content_sha256`), `content_documents` (по `logical_key`, включая ключ
версии), `content_clusters` (по `cluster_key`), `content_occurrences` (по паре
исследование/источник/канонический URL).

Испытания OCC-01…OCC-02 (`tests/test_occurrence_race.py`): OCC-01 воспроизводит окно гонки
детерминированно (предпроверка «не видит» строку) — до правки падал с той же ошибкой
`sqlite3.IntegrityError`, после — проходит; OCC-02 — 6 потоков через барьер на одном URL.
Полный набор после правки: **8 прогонов подряд без провалов**.

### Технический перевод НТ-информации (этап 4)

Испытания TRN-01…TRN-10 (`tests/test_translation.py`): определение языка по полям, защита
DOI/URL/формул/обозначений, согласование прилагательных, покрытие и список непереведённых
слов, кэш по `source_hash`, запрет имитационного провайдера, `review_required=1`,
отражение перевода в отчёте и API. Глоссарий **G-1.7.0**, 1366 слов; однобуквенные токены
в подсчёте покрытия не участвуют.

### Прогоны редакции 1.5.0 (фактические, живые источники)

Профиль DEV, сеть включена, `include_simulation=false`, `max_docs_per_source=8`,
страны RU US CN DE JP KR FI SE GB FR. Все 12 этапов завершены, этап поиска — `partial`
(источники без ключей / 403 / 429 — фиксируется явно).

| Показатель | «тропосферная связь за горизонтом» | «6G» | «терагерцовая связь и совмещённое зондирование» |
|---|---|---|---|
| Документов | 59 | 67 | 74 |
| Включено / DIRECT / ADJACENT | 32 / 12 / 20 | **35 / 31 / 4** | 29 / 18 / 11 |
| Доказательств / утверждений | 112 / 37 | 124 / 42 | 99 / 39 |
| Переведено / покрытие | 61 / 0.782 | 72 / 0.757 (+2 original 1.0) | 80 / 0.697 (+6 original 1.0) |
| TRL / уверенность | 3 / 0.853 | 3 / 0.842 | 3 / 0.797 |
| Реализуемость F | 75.83 | 66.25 | 80.0 |
| Барьеры / альтернативы / тренды / точки прогноза | 5 / 2 / 4 / 72 | 6 / 3 / 4 / 72 | 6 / 1 / 4 / 72 |
| Исследование | `res-ee2a980c-b622-4c21-9f54-1341e4bf5962` | `res-f8c71519-0451-468f-b20f-c94de9b071d6` | `res-e17ec4de-7cde-40a6-ad7d-d632aed1c692` |
| Отчёт (8 форматов, `ready`) | `rep-edb02454-86d4-4ed9-8336-b7e04c31c0ca` | `rep-9e93767d-60df-4156-9a04-4cd2346d6d2b` | `rep-a3a8646d-18ee-4608-96e7-1e63f6db0ca0` |

Динамика по запросу «6G»: 1.4.3 — 0 включённых / 0 доказательств; после ИД-18 — 1 / 1;
после ИД-19 и ИД-20 — **35 включённых, 31 прямого соответствия, 124 доказательства, 42 утверждения**.

Метрики качества поиска на живом корпусе не вычисляются (нет эталонной разметки) —
в отчёте стоит явное «не оценивалось», а не подстановка значения.

| Набор | Результат |
|---|---|
| `python3 -m unittest discover -t . -s tests -q` | **232/232**, 8 повторных прогонов подряд — без провалов |
| `python3 tools/api_check.py --base http://127.0.0.1:8000 --run` | **127/127** |
| `node tools/ui_check.mjs --base http://127.0.0.1:8000` | **102/102** |
| Образ Windows под wine (`--verify-wine`) | Python 3.11.9, SQLite 3.45.1, API **200**, ресурсы **9/9** |
| Цепочка запуска `cmd.exe /c isheika.cmd` (`--verify-launch`) | HTTP **200**, интерфейс **200** |
| Приёмочные тесты внутри образа (`--verify-tests`) | **232/232** (29.1 с под wine) |
| Проверка образа на Linux (`--verify-linux`) | ресурсы **9/9** побайтово, журнал загрузки «исправно» (7 проверок), тесты **232/232**, отсутствующий ресурс → 404 |

Артефакт: `release/ISHEIKA-NTR-AI.exe`, версия **1.5.0**, 10,217,703 байта; sha256
`18ec1b1c7476caa4c019ae4e883c2ff817683b1920ac03a2aaff33efe5638cf1` — также в `release/ISHEIKA-NTR-AI.exe.sha256` и `release/BUILD-INFO.json`.
Запасной вариант — `release/ISHEIKA-NTR-AI-portable.zip`.

Артефакты прогонов (отчёты в 8 форматах, CSV документов/доказательств/утверждений) вынесены
в каталог `results/` рабочей области, сводка — `results/СВОДКА-1.5.0.md`.


---

## Редакция 1.5.1. Разбор третьей выгрузки журнала с машины пользователя

Материал: `2_journal.txt` (217 записей, 17:18…21:28) и `3_isheika-log.txt`
(события, аудит, обращения к источникам, история состояний). На машине — 1.5.0.

### Что подтвердилось исправленным

| Дефект | Признак | Вывод |
|---|---|---|
| ИД-15 `'parsed_query'` | последняя запись 17:19:23 (до обновления); после 18:57 все 12 этапов проходят | закрыт |
| ИД-15 `null.innerHTML` | последние записи 18:19:42; после обновления ошибок отрисовки нет | закрыт |
| ИД-17 пересчёт | 21:27:16 `workflow.recompute` — сброшены 9 зависимых этапов после изменения `source_search` | работает |
| Перевод | 21:27:16 и 21:28:06 `translation.run` — «107 из 107 (ИИ 0, терминология 107)» | работает |
| Прогон 21:27 | источников 17 / успешно 15 / найдено 114; событий severity=error **нет** | прогон чистый |

### ИД-21. Отмена запроса выдавалась за недоступность сервера

Наблюдение: в 21:26:55 ≈50 запросов данных записаны как `E_NETWORK`
(`/system` ×22, `/researches`, `/documents`, `/claims`, `/logs`, `/journal`,
`/sources/stats`, `/document-clusters`, `/analytics/…` и отрисовки 9 экранов).

Разбор: в ту же секунду сервер принял ≈50 `POST /api/v1/journal/client` — все
HTTP 200 за 0.2…0.8 мс, и **ни одного** запроса данных не получил. Сервер был жив
до и после (21:24:58, 21:27:15 — успешные `research.start`). Запросы отменены
вкладкой (перезагрузка/закрытие): `fetch` бросает `AbortError`, оболочка считала
его сетевым отказом; журнальные события уходят с `keepalive: true` и переживают
выгрузку — потому дошли только они. Следствие — ложная лавина ошибок и срабатывание
DIA-15/DIA-16 «повторяющийся дефект» (18:58:56) на ровном месте.

Исправление: `E_ABORTED` для отмены без нашего таймера (без записи отказа, без
offline, без ошибки экрана), слушатели `pagehide`/`beforeunload`/`pageshow`,
отдельный текст для `navigator.onLine === false`. Испытания NET-09…NET-13.

### ИД-22. Идемпотентность заявлена, но не реализована

Контрольный опыт на живом сервере **до правки**: два `POST /api/v1/researches`
с одним `Idempotency-Key` → `res-a34007ad-c09a-42fa-a5b9-861fa3dca988` и
`res-dcc03cad-18e4-4c23-baa8-7270391f7f89` — **дубль исследования**, при том что
клиент повторяет такой POST трижды (ключ делает запрос «безопасным»).

Исправление: миграция `0008_idempotency`, таблица `ops_idempotency`, модуль
`api/idempotency.py` (пара актор+маршрут, TTL 24 ч, несовпадение тела → `E_VALIDATION`),
обработка заголовка в диспетчере (обработчик при повторе не вызывается), клиентский
ключ уникален для действия. **После правки** на живом сервере: первый
`res-bd270316-d702-41d7-881f-c332b054a565`, повтор — тот же идентификатор с
`Idempotency-Replayed: true`, другой ключ — `res-a365f3da-49c0-44cd-a58f-65bcc6304a92`.

Испытания IDM-01…IDM-07; IDM-07 (сквозной по HTTP) до правки воспроизводит дубль.

### ИД-23. Выгрузка журнала не содержала деталей

Поля `detail` и `client` (версия приложения, экран, маршрут, окно, `queued_at`,
число попыток, request_id) хранились в `ops_journal`, но TXT/CSV-выгрузка их не
включала — причину отказа по выгрузке установить было нельзя. Добавлены: в TXT —
строка контекста и «детали: {…}», `error_type`, `rid=`; в CSV — 9 колонок.
Испытания JEX-01…JEX-04.

### Не дефекты

`auth/me → 401` до входа (8 раз), `favicon.ico → 404`, `CON-S2AG HTTP 403` (нужен ключ),
ограничение частоты arXiv, `source_search = partial` при 15 успешных из 17 —
ожидаемое поведение, зафиксировано честно.

### Прогоны редакции 1.5.1 (фактические)

| Набор | Результат |
|---|---|
| `python3 -m unittest discover -t . -s tests -q` | **248/248** |
| `python3 tools/api_check.py --base http://127.0.0.1:8000 --run` | **124/124** |
| `node tools/ui_check.mjs --base http://127.0.0.1:8000` | **102/102** |
| Образ под wine (`--verify-wine`) | Python 3.11.9, SQLite 3.45.1, API **200**, ресурсы **9/9** |
| Цепочка запуска `cmd.exe /c isheika.cmd` | HTTP **200**, интерфейс **200** |
| Тесты внутри Windows-образа (`--verify-tests`) | **248/248** (30.0 с) |
| Проверка образа на Linux (`--verify-linux`) | ресурсы **9/9**, журнал загрузки «исправно», тесты **248/248** |

Артефакт: `release/ISHEIKA-NTR-AI.exe`, версия **1.5.1**, 10,224,730 байта;
sha256 `bf9e7aabb6dcfb3f84fb1e93f6f4907d02c0c8780795296dc0a9ee9ca4319c11`. Миграции: 0001…0008.
Разбор выгрузки для заказчика — `results/РАЗБОР-ЖУРНАЛА-3.md`.


---

## Редакция 1.5.2. Разбор четвёртой выгрузки журнала с машины пользователя

Материал: `3_journal.txt` (281 запись, 24.11 17:18:49Z … 25.11 05:24:55Z),
`isheika-log (1).txt`, `journal_browser.csv`, `journal_errors.csv`. На машине — 1.5.1.
Исследование заказчика: `res-3cd74672-b90b-45ec-b497-9de49898d7c7`, запрос «бшпд».

### Что подтвердилось исправленным

| Дефект | Признак | Вывод |
|---|---|---|
| ИД-21 отмена запроса | новых лавин `E_NETWORK` нет; 22 записи `/system` — 24.11 21:26:55 (до обновления) | закрыт |
| ИД-23 выгрузка | в TXT есть `детали: {…}`, `rid=`, версия/экран/маршрут | работает |
| ИД-17 пересчёт | повторные прогоны пересчитывают зависимые этапы | работает |
| Перевод | `translation.run` — 15 из 15 (ИИ 0, терминология 15) | работает |

### ИД-24. Повторный прогон удваивал утверждения

Пять прогонов: **8 → 16 → 24 → 32 → 40** утверждений, доказательств 0. Причина —
`_claims_from_agent` и `_claims_from_documents` вставляли новые записи без естественного
ключа. Исправление — `upsert_claim` (исследование, раздел, текст), статус проверки и связи
сохраняются. Испытания CLM-01…CLM-03.

### ИД-25. Собственный корпус показывался как «дубли»

Со второго прогона — «уникальных 0, дублей 15»: вхождение проверялось после решения
о статусе документа, и повтор своего же URL помечал документ дубликатом самого себя.
Проверка перенесена в начало `store`. Испытания DED-01…DED-03.

### ИД-26. Диагностика сигнализировала о дефектах прежних версий

Проверка 25.11 05:24:54/55 в версии 1.5.1: DIA-15 (5 случаев) и DIA-16 (8 случаев) —
все основания из 24.11 (версии 1.4.x/1.5.0). Введено окно текущей версии; история
показывается справкой `info`, не считается противоречием и не пишется предупреждением.
Испытания DGW-01…DGW-05.

### ИД-27. OpenAIRE потерян (HTTP 405)

Тело ответа: `{"message":"No static resource v1/researchProducts.","error":"Method Not Allowed"}`.
Живые пробы 25.11.2026: `graph/v1/*` — 405 на всех запросах; `search/researchProducts?format=json`
— 200; `keywords` с `OR` — 409; кириллица — 409; 4 узкие фразы — 0 записей, 2 терма — 5.
Коннектор переведён на рабочий контур с разбором OAF, отбором латинских термов без операторов,
ослаблением узкого запроса и одним повтором при плавающем 409; запасной путь Graph API сохранён;
реестр `CON-OPENAIRE` обновлён; язык приводится к ISO 639-1. Испытания OAF-01…OAF-10.

### ИД-28. Повторный прогон удваивал доказательства

Найдено **собственной живой проверкой** после правки ИД-24: утверждения 42 → 42,
доказательства 120 → **240**. Пара «утверждение — документ» сделана уникальной,
доказательство пересчитывается. Испытание EVD-01.

### Регрессионные испытания воспроизводят дефекты до правки

Обратные правки (возврат поведения 1.5.1) на тех же испытаниях: **21 из 22 падает** —
CLM-01…03, EVD-01, DED-01, DED-03, DGW-01…05, OAF-01…10. Единственное проходящее —
DED-02 (контроль: настоящий дубль из другого исследования помечается `DUPLICATE`).
После восстановления правок — **22/22** проходят.

### Не дефекты

`CON-S2AG` 403 / 429 (ключ, ограничение частоты), `CON-ZENODO` и `CON-NTRS` 403,
`CON-USPTO-ODP` RESTRICTED, DIA-20 (действительные отказы проверки сертификата),
`simulated_responses` (нет ключа провайдера), прогноз `NOT_CALIBRATED`,
15 материалов «бшпд» ниже порога — сокращение не раскрыто, англоязычная ветвь не строится.
Рекомендация заказчику и задача на предупреждение — в `ROADMAP.md`.

### Прогоны редакции 1.5.2 (фактические)

| Набор | Результат |
|---|---|
| `python3 -m unittest discover -t . -s tests -q` | **270/270** |
| `python3 tools/api_check.py --base http://127.0.0.1:8000 --run` | **128/128** |
| `node tools/ui_check.mjs --base http://127.0.0.1:8000` | **102/102** |

Живые прогоны (сеть, `include_simulation=false`, `max_docs_per_source=8`, 10 стран),
каждая тема — **два прогона подряд**:

| Запрос | Документов | DIRECT / ADJACENT / ниже порога | Утверждения 1→2 | Доказательства 1→2 | TRL (уверенность) | Реализуемость | OpenAIRE |
|---|---|---|---|---|---|---|---|
| тропосферная связь за горизонтом | 66 | 18 / 21 / 27 | 37 → 37 | 112 → 112 | 3 (0.91) | 75.83 | 8 (7 новых) |
| 6G | 69 | 33 / 4 / 32 | 42 → 42 | 120 → 120 | 3 (0.842) | 70.0 | 2 (2 новых) |
| терагерцовая связь и совмещённое зондирование | 75 | 20 / 8 / 47 | 40 → 40 | 112 → 112 | 3 (0.89) | 78.08 | 8 (8 новых) |

Идентификаторы: `res-06604778-3271-470a-9823-f45d2903fbda`, `res-577fa210-66bd-45e1-9108-e523b789cd34`,
`res-a497585b-da33-4f1f-bd70-3c03673d74d2`; отчёты `rep-50216889-…`, `rep-8013a6a3-…`, `rep-c1baa040-…`
(статус `ready`, 8 форматов). Источников запланировано 16, успешно 12–13; перевод —
66 / 69 / 75 материалов (терминологический режим, покрытие 0.72…0.85).
Числа — `results/progon-1.5.2.json`, разбор для заказчика — `results/РАЗБОР-ЖУРНАЛА-4.md`.

### Сборка и проверка образа 1.5.2

| Проверка | Результат |
|---|---|
| Образ под wine (`--verify-wine`) | Python **3.11.9**, SQLite **3.45.1**, API **200**, ресурсы **9/9**, журнал загрузки «исправно» |
| Цепочка запуска `cmd.exe /c isheika.cmd` (`--verify-launch`) | HTTP **200**, интерфейс **200** |
| Тесты внутри Windows-образа (`--verify-tests`) | **270/270** (31.6 с) |
| Проверка образа на Linux (`--verify-linux`) | HTTP **200**, интерфейс **200**, ресурсы **9/9**, тесты **OK** |

Артефакт: `release/ISHEIKA-NTR-AI.exe`, версия **1.5.2**, **10 237 808** байт;
sha256 `7e5424971b70d2a750fdfbedfa2171c07c8709462c89de056fb5b15f7f9e9666`.
Миграции: 0001…0008 (новых миграций в 1.5.2 нет — исправления не меняют схему данных).
Запасной вариант: `release/ISHEIKA-NTR-AI-portable.zip`.


---

## Редакция 1.5.3. Разбор пятой выгрузки журнала с машины пользователя

Материал: `4_journal.txt` (316 записей, 24.11 17:18:49Z … 25.11 08:12:08Z),
`4_isheika-log.txt` (2815 событий), `1_journal_browser.csv` (58 строк),
`1_journal_errors.csv` (29 строк). На машине — 1.5.2. Исследования новой сессии:
`res-487faed8-602d-4e03-a497-18954c9222bc` («АКБ Арктика») и
`res-495bc182-6963-4f9b-a543-76961e6e9f1c` («технологии цифровых двойников в системах связи»).

### Что подтвердилось исправленным

| Дефект | Признак | Вывод |
|---|---|---|
| ИД-24/ИД-28 удвоение утверждений и доказательств | `evidence_base`: `created: 29, updated: 0`, повторных прогонов нет | работает |
| ИД-25 «уникальных 0» | `document_processing`: уникальных 9, дублей 4, `new_in_corpus: 13` | работает |
| ИД-26 история версий | DIA-15/16 в выгрузке — записи 24.11 (версии ≤ 1.5.1) | работает |
| ИД-27 OpenAIRE | HTTP 405 нет; `E_POLICY` только на кириллическую ветвь (ограничение источника) | работает |

### ИД-29. Многословная тема склеивалась в одну фразу

`search_model.completed`: `{"branches": 1, "expression": "(\"технологии цифровых двойников системах\")"}` —
одна точная фраза из четырёх слов, без англоязычной ветви и синонимов. Итог: 16 найдено /
13 в корпусе, **1 прямой**, TRL 1, покрытие 0,3. Запасной путь расширения склеивал слова,
а глоссарий G-1.7.0 (где есть пара `digital twin → цифровой двойник`) не использовался.
Исправление: пары соседних слов, англоязычная ветвь из обратного глоссария (отдельные
слова — по И), сущность `digital_twin` в тезаурусе и лексиконе, версия `EX-1.1.0`.
Испытания QRY-01…03, QRY-06.

### ИД-30. arXiv и Stack Exchange строили запрос сами

В адресах обращений: arXiv — `all:"("технологии цифровых двойников системах")"` (скобки и вложенные
кавычки), Stack Exchange — операторы `OR`/`AND` как слова. Оба коннектора переведены
на общий `BaseConnector.terms()`. Испытания ARX-01…02.

### ИД-31. Нераскрытое сокращение — молча пустая выдача

Запрос «бшпд»: ветвь `(бшпд)`, синонимов и перевода нет, все материалы ниже порога,
предупреждений нет. `Expansion.warnings` доводится до журнала (`search_model.warning`),
результата этапа и предпросмотра UI-03. Испытания QRY-04…05 и 4 проверки интерфейса.

### ИД-32. Повторный прогон удваивал оценки релевантности

Найдено **собственной живой проверкой**: два прогона — 134 записи оценки на 67 документов,
распределение классов 55/7/5 → **110/14/10**, список результатов двоился, исключение
документа аналитиком затиралось записью `INCLUDE`. Оценка опознаётся парой
«исследование × документ», пересчитывается; ручное решение сохраняется; метрики качества
и список результатов считаются по документам. Испытания REL-01…05.

### ИД-33. Повторный прогон размножал связи документов

`REVISION_OF` 1 → 2 → 3 → 4 по прогонам, до 6 копий одной пары в базе. Связь опознаётся
тройкой «документ × документ × тип», подтверждение аналитика не понижается до алгоритма,
сводка и граф считают пары. Испытания RLN-01…04.

### Регрессионные испытания воспроизводят дефекты до правки

| Набор | До правки (обратные правки) | После правки |
|---|---|---|
| `tests/test_query_recall.py` (ИД-29…31) | 6 отказов + 1 ошибка из 8 | **8/8** |
| `tests/test_relevance_rerun.py` (ИД-32) | 4 отказа + 1 ошибка из 5 | **5/5** |
| `tests/test_relations_rerun.py` (ИД-33) | 4 отказа из 4 | **4/4** |

Контрольное испытание QRY-06 (распознанная тема не изменилась) проходит в обоих состояниях.

### Не дефекты

`CON-ARXIV` 429 и таймаут 20180 мс, `CON-S2AG` 403 (ключ), `CON-NTRS`/`CON-ZENODO` 403,
`CON-USPTO-ODP` RESTRICTED, `CON-OPENAIRE` `E_POLICY` на кириллицу, 11 агентов `simulated`,
прогноз `NOT_CALIBRATED`, «бшпд» ниже порога (сокращение не раскрыто — теперь с предупреждением).
Отмечено как задача: расхождение кодов отказа `CON-S2AG` (журнал обращения — `E_NETWORK`,
этап — `E_POLICY`).

### Прогоны редакции 1.5.3 (фактические)

| Набор | Результат |
|---|---|
| `python3 -m unittest discover -t . -s tests -q` | **287/287** |
| `python3 tools/api_check.py --base http://127.0.0.1:8000 --run` | **127/127** |
| `node tools/ui_check.mjs --base http://127.0.0.1:8000` | **106/106** |

Живые прогоны (сеть, `include_simulation=false`, `max_docs_per_source=8`, 10 стран):

| Запрос | Найдено / в корпусе | DIRECT / ADJACENT / ниже | Утверждения | Доказательства | TRL (уверенность) | Реализуемость | Ветвей |
|---|---|---|---|---|---|---|---|
| технологии цифровых двойников в системах связи | 71 / 67 | 55 / 7 / 5 | 50 | 156 | 5 (0,842) | 75,0 | 3 |
| бшпд | 11 / 8 | 0 / 0 / 8 | 8 | 0 | 1 | — | 1 |

Повторные прогоны темы о цифровых двойниках (`res-c9727ac8-c72f-43e1-b339-13a0833e552c`):
утверждения **50 → 50**, доказательства **156 → 156** (`updated: 156`), оценки
**55/7/5 → 55/7/5** (`updated: 67`), связи **1 → 1**, список результатов — 67 записей
на 67 документов. Тема «бшпд» (`res-7b2919ca-e95d-472c-8c7d-c0c0554f4992`): второй прогон
`created: 2, updated: 8`, два предупреждения о нераскрытом сокращении и отсутствии EN-ветви.
Источников запланировано 16, успешно 12–13; отчёты `rep-af57fb82-…`, `rep-987c5400-…`
(8 форматов). Числа — `results/progon-1.5.3.json`, разбор для заказчика —
`results/РАЗБОР-ЖУРНАЛА-5.md`.

### Сборка и проверка образа 1.5.3

| Проверка | Результат |
|---|---|
| Образ под wine (`--verify-wine`) | Python **3.11.9**, SQLite **3.45.1**, API **200**, ресурсы **9/9**, журнал загрузки «исправно» |
| Цепочка запуска `cmd.exe /c isheika.cmd` (`--verify-launch`) | HTTP **200**, интерфейс **200** |
| Тесты внутри Windows-образа (`--verify-tests`) | **287/287** (31.2 с) |
| Проверка образа на Linux (`--verify-linux`) | HTTP **200**, интерфейс **200**, ресурсы **9/9**, отсутствующий ресурс — **404**, тесты **287/287** (11.4 с) |

Артефакт: `release/ISHEIKA-NTR-AI.exe`, версия **1.5.3**, **10 247 709** байт;
sha256 `51a728c1e26735212b869c9cc11be496e730b9dca3eba83fa607219404801b63`.
Запасной вариант: `release/ISHEIKA-NTR-AI-portable.zip` (12 537 900 байт).
Миграции: 0001…0008 (новых миграций в 1.5.3 нет — исправления не меняют схему данных).
