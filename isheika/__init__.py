"""ИЩЕЙКА НТР AI — серверное ядро (модульный монолит, ТЗ-05 §12.3).

Пакеты:
    contracts  — единый словарь статусов, кодов ошибок, оболочка сообщения (ТЗ-05 §7)
    states     — конечные автоматы research / task / ai_request / document / report (ТЗ-05 §9)
    storage    — SQLite/PostgreSQL-совместимая физическая модель (ТЗ-06)
    registry   — каталог источников, реестр коннекторов, провайдеры, модели, агенты
    search     — поисковый контур P1
    ai         — мульти-ИИ контур P2/P3
    analytics  — доказательная модель и расчётное ядро P4/P5/P6
    workflow   — граф выполнения, задания, события
    reports    — отчётность и экспорт P7
    api        — REST /api/v1 (ТЗ-06 §7)
"""

__version__ = "1.4.0"
CODENAME = "ISHEIKA-NTR-AI"
METHODOLOGY_VERSION = "M-1.0.0"
API_VERSION = "v1"
