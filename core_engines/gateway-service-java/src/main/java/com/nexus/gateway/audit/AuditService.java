package com.nexus.gateway.audit;

import com.nexus.gateway.security.ClientPrincipal;
import com.nexus.gateway.security.Hashing;
import java.math.BigDecimal;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Writes the audit ledger. {@link #received} is fail-closed: if it throws, the request is not
 * forwarded (no unaudited AI calls). Completion and denial records are best-effort and logged on
 * failure, because the caller has already been answered or rejected.
 */
@Service
public class AuditService {

    private static final Logger log = LoggerFactory.getLogger(AuditService.class);

    private final AuditEventRepository events;

    public AuditService(AuditEventRepository events) {
        this.events = events;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void received(UUID requestId, ClientPrincipal client, String endpoint, String source, String sessionId,
                         String query) {
        events.save(AuditEvent.builder(requestId, "RECEIVED", client.name(), endpoint, "RECEIVED")
                .role(client.role().name()).source(source).sessionId(sessionId)
                .querySha256(Hashing.sha256Hex(query)).build());
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void completed(UUID requestId, ClientPrincipal client, String endpoint, String source, String sessionId,
                          Map<String, Object> reply, long latencyMs) {
        try {
            Map<?, ?> route = reply.get("route") instanceof Map<?, ?> m ? m : Map.of();
            Map<?, ?> security = reply.get("security") instanceof Map<?, ?> m ? m : Map.of();
            Map<?, ?> usage = reply.get("usage") instanceof Map<?, ?> m ? m : Map.of();
            events.save(AuditEvent.builder(requestId, "COMPLETED", client.name(), endpoint,
                            String.valueOf(reply.getOrDefault("status", "UNKNOWN")))
                    .role(client.role().name()).source(source).sessionId(sessionId)
                    .route(route.get("intent") instanceof String s ? s : null)
                    .securityPassed(security.get("passed") instanceof Boolean b ? b : null)
                    .inputTokens(asInt(usage.get("input_tokens")))
                    .outputTokens(asInt(usage.get("output_tokens")))
                    .costUsd(usage.get("cost_usd") instanceof Number n ? BigDecimal.valueOf(n.doubleValue()) : null)
                    .latencyMs((int) latencyMs)
                    .detail(reply.get("error") instanceof String e ? e : null)
                    .build());
        } catch (RuntimeException e) {
            log.error("Failed to write COMPLETED audit event for {}", requestId, e);
        }
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void denied(String clientName, String role, String endpoint, String status, String detail) {
        try {
            events.save(AuditEvent.builder(UUID.randomUUID(), "DENIED", clientName, endpoint, status)
                    .role(role).detail(detail).build());
        } catch (RuntimeException e) {
            log.error("Failed to write DENIED audit event for {} on {}", clientName, endpoint, e);
        }
    }

    private static Integer asInt(Object value) {
        return value instanceof Number n ? n.intValue() : null;
    }
}
