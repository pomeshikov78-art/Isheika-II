# ИЩЕЙКА НТР AI

**Шифр:** ISHEIKA-NTR-AI · **Редакция:** 1.2.0 (ТЗ-01…ТЗ-06 + ведомость корректирующих изменений v1.1, ИД-01…ИД-12)
**Назначение:** онлайн-система открытой научно-технической разведки (НТР) с мультиагентным ИИ,
расчётным ядром и доказательной базой.

Реализованы: реестр из **806 источников** и **35 стран**, 24 коннектора (14 подтверждены живыми
запросами), 12-этапный вычислительный процесс, 12 ИИ-агентов A01–A12, расчётное ядро
(релевантность, TRL, реализуемость, барьеры, альтернативы, тренды, прогноз 0–50 лет),
доказательная база Evidence/Claim с группами независимости, реестр версионируемых методик,
отчёты в **6 форматах**, REST API (**79 маршрутов** + SSE + OpenAPI 3.1),
веб-интерфейс **UI-01…UI-30** с модулями **M01–M32**, сквозная трассировка запросов.

---

## 1. Быстрый старт

### Windows: единый файл запуска

`release/ISHEIKA-NTR-AI.exe` — один файл, ничего устанавливать не нужно: внутри
встроенный CPython 3.11 (x64) и приложение. Двойной щелчок → «Да» → откроется окно
сервера и браузер на `http://127.0.0.1:8000/`. Данные сохраняются в
`%LOCALAPPDATA%\IsheikaNTR-AI`, временный каталог распаковки удаляется при выходе.
Пересборка: `python3 tools/build_exe.py` (нужен 7-Zip; см. `release/BUILD-INFO.json`).

### Из исходников (любая ОС)

Требуется только **Python 3.11+** — внешних зависимостей нет.

```bash
cd isheika
python3 run.py                      # профиль DEV, http://0.0.0.0:8000
python3 run.py --port 8080
python3 run.py --no-network         # полностью офлайн (имитационный коннектор)
python3 run.py --email you@org.ru   # polite pool Crossref / Unpaywall
```

Откройте `http://localhost:8000`. Демо-учётные записи профиля DEV (пароль `dev:<логин>`):

| Логин | Роль | Права |
|---|---|---|
| `admin` | администратор | всё, включая ключи и настройки |
| `lead` | руководитель исследования | исследования, реестры, ключи, отчёты |
| `analyst` | аналитик НТР | исследования, аналитика, доказательства, отчёты |
| `expert` | эксперт | чтение + разметка и подтверждения доказательств |
| `observer` | наблюдатель/заказчик | только чтение результатов |
| `auditor` | аудитор качества | чтение журнала, аудита, настроек |

В профилях PILOT/PROD демо-вход заменяется корпоративной аутентификацией (см. `ROADMAP.md`).

### Первый сценарий за 2 минуты

1. **M02 «Новое исследование»** (UI-02): запрос `тропосферная связь за горизонтом`,
   кнопка **«Выбрать все страны»**, «Создать и запустить».
2. **M30 «Мониторинг»** (UI-23): 12 этапов, прогресс, ошибки источников, живая лента SSE.
3. **M16 TRL** (UI-08) и **M17 Реализуемость** (UI-09): шкала, критерии, пробелы, факторы, чувствительность.
4. **M27 «Генератор отчёта»** (UI-20): HTML / PDF / DOCX / XLSX / JSON / CSV.

## 2. Проверки и инструменты

```bash
python3 -m unittest discover -s tests -t .        # 112 автотестов ядра (офлайн, изолированная БД)
python3 tools/api_check.py                        # 69 проверок API + RBAC по ролям
python3 tools/api_check.py --login observer       # те же проверки с правами наблюдателя
python3 tools/api_check.py --run                  # сквозной цикл: создание → 12 этапов → отчёт
python3 tools/verify_connectors.py --json var/connector-health.json
python3 tools/smoke.py --live --limit 8 --wait 200
node tools/ui_check.mjs                           # 61 проверка интерфейса (нужен jsdom)
python3 tools/build_exe.py --verify-wine --verify-tests   # сборка единого .exe + проверка образа
node tools/pdf_check.mjs var/files/<rid>/report-<id>.pdf   # нужен pdfjs-dist
```

`tools/ui_check.mjs` и `tools/pdf_check.mjs` — **dev-инструменты**, в рантайме не используются:
`npm install jsdom pdfjs-dist` (см. `requirements-optional.txt`).

Последние прогоны: автотесты **63/63**, API **45/45** (все 6 ролей), интерфейс **47/47**,
сквозной цикл по HTTP **59/59**, живые коннекторы **14 активных из 24**.

## 3. Состав проекта

