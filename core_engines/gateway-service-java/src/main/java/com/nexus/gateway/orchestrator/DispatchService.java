package com.nexus.gateway.orchestrator;

import com.nexus.gateway.audit.AuditService;
import com.nexus.gateway.config.NexusProperties;
import com.nexus.gateway.security.ClientPrincipal;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeoutException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.context.request.async.DeferredResult;

/**
 * Audits, forwards and answers one request. The servlet thread is released immediately
 * ({@link DeferredResult}); a semaphore bounds how many requests may be in flight so a slow
 * orchestrator produces fast 429s instead of an unbounded backlog.
 */
@Service
public class DispatchService {

    private static final Logger log = LoggerFactory.getLogger(DispatchService.class);

    private final OrchestratorClient orchestrator;
    private final AuditService audit;
    private final Semaphore inflight;

    public DispatchService(OrchestratorClient orchestrator, AuditService audit, NexusProperties properties) {
        this.orchestrator = orchestrator;
        this.audit = audit;
        this.inflight = new Semaphore(properties.maxInflight());
    }

    public DeferredResult<ResponseEntity<Map<String, Object>>> dispatch(
            ClientPrincipal client, String endpoint, String source, String query, String sessionId, String userId) {
        DeferredResult<ResponseEntity<Map<String, Object>>> result =
                new DeferredResult<>(orchestrator.timeoutMs() + 5_000);

        if (!inflight.tryAcquire()) {
            audit.denied(client.name(), client.role().name(), endpoint, "RATE_LIMITED", "max in-flight requests");
            result.setResult(ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS).header("Retry-After", "5")
                    .body(Map.of("status", "RATE_LIMITED", "error", "Too many requests in flight, retry shortly.")));
            return result;
        }

        UUID requestId = UUID.randomUUID();
        String session = sessionId != null ? sessionId : UUID.randomUUID().toString().substring(0, 12);
        try {
            audit.received(requestId, client, endpoint, source, session, query);
        } catch (RuntimeException e) {
            inflight.release();
            log.error("Audit ledger unavailable; refusing request {}", requestId, e);
            result.setResult(ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body(Map.of("status", "AUDIT_UNAVAILABLE", "error", "Request not processed: audit ledger unavailable.")));
            return result;
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("request_id", requestId.toString());
        payload.put("principal", client.name());
        payload.put("role", client.role().name());
        payload.put("session_id", session);
        payload.put("source", source);
        payload.put("query", query);
        if (userId != null) {
            payload.put("user_id", userId);
        }

        long started = System.nanoTime();
        CompletableFuture<Map<String, Object>> pending;
        try {
            pending = orchestrator.send(payload);
        } catch (RuntimeException e) {  // never leak the in-flight permit or leave RECEIVED without COMPLETED
            pending = CompletableFuture.failedFuture(e);
        }
        pending.whenComplete((reply, error) -> {
            try {
                Map<String, Object> body = new LinkedHashMap<>();
                HttpStatus status;
                if (error != null) {
                    Throwable cause = error.getCause() != null ? error.getCause() : error;
                    boolean timeout = error instanceof TimeoutException || cause instanceof TimeoutException;
                    body.put("request_id", requestId.toString());
                    body.put("status", timeout ? "GATEWAY_TIMEOUT" : "ORCHESTRATOR_UNAVAILABLE");
                    body.put("error", timeout ? "The orchestrator did not answer in time." : cause.getMessage());
                    status = timeout ? HttpStatus.GATEWAY_TIMEOUT : HttpStatus.BAD_GATEWAY;
                    log.warn("Request {} failed: {}", requestId, cause.toString());
                } else {
                    body.putAll(reply);
                    body.putIfAbsent("request_id", requestId.toString());
                    status = httpStatusFor(String.valueOf(reply.get("status")));
                }
                long latencyMs = (System.nanoTime() - started) / 1_000_000;
                body.put("gateway_latency_ms", latencyMs);
                audit.completed(requestId, client, endpoint, source, session, body, latencyMs);
                result.setResult(ResponseEntity.status(status).body(body));
            } finally {
                inflight.release();
            }
        });
        return result;
    }

    static HttpStatus httpStatusFor(String orchestratorStatus) {
        return switch (orchestratorStatus) {
            case "OK", "BLOCKED" -> HttpStatus.OK;
            case "INVALID_REQUEST" -> HttpStatus.BAD_REQUEST;
            case "BUSY" -> HttpStatus.SERVICE_UNAVAILABLE;
            case "TIMEOUT" -> HttpStatus.GATEWAY_TIMEOUT;
            default -> HttpStatus.INTERNAL_SERVER_ERROR;
        };
    }
}
