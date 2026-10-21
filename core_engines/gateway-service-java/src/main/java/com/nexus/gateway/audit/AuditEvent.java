package com.nexus.gateway.audit;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.UUID;
import org.hibernate.annotations.Immutable;

/** One row of the append-only audit ledger (UPDATE/DELETE are also rejected by a DB trigger). */
@Entity
@Immutable
@Table(name = "audit_events")
public class AuditEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "request_id", nullable = false)
    private UUID requestId;

    @Column(name = "event_type", nullable = false, length = 16)
    private String eventType;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt = OffsetDateTime.now();

    @Column(name = "client_name", nullable = false, length = 64)
    private String clientName;

    @Column(length = 32)
    private String role;

    @Column(nullable = false, length = 128)
    private String endpoint;

    @Column(length = 16)
    private String source;

    @Column(name = "session_id", length = 128)
    private String sessionId;

    @Column(name = "query_sha256", length = 64, columnDefinition = "bpchar(64)")
    private String querySha256;

    @Column(nullable = false, length = 32)
    private String status;

    @Column(length = 32)
    private String route;

    @Column(name = "security_passed")
    private Boolean securityPassed;

    @Column(name = "input_tokens")
    private Integer inputTokens;

    @Column(name = "output_tokens")
    private Integer outputTokens;

    @Column(name = "cost_usd", precision = 12, scale = 6)
    private BigDecimal costUsd;

    @Column(name = "latency_ms")
    private Integer latencyMs;

    @Column(length = 500)
    private String detail;

    protected AuditEvent() {
    }

    private AuditEvent(Builder b) {
        this.requestId = b.requestId;
        this.eventType = b.eventType;
        this.clientName = b.clientName;
        this.role = b.role;
        this.endpoint = b.endpoint;
        this.source = b.source;
        this.sessionId = b.sessionId;
        this.querySha256 = b.querySha256;
        this.status = b.status;
        this.route = b.route;
        this.securityPassed = b.securityPassed;
        this.inputTokens = b.inputTokens;
        this.outputTokens = b.outputTokens;
        this.costUsd = b.costUsd;
        this.latencyMs = b.latencyMs;
        this.detail = b.detail == null ? null : b.detail.substring(0, Math.min(500, b.detail.length()));
    }

    public static Builder builder(UUID requestId, String eventType, String clientName, String endpoint, String status) {
        return new Builder(requestId, eventType, clientName, endpoint, status);
    }

    public Long getId() { return id; }
    public UUID getRequestId() { return requestId; }
    public String getEventType() { return eventType; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public String getClientName() { return clientName; }
    public String getRole() { return role; }
    public String getEndpoint() { return endpoint; }
    public String getSource() { return source; }
    public String getSessionId() { return sessionId; }
    public String getQuerySha256() { return querySha256; }
    public String getStatus() { return status; }
    public String getRoute() { return route; }
    public Boolean getSecurityPassed() { return securityPassed; }
    public Integer getInputTokens() { return inputTokens; }
    public Integer getOutputTokens() { return outputTokens; }
    public BigDecimal getCostUsd() { return costUsd; }
    public Integer getLatencyMs() { return latencyMs; }
    public String getDetail() { return detail; }

    public static final class Builder {
        private final UUID requestId;
        private final String eventType;
        private final String clientName;
        private final String endpoint;
        private final String status;
        private String role;
        private String source;
        private String sessionId;
        private String querySha256;
        private String route;
        private Boolean securityPassed;
        private Integer inputTokens;
        private Integer outputTokens;
        private BigDecimal costUsd;
        private Integer latencyMs;
        private String detail;

        private Builder(UUID requestId, String eventType, String clientName, String endpoint, String status) {
            this.requestId = requestId;
            this.eventType = eventType;
            this.clientName = clientName;
            this.endpoint = endpoint;
            this.status = status;
        }

        public Builder role(String v) { this.role = v; return this; }
        public Builder source(String v) { this.source = v; return this; }
        public Builder sessionId(String v) { this.sessionId = v; return this; }
        public Builder querySha256(String v) { this.querySha256 = v; return this; }
        public Builder route(String v) { this.route = v; return this; }
        public Builder securityPassed(Boolean v) { this.securityPassed = v; return this; }
        public Builder inputTokens(Integer v) { this.inputTokens = v; return this; }
        public Builder outputTokens(Integer v) { this.outputTokens = v; return this; }
        public Builder costUsd(BigDecimal v) { this.costUsd = v; return this; }
        public Builder latencyMs(Integer v) { this.latencyMs = v; return this; }
        public Builder detail(String v) { this.detail = v; return this; }

        public AuditEvent build() {
            return new AuditEvent(this);
        }
    }
}