```
isheika/
├── run.py                     точка входа (DEV/PILOT/PROD, --no-network, --allow-paid)
├── isheika/
│   ├── config.py              профили, лимиты, политики; секреты не покидают сервер
│   ├── contracts.py           контракты Document/AIRequest/AIResponse/ApiError
│   ├── states.py              7 конечных автоматов (research, task, ai_request, document, report, source, provider)
│   ├── storage/               schema.sql (41 таблица), db.py, secrets.py (шифр. хранилище ключей)
│   ├── registry/              loader.py + seed/*.json (806 источников, 35 стран, методика M-1.0.0)
│   ├── search/                quota, http (robots/SSRF/стоп-лист), query_parser, expansion,
│   │                          normalize (дедупликация), relevance, manager, connectors/ (24)
│   ├── workflow/              events (SSE), engine (12 этапов, идемпотентность, resume), pipeline
│   ├── ai/                    safety (prompt injection), adapters, orchestrator (free-first),
│   │                          agents A01–A12, collective (4 режима), simulation
│   ├── analytics/             evidence, trl, feasibility, barriers, alternatives, trends,
│   │                          forecast, passport, quality
│   ├── reports/               builder.py (HTML/JSON/CSV/XLSX/DOCX), pdf.py + assets/ (шрифт)
│   ├── api/                   service.py (предметный слой), server.py (stdlib HTTP),
│   │                          adapters_fastapi.py (опциональный транспорт)
│   └── web/                   index.html, styles.css, charts.js, app.js,
│                              screens_core.js, screens_registry.js
├── registry/                  (данные перечня — вне пакета)
├── tests/                     63 автотеста
├── tools/                     parse_registry, smoke, api_check, verify_connectors, ui_check, pdf_check
├── docs/                      REGISTRY_NOTES.md, ACCEPTANCE.md
├── ARCHITECTURE.md  ROADMAP.md  requirements-optional.txt
└── var/                       isheika.db, cache/, files/<rid>/report-*, secrets.enc, config.json
```

## 4. Что реализовано по ТЗ

**ТЗ-01 (функциональная модель).** Модули M01–M32 доступны из левого меню; 6 ролей RBAC;
настраиваемый реестр (добавление источника не требует изменения ядра); статусы заданий
`queued/running/partial/completed/failed/cancelled`; идемпотентные ключи этапов и продолжение
прерванного исследования; экспорт HTML/PDF/DOCX/XLSX/JSON/CSV; ключи только на сервере
в зашифрованном виде; защита от XSS (экранирование), SSRF (запрет приватных адресов),
инъекций в промпты, обхода paywall/CAPTCHA/авторизации (стоп-лист STOP-01…06), соблюдение
robots.txt и лицензий.

**ТЗ-02 (мульти-ИИ).** Free-first маршрутизация `Q(m,t) = argmax`: бесплатная подтверждённая →
бесплатная альтернативная → локальная → платная **только при явном разрешении**; 18 провайдеров,
11 моделей, адаптер на провайдера; полный контракт запроса/ответа (`request_id`, `task_id`,
`agent_id`, `provider_id`, `model_id`, `prompt_version`, `prompt_hash`, `privacy_class`,
`usage`, `latency_ms`, `estimated_cost`, `finish_reason`, `error_code`); валидация JSON Schema
с ограниченной попыткой исправления и статусом `schema_error`; Retry-After + backoff;
9 статусов провайдера; 4 режима коллективного анализа; **голосование моделей не является
доказательством**; квоты берутся из реестра и фактических ответов API, а не зашиваются в код.

**ТЗ-03 (математика).** Расчётное ядро не зависит от ИИ и версионируется (`M-1.0.0` + хеш входов).
`R = 0,30S + 0,25T + 0,15C + 0,15E + 0,10K + 0,05F`, пороги 0,80 / 0,60;
`claim_id` + Evidence, типы FACT/ANALYSIS/HYPOTHESIS/FORECAST и статусы
SUPPORTED/PARTIAL/CONTRADICTED/UNVERIFIED/SUPERSEDED; **TRL = максимальный уровень с выполненными
обязательными критериями, усреднение запрещено**; `F = 100·Σ(wᵢxᵢ)/Σ(wᵢaᵢ)`, покрытие `C`,
неизвестный фактор ≠ 0; 11 классов барьеров; альтернативы по единым критериям; прогноз
6 горизонтов (0–2…35–50), 3 сценария, монотонная `P(T≤t)`, на 20–50 годах только качественные
сценарии; метрики Precision@10, nDCG@10, TRL MAE, Brier, покрытие интервалов со статусом
**«калибровка не завершена»**.

