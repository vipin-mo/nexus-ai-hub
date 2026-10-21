-- API clients: one row per calling application. Only the SHA-256 hash of the key is stored.
CREATE TABLE api_clients (
    id          BIGSERIAL    PRIMARY KEY,
    name        VARCHAR(64)  NOT NULL UNIQUE,
    role        VARCHAR(32)  NOT NULL CHECK (role IN ('ADMIN', 'ANALYST', 'INGEST_SERVICE')),
    key_hash    CHAR(64)     NOT NULL UNIQUE,
    active      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    rotated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Audit ledger: append-only. Each request writes RECEIVED before it is forwarded and
-- COMPLETED after the orchestrator answers; rejected requests write DENIED.
-- The query text is never stored, only its SHA-256 hash.
CREATE TABLE audit_events (
    id               BIGSERIAL     PRIMARY KEY,
    request_id       UUID          NOT NULL,
    event_type       VARCHAR(16)   NOT NULL CHECK (event_type IN ('RECEIVED', 'COMPLETED', 'DENIED')),
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    client_name      VARCHAR(64)   NOT NULL,
    role             VARCHAR(32),
    endpoint         VARCHAR(128)  NOT NULL,
    source           VARCHAR(16),
    session_id       VARCHAR(128),
    query_sha256     CHAR(64),
    status           VARCHAR(32)   NOT NULL,
    route            VARCHAR(32),
    security_passed  BOOLEAN,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    cost_usd         NUMERIC(12, 6),
    latency_ms       INTEGER,
    detail           VARCHAR(500),
    UNIQUE (request_id, event_type)
);
CREATE INDEX audit_events_created_at_idx ON audit_events (created_at DESC);
CREATE INDEX audit_events_client_idx ON audit_events (client_name, created_at DESC);

CREATE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_events_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();

CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only();
