-- ISHEIKA-NTR-AI / миграция 0001 — базовая физическая модель (ТЗ-06)
-- Профиль DEV: SQLite. Имена таблиц = <схема PostgreSQL>_<таблица>.
-- Соответствие схемам ТЗ-06 §2.1: core_, search_, registry_, content_, knowledge_,
-- evidence_, ai_, analytics_, forecast_, workflow_, reporting_, audit_, dict_.
-- JSONB -> TEXT(JSON), UUID -> TEXT, TIMESTAMPTZ -> TEXT(ISO-8601 UTC), TEXT[] -> TEXT(JSON).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- ============================================================ dict
CREATE TABLE IF NOT EXISTS dict_countries (
    code            TEXT PRIMARY KEY,
    name_ru         TEXT NOT NULL,
    region          TEXT,
    patent_office   TEXT,
    languages       TEXT NOT NULL DEFAULT '[]',
    is_enabled      INTEGER NOT NULL DEFAULT 1,
    profile         TEXT NOT NULL DEFAULT '{}',
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dict_statuses (
    domain      TEXT NOT NULL,
    code        TEXT NOT NULL,
    title_ru    TEXT NOT NULL,
    is_terminal INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (domain, code)
);

-- ============================================================ core
CREATE TABLE IF NOT EXISTS core_users (
    id            TEXT PRIMARY KEY,
    login         TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN
                  ('admin','research_lead','analyst','expert','observer','auditor')),
    password_hash TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS core_projects (
    id              TEXT PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    description     TEXT,
    owner_user_id   TEXT REFERENCES core_users(id),
    classification  TEXT NOT NULL DEFAULT 'open'
                    CHECK (classification IN ('open','internal','restricted','confidential')),
    status          TEXT NOT NULL DEFAULT 'active',
    settings        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS core_researches (
    id                      TEXT PRIMARY KEY,
    project_id              TEXT NOT NULL REFERENCES core_projects(id),
    title                   TEXT NOT NULL,
    research_type           TEXT NOT NULL DEFAULT 'technology'
                            CHECK (research_type IN ('technology','product','problem','direction','comparative','forecast')),
    status                  TEXT NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft','queued','running','partial','completed','failed','paused','cancelled')),
    owner_user_id           TEXT REFERENCES core_users(id),
    goal                    TEXT,
    period_from             INTEGER,
    period_to               INTEGER,
    forecast_horizon_years  INTEGER CHECK (forecast_horizon_years BETWEEN 0 AND 50),
    language_codes          TEXT NOT NULL DEFAULT '[]',
    country_codes           TEXT NOT NULL DEFAULT '[]',
    settings                TEXT NOT NULL DEFAULT '{}',
    methodology_version     TEXT NOT NULL DEFAULT 'M-1.0.0',
    version_no              INTEGER NOT NULL DEFAULT 1,
    snapshot_hash           TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_researches_project_status ON core_researches(project_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS core_state_history (
    id           TEXT PRIMARY KEY,
    entity_kind  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    from_state   TEXT,
    to_state     TEXT NOT NULL,
    reason       TEXT,
    actor        TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_state_history_entity ON core_state_history(entity_kind, entity_id, created_at);

-- ============================================================ search
CREATE TABLE IF NOT EXISTS search_queries (
    id              TEXT PRIMARY KEY,
    research_id     TEXT NOT NULL REFERENCES core_researches(id) ON DELETE CASCADE,
    raw_text        TEXT NOT NULL,
    parsed          TEXT NOT NULL DEFAULT '{}',
    expansions      TEXT NOT NULL DEFAULT '{}',
    branches        TEXT NOT NULL DEFAULT '[]',
    exclusions      TEXT NOT NULL DEFAULT '[]',
    query_version   INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_profiles (
    id            TEXT PRIMARY KEY,
    research_id   TEXT NOT NULL REFERENCES core_researches(id) ON DELETE CASCADE,
    country_codes TEXT NOT NULL DEFAULT '[]',
    source_codes  TEXT NOT NULL DEFAULT '[]',
    categories    TEXT NOT NULL DEFAULT '[]',
    languages     TEXT NOT NULL DEFAULT '[]',
    access_max    TEXT NOT NULL DEFAULT 'A1',
    settings      TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_jobs (
    id             TEXT PRIMARY KEY,
    research_id    TEXT NOT NULL REFERENCES core_researches(id) ON DELETE CASCADE,
    connector_code TEXT NOT NULL,
    source_code    TEXT NOT NULL,
    branch         TEXT,
    expression     TEXT,
    status         TEXT NOT NULL DEFAULT 'queued',
    attempts       INTEGER NOT NULL DEFAULT 0,
    found_count    INTEGER NOT NULL DEFAULT 0,
    error_code     TEXT,
    error_message  TEXT,
    started_at     TEXT,
    finished_at    TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_search_jobs_research ON search_jobs(research_id, status);

-- ============================================================ registry
CREATE TABLE IF NOT EXISTS registry_sources (
    id                 TEXT PRIMARY KEY,
    code               TEXT NOT NULL UNIQUE,
    name               TEXT NOT NULL,
    category           TEXT NOT NULL,
    category_name      TEXT,
    country_code       TEXT REFERENCES dict_countries(code),
    scope              TEXT NOT NULL DEFAULT 'international',
    api_type           TEXT,
    access_class       TEXT NOT NULL DEFAULT 'UNKNOWN',
    access_reason      TEXT,
    auth_type          TEXT,
    endpoints          TEXT NOT NULL DEFAULT '[]',
    official_url       TEXT,
    purpose            TEXT,
    limits             TEXT NOT NULL DEFAULT '{}',
    evidence_marker    TEXT NOT NULL DEFAULT 'Д' CHECK (evidence_marker IN ('П','Р','Д')),
    marker_reason      TEXT,
    integration_status TEXT NOT NULL DEFAULT 'CANDIDATE'
                       CHECK (integration_status IN ('CONNECTED','TESTED','CANDIDATE','RESTRICTED','UNAVAILABLE','DISABLED')),
    connector_code     TEXT,
    priority           TEXT NOT NULL DEFAULT 'P2',
    response_format    TEXT,
    license            TEXT,
    registry_section   TEXT,
    last_verified_at   TEXT,
    last_success_at    TEXT,
    last_http_status   INTEGER,
    health             TEXT NOT NULL DEFAULT '{}',
    metadata           TEXT NOT NULL DEFAULT '{}',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sources_status_type ON registry_sources(integration_status, category);
CREATE INDEX IF NOT EXISTS ix_sources_country ON registry_sources(country_code);

CREATE TABLE IF NOT EXISTS registry_connectors (
    code            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_code     TEXT REFERENCES registry_sources(code),
    protocol        TEXT NOT NULL,
    base_url        TEXT,
    auth_type       TEXT NOT NULL DEFAULT 'none',
    secret_ref      TEXT,
    capabilities    TEXT NOT NULL DEFAULT '{}',
    limits          TEXT NOT NULL DEFAULT '{}',
    quota_policy    TEXT NOT NULL DEFAULT '{}',
    enabled         INTEGER NOT NULL DEFAULT 1,
    requires_key    INTEGER NOT NULL DEFAULT 0,
    paid            INTEGER NOT NULL DEFAULT 0,
    health_status   TEXT NOT NULL DEFAULT 'unverified',
    last_checked_at TEXT,
    last_error      TEXT,
    docs_url        TEXT,
    tos_url         TEXT,
    fallback_code   TEXT,
    verified_marker TEXT NOT NULL DEFAULT 'Д',
    implementation  TEXT NOT NULL DEFAULT 'stub',
    robots_policy   TEXT NOT NULL DEFAULT 'respect',
    notes           TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registry_stoplist (
    code       TEXT PRIMARY KEY,
    pattern    TEXT NOT NULL,
    reason     TEXT NOT NULL,
    action     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registry_changelog (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    subject    TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- ============================================================ content
-- ---------------------------------------------------------------- контент v1.1
-- ИД-03: четыре уровня модели документов + связи.
-- Физическое содержимое (blob) != логический документ != вхождение в источнике.
CREATE TABLE IF NOT EXISTS content_blobs (
    id             TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL,
    hash_algorithm TEXT NOT NULL DEFAULT 'sha256',
    size_bytes     INTEGER,
    format         TEXT,
    text_ref       TEXT,
    storage_ref    TEXT,
    created_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_blob_sha256 ON content_blobs(content_sha256);

CREATE TABLE IF NOT EXISTS content_documents (
    id                TEXT PRIMARY KEY,
    logical_key       TEXT NOT NULL,
    blob_id           TEXT REFERENCES content_blobs(id) ON DELETE SET NULL,
    cluster_id        TEXT,
    title             TEXT NOT NULL,
    normalized_title  TEXT,
    doc_type          TEXT NOT NULL DEFAULT 'unknown',
    authors           TEXT NOT NULL DEFAULT '[]',
    organizations     TEXT NOT NULL DEFAULT '[]',
    country_code      TEXT,
    language          TEXT,
    published_at      TEXT,
    publication_year  INTEGER,
    abstract          TEXT,
    text_excerpt      TEXT,
    license           TEXT,
    oa_status         TEXT,
    doi               TEXT,
    external_id       TEXT,
    identifiers       TEXT NOT NULL DEFAULT '{}',
    content_hash      TEXT,
    simhash           TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'DISCOVERED'
                      CHECK (extraction_status IN ('DISCOVERED','FETCHED','EXTRACTED','NORMALIZED','FAILED','UNSUPPORTED')),
    deduplication_status TEXT NOT NULL DEFAULT 'PENDING'
                      CHECK (deduplication_status IN ('PENDING','UNIQUE','DUPLICATE','CLUSTERED','REVIEW')),
    duplicate_of_document_id TEXT REFERENCES content_documents(id) ON DELETE SET NULL,
    evidence_class    TEXT NOT NULL DEFAULT 'unknown',
    independence_group TEXT,
    origin_class      TEXT NOT NULL DEFAULT 'PRIMARY',
    marker            TEXT NOT NULL DEFAULT 'Д',
    first_research_id TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_logical_key ON content_documents(logical_key);
CREATE INDEX IF NOT EXISTS ix_documents_doi ON content_documents(doi);
CREATE INDEX IF NOT EXISTS ix_documents_cluster ON content_documents(cluster_id);

CREATE TABLE IF NOT EXISTS content_occurrences (
    id                TEXT PRIMARY KEY,
    document_id       TEXT NOT NULL REFERENCES content_documents(id) ON DELETE CASCADE,
    research_id       TEXT NOT NULL REFERENCES core_researches(id) ON DELETE CASCADE,
    source_code       TEXT NOT NULL,
    connector_code    TEXT,
    search_job_id     TEXT,
    branch            TEXT,
    expression        TEXT,
    url               TEXT NOT NULL,
    canonical_url     TEXT NOT NULL,
    accessed_at       TEXT NOT NULL,
    fetch_http_status INTEGER,
    raw_ref           TEXT,
    blob_id           TEXT,
    created_at        TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_occurrence_source_url
    ON content_occurrences(research_id, source_code, canonical_url);
CREATE INDEX IF NOT EXISTS ix_occurrences_research ON content_occurrences(research_id);
CREATE INDEX IF NOT EXISTS ix_occurrences_document ON content_occurrences(document_id);

CREATE TABLE IF NOT EXISTS content_clusters (
    id            TEXT PRIMARY KEY,
    cluster_key   TEXT NOT NULL,
    title         TEXT,
    cluster_type  TEXT NOT NULL DEFAULT 'VERSIONS',
    primary_document_id TEXT,
    created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cluster_key ON content_clusters(cluster_key);

CREATE TABLE IF NOT EXISTS content_cluster_members (
    cluster_id   TEXT NOT NULL REFERENCES content_clusters(id) ON DELETE CASCADE,
    document_id  TEXT NOT NULL REFERENCES content_documents(id) ON DELETE CASCADE,
    relation     TEXT NOT NULL DEFAULT 'EXACT_DUPLICATE',
    role         TEXT NOT NULL DEFAULT 'member',
    confidence   REAL,
    decided_by   TEXT NOT NULL DEFAULT 'algorithm',
    created_at   TEXT NOT NULL,
    PRIMARY KEY (cluster_id, document_id)
);

CREATE TABLE IF NOT EXISTS content_relations (
    id               TEXT PRIMARY KEY,
    from_document_id TEXT NOT NULL REFERENCES content_documents(id) ON DELETE CASCADE,
    to_document_id   TEXT NOT NULL REFERENCES content_documents(id) ON DELETE CASCADE,
    relation_type    TEXT NOT NULL
                     CHECK (relation_type IN ('EXACT_DUPLICATE','ALTERNATIVE_HOSTING','PREPRINT_OF',
                            'PUBLISHED_VERSION_OF','REVISION_OF','TRANSLATION_OF','SUMMARY_OF','CITES')),
    confidence       REAL,
    basis            TEXT,
    decided_by       TEXT NOT NULL DEFAULT 'algorithm',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_relations_from ON content_relations(from_document_id);

-- ИД-01/ИД-07: результат оценки соответствия запросу (не статус документа).
CREATE TABLE IF NOT EXISTS search_results (
    id                  TEXT PRIMARY KEY,
    research_id         TEXT NOT NULL,
    document_id         TEXT NOT NULL REFERENCES content_documents(id) ON DELETE CASCADE,
    search_task_id      TEXT,
    relevance_score     REAL NOT NULL,
    relevance_class     TEXT NOT NULL CHECK (relevance_class IN ('DIRECT','ADJACENT','BELOW_THRESHOLD')),
    decision            TEXT NOT NULL DEFAULT 'INCLUDE'
                        CHECK (decision IN ('INCLUDE','EXCLUDE','MANUAL_INCLUDE','MANUAL_EXCLUDE')),
    score_s             REAL,
    score_t             REAL,
    score_c             REAL,
    score_e             REAL,
    score_k             REAL,
    score_f             REAL,
    components          TEXT NOT NULL DEFAULT '{}',
    weights             TEXT NOT NULL DEFAULT '{}',
    gate                TEXT NOT NULL DEFAULT '{}',
    reason              TEXT,
    reason_codes        TEXT NOT NULL DEFAULT '[]',
    methodology_id      TEXT,
    methodology_version TEXT NOT NULL,
    input_hash          TEXT,
    -- псевдонимы обратной совместимости (виртуальные, не дублируют данные)
    score               REAL GENERATED ALWAYS AS (relevance_score) VIRTUAL,
    class               TEXT GENERATED ALWAYS AS (relevance_class) VIRTUAL,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_search_results_score ON search_results(research_id, relevance_score DESC);
CREATE INDEX IF NOT EXISTS ix_search_results_doc ON search_results(document_id, research_id);

-- Представление «документы исследования»: логический документ + вхождения + оценка.
-- Один логический документ = одна строка на исследование, сколько бы URL ни найдено.
CREATE VIEW IF NOT EXISTS research_documents AS
SELECT d.id, d.logical_key, d.blob_id, d.cluster_id, d.title, d.normalized_title, d.doc_type,
       d.authors, d.organizations, d.country_code, d.language, d.published_at, d.publication_year,
       d.abstract, d.text_excerpt, d.license, d.oa_status, d.doi, d.external_id, d.identifiers,
       d.content_hash, d.simhash, d.extraction_status, d.deduplication_status,
       d.duplicate_of_document_id, d.evidence_class, d.independence_group, d.origin_class, d.marker,
       d.created_at, d.updated_at,
       o.research_id, o.occurrence_count, o.occurrence_id, o.source_code, o.connector_code,
       o.url, o.canonical_url, o.accessed_at, o.fetch_http_status, o.raw_ref, o.branch,
       r.relevance_class, r.relevance_score, r.decision, r.methodology_version,
       d.extraction_status AS state
FROM content_documents d
JOIN (SELECT document_id, research_id, COUNT(*) AS occurrence_count,
             MIN(id) AS occurrence_id, MIN(url) AS url, MIN(canonical_url) AS canonical_url,
             MIN(source_code) AS source_code, MIN(connector_code) AS connector_code,
             MIN(accessed_at) AS accessed_at, MAX(fetch_http_status) AS fetch_http_status,
             MIN(raw_ref) AS raw_ref, MIN(branch) AS branch
      FROM content_occurrences GROUP BY document_id, research_id) o
  ON o.document_id = d.id
LEFT JOIN search_results r
  ON r.document_id = d.id AND r.research_id = o.research_id
 AND r.id = (SELECT s2.id FROM search_results s2
             WHERE s2.document_id = d.id AND s2.research_id = o.research_id
             ORDER BY s2.created_at DESC, s2.rowid DESC LIMIT 1);

-- ============================================================ knowledge
CREATE TABLE IF NOT EXISTS knowledge_technologies (
    id            TEXT PRIMARY KEY,
    research_id   TEXT NOT NULL REFERENCES core_researches(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    passport      TEXT NOT NULL DEFAULT '{}',
    trl           INTEGER,
    feasibility   REAL,
    coverage      REAL,
    status        TEXT NOT NULL DEFAULT 'draft',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_claims (
    id            TEXT PRIMARY KEY,
    research_id   TEXT NOT NULL REFERENCES core_researches(id) ON DELETE CASCADE,
    technology_id TEXT REFERENCES knowledge_technologies(id) ON DELETE CASCADE,
    claim_text    TEXT NOT NULL,
    claim_type    TEXT NOT NULL CHECK (claim_type IN ('FACT','ANALYSIS','HYPOTHESIS','FORECAST')),
    section       TEXT,
    status        TEXT NOT NULL DEFAULT 'UNVERIFIED'
                  CHECK (status IN ('SUPPORTED','PARTIAL','CONTRADICTED','UNVERIFIED','SUPERSEDED')),
    confidence    REAL,
    produced_by   TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_claims_research_type ON knowledge_claims(research_id, claim_type, status);

CREATE TABLE IF NOT EXISTS evidence_items (
    id                 TEXT PRIMARY KEY,
    claim_id           TEXT NOT NULL REFERENCES knowledge_claims(id) ON DELETE CASCADE,
    document_id        TEXT REFERENCES content_documents(id) ON DELETE SET NULL,
    research_id        TEXT NOT NULL,
    source_code        TEXT,
    url                TEXT,
    locator            TEXT,
    quote              TEXT,
    published_at       TEXT,
    accessed_at        TEXT,
    evidence_class     TEXT NOT NULL DEFAULT 'unknown',
    independence_group TEXT,
    independence_group_id TEXT,
    origin_class       TEXT NOT NULL DEFAULT 'PRIMARY'
                       CHECK (origin_class IN ('PRIMARY','INDEPENDENT_CONFIRMATION','REPRINT',
                                               'SUMMARY','DERIVATIVE','CONTRADICTORY')),
    primary_source_ref TEXT,
    derived_from_evidence_id TEXT,
    first_published_at TEXT,
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
    blob_id            TEXT,
    quality            REAL,
    status             TEXT NOT NULL DEFAULT 'UNVERIFIED',
    marker             TEXT NOT NULL DEFAULT 'Д',
    archive_url        TEXT,
    contradiction_of   TEXT,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evidence_claim ON evidence_items(claim_id);

CREATE TABLE IF NOT EXISTS knowledge_links (
    id          TEXT PRIMARY KEY,
    research_id TEXT NOT NULL,
    from_kind   TEXT NOT NULL,
    from_id     TEXT NOT NULL,
    to_kind     TEXT NOT NULL,
    to_id       TEXT NOT NULL,
    link_type   TEXT NOT NULL,
    confirmed   INTEGER NOT NULL DEFAULT 0,
    evidence_id TEXT,
    created_at  TEXT NOT NULL
);

-- ============================================================ ai
CREATE TABLE IF NOT EXISTS ai_providers (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    family         TEXT,
    endpoint       TEXT,
    docs_url       TEXT,
    auth_method    TEXT,
    adapter        TEXT NOT NULL,
    privacy_policy TEXT NOT NULL DEFAULT '{}',
    region_limits  TEXT,
    pricing        TEXT NOT NULL DEFAULT '{}',
    paid           INTEGER NOT NULL DEFAULT 0,
    enabled        INTEGER NOT NULL DEFAULT 1,
    status         TEXT NOT NULL DEFAULT 'unavailable',
    secret_ref     TEXT,
    last_checked_at TEXT,
    last_error     TEXT,
    verified_at    TEXT,
    metadata       TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_models (
    id              TEXT PRIMARY KEY,
    provider_id     TEXT NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
    model_id        TEXT NOT NULL,
    display_name    TEXT,
    capabilities    TEXT NOT NULL DEFAULT '{}',
    context_window  INTEGER,
    languages       TEXT NOT NULL DEFAULT '[]',
    free_tier       INTEGER NOT NULL DEFAULT 0,
    paid            INTEGER NOT NULL DEFAULT 0,
    quota           TEXT NOT NULL DEFAULT '{}',
    quality_scores  TEXT NOT NULL DEFAULT '{}',
    enabled         INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'unavailable',
    verified_at     TEXT,
    UNIQUE (provider_id, model_id)
);

CREATE TABLE IF NOT EXISTS ai_agents (
    code           TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    purpose        TEXT,
    task_classes   TEXT NOT NULL DEFAULT '[]',
    prompt_version TEXT NOT NULL DEFAULT 'P-1.0.0',
    response_schema TEXT NOT NULL DEFAULT '{}',
    enabled        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ai_tasks (
    id           TEXT PRIMARY KEY,
    research_id  TEXT NOT NULL REFERENCES core_researches(id) ON DELETE CASCADE,
    agent_code   TEXT NOT NULL,
    task_class   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'queued',
    input_refs   TEXT NOT NULL DEFAULT '[]',
    payload      TEXT NOT NULL DEFAULT '{}',
    mode         TEXT NOT NULL DEFAULT 'independent',
    created_at   TEXT NOT NULL,
    finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS ai_requests (
    id             TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL REFERENCES ai_tasks(id) ON DELETE CASCADE,
    research_id    TEXT NOT NULL,
    attempt_no     INTEGER NOT NULL DEFAULT 1,
    provider_id    TEXT,
    model_id       TEXT,
    agent_code     TEXT NOT NULL,
    state          TEXT NOT NULL DEFAULT 'created',
    privacy_class  TEXT NOT NULL DEFAULT 'public',
    prompt_version TEXT NOT NULL DEFAULT 'P-1.0.0',
    prompt_hash    TEXT,
    usage          TEXT,
    latency_ms     INTEGER,
    estimated_cost REAL,
    simulated      INTEGER NOT NULL DEFAULT 0,
    error_code     TEXT,
    error_message  TEXT,
    route_reason   TEXT,
    created_at     TEXT NOT NULL,
    finished_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_ai_requests_task ON ai_requests(task_id, attempt_no);

CREATE TABLE IF NOT EXISTS ai_results (
    id                TEXT PRIMARY KEY,
    request_id        TEXT NOT NULL REFERENCES ai_requests(id) ON DELETE CASCADE,
    task_id           TEXT NOT NULL,
    research_id       TEXT NOT NULL,
    agent_code        TEXT NOT NULL,
    content           TEXT,
    structured_result TEXT,
    citations         TEXT NOT NULL DEFAULT '[]',
    schema_valid      INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_consensus (
    id           TEXT PRIMARY KEY,
    research_id  TEXT NOT NULL,
    topic        TEXT NOT NULL,
    mode         TEXT NOT NULL,
    positions    TEXT NOT NULL DEFAULT '[]',
    conflicts    TEXT NOT NULL DEFAULT '[]',
    resolution   TEXT,
    synthesis    TEXT,
    created_at   TEXT NOT NULL
);

-- ============================================================ analytics
CREATE TABLE IF NOT EXISTS analytics_trl (
    id                  TEXT PRIMARY KEY,
    research_id         TEXT NOT NULL,
    technology_id       TEXT,
    trl                 INTEGER NOT NULL CHECK (trl BETWEEN 1 AND 9),
    criteria            TEXT NOT NULL DEFAULT '[]',
    gaps                TEXT NOT NULL DEFAULT '[]',
    confidence          REAL,
    methodology_id      TEXT,
    methodology_version TEXT NOT NULL,
    input_hash          TEXT,
    document_set_version TEXT,
    model_id            TEXT,
    model_version       TEXT,
    prompt_version      TEXT,
    input_snapshot      TEXT NOT NULL DEFAULT '{}',
    parameters          TEXT NOT NULL DEFAULT '{}',
    config_checksum     TEXT,
    output_hash         TEXT,
    assessed_by         TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics_feasibility (
    id                  TEXT PRIMARY KEY,
    research_id         TEXT NOT NULL,
    technology_id       TEXT,
    score               REAL,                    -- ИД-02: NULL, если все факторы неизвестны
    coverage            REAL NOT NULL,
    interpretation_allowed INTEGER NOT NULL DEFAULT 0,
    coverage_warning    TEXT,
    unknown_factors     TEXT NOT NULL DEFAULT '[]',
    range_low           REAL,
    range_high          REAL,
    conservative        REAL,
    factors             TEXT NOT NULL DEFAULT '[]',
    weights             TEXT NOT NULL DEFAULT '{}',
    sensitivity         TEXT NOT NULL DEFAULT '[]',
    interpretation      TEXT,
    methodology_id      TEXT,
    methodology_version TEXT NOT NULL,
    input_hash          TEXT,
    document_set_version TEXT,
    model_id            TEXT,
    model_version       TEXT,
    prompt_version      TEXT,
    input_snapshot      TEXT NOT NULL DEFAULT '{}',
    parameters          TEXT NOT NULL DEFAULT '{}',
    config_checksum     TEXT,
    output_hash         TEXT,
    assessed_by         TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics_barriers (
    id           TEXT PRIMARY KEY,
    research_id  TEXT NOT NULL,
    barrier_type TEXT NOT NULL,
    title        TEXT NOT NULL,
    criticality  REAL,
    probability  REAL,
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    dependencies TEXT NOT NULL DEFAULT '[]',
    workarounds  TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics_alternatives (
    id           TEXT PRIMARY KEY,
    research_id  TEXT NOT NULL,
    name         TEXT NOT NULL,
    criteria     TEXT NOT NULL DEFAULT '{}',
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics_trends (
    id           TEXT PRIMARY KEY,
    research_id  TEXT NOT NULL,
    metric       TEXT NOT NULL,
    series       TEXT NOT NULL DEFAULT '[]',
    method       TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS forecast_runs (
    id                  TEXT PRIMARY KEY,
    research_id         TEXT NOT NULL,
    target              TEXT NOT NULL,
    horizons            TEXT NOT NULL DEFAULT '[]',
    scenarios           TEXT NOT NULL DEFAULT '{}',
    method              TEXT NOT NULL,
    assumptions         TEXT NOT NULL DEFAULT '[]',
    intervals           TEXT NOT NULL DEFAULT '{}',
    monotonic_ok        INTEGER NOT NULL DEFAULT 1,
    methodology_id      TEXT,
    methodology_version TEXT NOT NULL,
    presentation_policy TEXT NOT NULL DEFAULT 'FORECAST_V1',
    calibration_status  TEXT NOT NULL DEFAULT 'NOT_CALIBRATED',
    document_set_version TEXT,
    model_id            TEXT,
    model_version       TEXT,
    prompt_version      TEXT,
    input_snapshot      TEXT NOT NULL DEFAULT '{}',
    parameters          TEXT NOT NULL DEFAULT '{}',
    config_checksum     TEXT,
    input_hash          TEXT,
    output_hash         TEXT,
    assessed_by         TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics_quality (
    id           TEXT PRIMARY KEY,
    research_id  TEXT,
    metric       TEXT NOT NULL,
    value        REAL,
    sample_size  INTEGER,
    calibrated   INTEGER NOT NULL DEFAULT 0,
    details      TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL
);

-- ============================================================ workflow
CREATE TABLE IF NOT EXISTS workflow_jobs (
    id             TEXT PRIMARY KEY,
    research_id    TEXT NOT NULL REFERENCES core_researches(id) ON DELETE CASCADE,
    stage          TEXT NOT NULL,
    name           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued','running','partial','completed','failed','cancelled','retry_wait','skipped')),
    depends_on     TEXT NOT NULL DEFAULT '[]',
    attempts       INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    progress       REAL NOT NULL DEFAULT 0,
    processed      INTEGER NOT NULL DEFAULT 0,
    total          INTEGER NOT NULL DEFAULT 0,
    result         TEXT NOT NULL DEFAULT '{}',
    error_code     TEXT,
    error_message  TEXT,
    started_at     TEXT,
    finished_at    TEXT,
    correlation_id TEXT,                        -- P6: трассировка запуска
    duration_ms    INTEGER,                     -- P6: латентность этапа
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_jobs_research_stage ON workflow_jobs(research_id, stage);
CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_idempotency ON workflow_jobs(research_id, idempotency_key);

CREATE TABLE IF NOT EXISTS workflow_events (
    id           TEXT PRIMARY KEY,
    seq          INTEGER,
    research_id  TEXT,
    job_id       TEXT,
    event_type   TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'info',
    payload      TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT,                        -- P6: сквозная трассировка
    request_id   TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_research_seq ON workflow_events(research_id, id);

-- ============================================================ reporting
CREATE TABLE IF NOT EXISTS reporting_reports (
    id            TEXT PRIMARY KEY,
    research_id   TEXT NOT NULL REFERENCES core_researches(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'requested',
    formats       TEXT NOT NULL DEFAULT '[]',
    files         TEXT NOT NULL DEFAULT '{}',
    snapshot_hash TEXT,
    warnings      TEXT NOT NULL DEFAULT '[]',
    methodology_version TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    finished_at   TEXT
);

-- ============================================================ audit
CREATE TABLE IF NOT EXISTS audit_log (
    id          TEXT PRIMARY KEY,
    actor       TEXT,
    action      TEXT NOT NULL,
    entity_kind TEXT,
    entity_id   TEXT,
    research_id TEXT,
    request_id  TEXT,
    correlation_id TEXT,
    http_status INTEGER,
    duration_ms INTEGER,
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_research ON audit_log(research_id, created_at);

CREATE TABLE IF NOT EXISTS audit_api_calls (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    target        TEXT NOT NULL,
    url           TEXT,
    http_status   INTEGER,
    duration_ms   INTEGER,
    bytes         INTEGER,
    cached        INTEGER NOT NULL DEFAULT 0,
    error_code    TEXT,
    research_id   TEXT,
    correlation_id TEXT,                        -- P6: связь с внутренним запросом
    request_id    TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_quota_usage (
    id           TEXT PRIMARY KEY,
    scope        TEXT NOT NULL,
    key          TEXT NOT NULL,
    window       TEXT NOT NULL,
    used         REAL NOT NULL DEFAULT 0,
    limit_value  REAL,
    updated_at   TEXT NOT NULL,
    UNIQUE (scope, key, window)
);

CREATE TABLE IF NOT EXISTS core_secrets (
    ref         TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    owner       TEXT NOT NULL,
    ciphertext  TEXT NOT NULL,
    hint        TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- ============================================================ v1.1 (ИД-01…ИД-12)

-- ИД-09: централизованный реестр версионируемых методик.
CREATE TABLE IF NOT EXISTS analytics_methodologies (
    id                  TEXT PRIMARY KEY,
    code                TEXT NOT NULL,
    version             TEXT NOT NULL,
    name                TEXT NOT NULL,
    formula_definition  TEXT NOT NULL DEFAULT '{}',
    parameters          TEXT NOT NULL DEFAULT '{}',
    thresholds          TEXT NOT NULL DEFAULT '{}',
    valid_from          TEXT NOT NULL,
    valid_to            TEXT,
    approval_status     TEXT NOT NULL DEFAULT 'PROVISIONAL'
                        CHECK (approval_status IN ('PROVISIONAL','VALIDATED','DEPRECATED')),
    is_active           INTEGER NOT NULL DEFAULT 0,
    author_user_id      TEXT,
    approver_user_id    TEXT,
    config_checksum     TEXT NOT NULL,
    validation_examples TEXT NOT NULL DEFAULT '[]',
    change_description  TEXT,
    previous_version_id TEXT,
    created_at          TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_methodology_code_version ON analytics_methodologies(code, version);
CREATE INDEX IF NOT EXISTS ix_methodology_active ON analytics_methodologies(code, is_active);

-- ИД-08: справочник критериев TRL со стабильными идентификаторами TRL<n>-C<nn>.
CREATE TABLE IF NOT EXISTS analytics_trl_criteria (
    criterion_code   TEXT PRIMARY KEY,
    trl_level        INTEGER NOT NULL CHECK (trl_level BETWEEN 1 AND 9),
    is_mandatory     INTEGER NOT NULL DEFAULT 1,
    description      TEXT NOT NULL,
    evidence_classes TEXT NOT NULL DEFAULT '[]',
    legacy_code      TEXT,
    methodology_id   TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics_trl_criterion_evidence (
    id             TEXT PRIMARY KEY,
    assessment_id  TEXT NOT NULL REFERENCES analytics_trl(id) ON DELETE CASCADE,
    criterion_code TEXT NOT NULL,
    document_id    TEXT,
    evidence_id    TEXT,
    confirmed      INTEGER NOT NULL DEFAULT 0,
    independence_group_id TEXT,
    note           TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trl_crit_ev ON analytics_trl_criterion_evidence(assessment_id, criterion_code);

-- ИД-10: уверенность — самостоятельный показатель, не F и не P(T<=t).
CREATE TABLE IF NOT EXISTS analytics_confidence (
    id                  TEXT PRIMARY KEY,
    research_id         TEXT NOT NULL,
    technology_id       TEXT,
    subject_kind        TEXT NOT NULL,          -- trl | feasibility | forecast | claim
    subject_id          TEXT,
    confidence          REAL,                   -- 0..1
    independent_groups  INTEGER NOT NULL DEFAULT 0,
    evidence_count      INTEGER NOT NULL DEFAULT 0,
    contradictions      INTEGER NOT NULL DEFAULT 0,
    coverage            REAL,
    basis               TEXT NOT NULL DEFAULT '{}',
    limitations         TEXT NOT NULL DEFAULT '[]',
    methodology_id      TEXT,
    methodology_version TEXT NOT NULL,
    document_set_version TEXT,
    model_id            TEXT,
    model_version       TEXT,
    prompt_version      TEXT,
    input_snapshot      TEXT NOT NULL DEFAULT '{}',
    parameters          TEXT NOT NULL DEFAULT '{}',
    config_checksum     TEXT,
    input_hash          TEXT,
    output_hash         TEXT,
    assessed_by         TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_confidence_research ON analytics_confidence(research_id, subject_kind);

-- ИД-11: группы независимости доказательств.
CREATE TABLE IF NOT EXISTS evidence_independence_groups (
    id                 TEXT PRIMARY KEY,
    research_id        TEXT NOT NULL,
    group_key          TEXT NOT NULL,
    primary_source_ref TEXT,
    primary_document_id TEXT,
    origin_class       TEXT NOT NULL DEFAULT 'PRIMARY',
    members            INTEGER NOT NULL DEFAULT 0,
    first_published_at TEXT,
    basis              TEXT,
    created_at         TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_indep_group ON evidence_independence_groups(research_id, group_key);

-- ИД-05: точки прогноза с серверной политикой представления.
CREATE TABLE IF NOT EXISTS forecast_points (
    id                    TEXT PRIMARY KEY,
    forecast_id           TEXT NOT NULL REFERENCES forecast_runs(id) ON DELETE CASCADE,
    research_id           TEXT NOT NULL,
    target                TEXT NOT NULL,
    scenario_id           TEXT NOT NULL,
    horizon_code          TEXT NOT NULL,
    forecast_horizon_years INTEGER NOT NULL,
    years_from            INTEGER NOT NULL,
    probability_value     REAL,                 -- внутренняя точность NUMERIC(7,6)
    probability_lower     REAL,
    probability_upper     REAL,
    display_mode          TEXT NOT NULL CHECK (display_mode IN ('EXACT','INTERVAL','COARSE','SCENARIO')),
    display_precision     INTEGER NOT NULL DEFAULT 2,
    display_value         REAL,                 -- округлённое значение для показа (или NULL)
    display_text          TEXT,
    uncertainty_class     TEXT NOT NULL,
    calibration_status    TEXT NOT NULL DEFAULT 'NOT_CALIBRATED',
    warning_text          TEXT,
    qualitative           TEXT,
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_forecast_points ON forecast_points(forecast_id, target, scenario_id, forecast_horizon_years);

-- ИД-12: запуски исследования и снимки для воспроизводимости.
CREATE TABLE IF NOT EXISTS research_runs (
    id                   TEXT PRIMARY KEY,
    research_id          TEXT NOT NULL,
    job_id               TEXT,
    document_set_version TEXT NOT NULL,
    query_snapshot       TEXT NOT NULL DEFAULT '{}',
    search_strategy_version TEXT,
    methodology_versions TEXT NOT NULL DEFAULT '{}',
    model_versions       TEXT NOT NULL DEFAULT '{}',
    prompt_versions      TEXT NOT NULL DEFAULT '{}',
    parameters           TEXT NOT NULL DEFAULT '{}',
    input_checksum       TEXT,
    output_checksum      TEXT,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    initiated_by         TEXT,
    status               TEXT NOT NULL DEFAULT 'running'
);
CREATE INDEX IF NOT EXISTS ix_runs_research ON research_runs(research_id, started_at DESC);
