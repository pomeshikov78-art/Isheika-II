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