**ТЗ-04 (интерфейс).** Экраны UI-01…UI-26; верхняя панель, сворачиваемое меню M01–M32 с
индикатором заданий, рабочая область, контекстная панель, статусная строка; светлая/тёмная темы;
адаптив 1920/1440/1366/планшеты; состояния initial/loading/partial/success/empty/warning/error/
offline/permission_denied; кнопка **«Выбрать все страны»** (повторное нажатие снимает выбор);
инфографика SVG без внешних библиотек (TRL ladder, radar, fan chart, матрица рисков, heatmap,
граф связей) с легендами, единицами, tooltip, текстовой альтернативой и экспортом;
таблицы с сортировкой, фильтром, пагинацией, выбором колонок и выгрузкой CSV.
**UI не пересчитывает научные показатели** — только отображает серверные значения с версией методики.

## 5. Отклонения от рекомендованного стека (зафиксированы честно)

Среда сборки не имеет пакетного менеджера, поэтому ядро реализовано **на стандартной библиотеке**.
Предметная логика отделена от транспорта и хранилища, поэтому переход на промышленный стек
не требует переписывания домена.

| ТЗ рекомендует | Реализовано сейчас | Путь миграции |
|---|---|---|
| FastAPI + uvicorn | `api/server.py` (stdlib `ThreadingHTTPServer`), те же маршруты | `uvicorn isheika.api.adapters_fastapi:app` — готовый адаптер поверх `ROUTES` |
| PostgreSQL | SQLite (`var/isheika.db`), схема по ТЗ-06 | `storage/db.py` — единая точка доступа; DDL совместим по составу полей |
| OpenSearch / PG FTS | собственный лексический поиск + релевантность | заменить `search/manager.py` на поисковый бэкенд, контракты сохранить |
| pgvector + эмбеддинги | лексико-семантическая аппроксимация, в каждом расчёте поле `S_method` | подключить эмбеддинги и переключить `S`, версия методики повышается |
| Redis + Celery | потоковый `workflow/engine.py` с идемпотентностью и resume | очередь заданий выносится за тем же интерфейсом `start/status/cancel` |
| WeasyPrint / python-docx / openpyxl | собственные писатели PDF (встроенный шрифт DejaVu) и OOXML | при наличии WeasyPrint PDF делается из HTML автоматически |
| SSO/OIDC, TLS | токены Bearer + RBAC, HTTP в DEV | TLS и OIDC — на границе (reverse proxy), см. `ROADMAP.md` |

Прочие осознанные ограничения:

* **Живых ключей ИИ нет** → ответы формирует детерминированный экстрактор; каждый такой ответ
  помечен `simulated=1`, в UI показан как «детерминированный экстрактор», в отчёт попадает предупреждение.
* **Калибровка методик не завершена** — веса и пороги стартовые, статус выводится во всех экранах.
* Часть источников требует бесплатного ключа (CORE, Unpaywall, EPO OPS, USPTO ODP) — статус
  `RESTRICTED` до внесения ключа в UI-25; NASA NTRS отвечает 403 без ключа, Semantic Scholar — 429
  без ключа (зафиксировано в `docs/REGISTRY_NOTES.md`).
* Доступность ≥ 98 %/мес — эксплуатационная метрика, в DEV не измеряется; точки мониторинга есть.

## 6. Безопасность

* Ключи — в `var/secrets.enc` (шифрование + HMAC-целостность), в API/UI только факт наличия и маска.
* SSRF: запрет приватных/loopback/link-local адресов и не-HTTP схем.
* Стоп-лист: Sci-Hub/Libgen, автосбор Scholar/ResearchGate/LinkedIn/X, GUI Espacenet,
  PDF CORE в обход API, материалы ДСП/ГОСТ РВ.
* robots.txt соблюдается; исключение `api_terms` — только для документированных официальных API
  (обоснование и журнал — в `docs/REGISTRY_NOTES.md`).
* Prompt injection: контент источников передаётся как данные, инструкции из документов не исполняются.
* Токен передаётся в заголовке `Authorization` (не в cookie) → CSRF-вектор отсутствует;
  для продакшена TLS terminates на границе.
* Аудит: каждое изменение пишет `audit_log`, переходы состояний — `core_state_history`,
  обращения к API — `audit_api_calls`, квоты — `audit_quota_usage`. Журнал выгружается TXT/JSON/CSV.

## 7. Лицензии

Код проекта — по условиям заказчика. Встроенный шрифт **DejaVu Sans**
(`isheika/reports/assets/DejaVuSans.ttf`) распространяется по лицензии Bitstream Vera / DejaVu —
текст лицензии в `assets/LICENSE_DEJAVU.txt`. Данные источников используются через официальные
API в рамках их условий; лицензии документов сохраняются в поле `license` карточки документа.
