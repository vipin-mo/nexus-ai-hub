package com.nexus.gateway.orchestrator;

import com.nexus.gateway.config.NexusProperties;
import jakarta.websocket.ContainerProvider;
import jakarta.websocket.WebSocketContainer;
import java.net.URI;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketHttpHeaders;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.client.standard.StandardWebSocketClient;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;

/**
 * Sends one request to the Python orchestrator over WebSocket and completes with its JSON reply.
 * Handshake failures, transport errors, early closes and timeouts all complete the future
 * exceptionally, so callers fail fast instead of waiting for a reply that will never come.
 */
@Component
public class OrchestratorClient {

    private static final int MAX_MESSAGE_BYTES = 512 * 1024;

    private final StandardWebSocketClient client;
    private final JsonMapper json;
    private final URI uri;
    private final String internalToken;
    private final long timeoutMs;

    public OrchestratorClient(NexusProperties properties, JsonMapper json) {
        WebSocketContainer container = ContainerProvider.getWebSocketContainer();
        container.setDefaultMaxTextMessageBufferSize(MAX_MESSAGE_BYTES);
        this.client = new StandardWebSocketClient(container);
        this.json = json;
        this.uri = URI.create(properties.orchestrator().wsUri().strip());
        if (uri.getHost() == null || uri.getPort() <= 0) {  // fail at startup, not on the first request
            throw new IllegalStateException("Invalid nexus.orchestrator.ws-uri: " + uri);
        }
        this.internalToken = properties.orchestrator().internalToken();
        this.timeoutMs = properties.orchestrator().timeout().toMillis();
    }

    public long timeoutMs() {
        return timeoutMs;
    }

    public CompletableFuture<Map<String, Object>> send(Map<String, Object> payload) {
        CompletableFuture<Map<String, Object>> reply = new CompletableFuture<>();
        AtomicReference<WebSocketSession> sessionRef = new AtomicReference<>();
        String body = json.writeValueAsString(payload);

        TextWebSocketHandler handler = new TextWebSocketHandler() {
            @Override
            public void afterConnectionEstablished(WebSocketSession session) throws Exception {
                sessionRef.set(session);
                session.sendMessage(new TextMessage(body));
            }

            @Override
            protected void handleTextMessage(WebSocketSession session, TextMessage message) {
                try {
                    reply.complete(json.readValue(message.getPayload(), new TypeReference<Map<String, Object>>() { }));
                } catch (RuntimeException e) {
                    reply.completeExceptionally(new OrchestratorException("unparseable orchestrator reply", e));
                }
            }

            @Override
            public void handleTransportError(WebSocketSession session, Throwable exception) {
                reply.completeExceptionally(new OrchestratorException("transport error", exception));
            }

            @Override
            public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
                reply.completeExceptionally(new OrchestratorException("connection closed before reply: " + status));
            }
        };

        WebSocketHttpHeaders headers = new WebSocketHttpHeaders();
        if (internalToken != null && !internalToken.isBlank()) {
            headers.add("Authorization", "Bearer " + internalToken);
        }
        try {
            client.execute(handler, headers, uri).whenComplete((session, error) -> {
                if (error != null) {
                    reply.completeExceptionally(new OrchestratorException("handshake with " + uri + " failed", error));
                }
            });
        } catch (RuntimeException e) {  // some failures are thrown synchronously instead of via the future
            reply.completeExceptionally(new OrchestratorException("could not connect to " + uri, e));
        }

        return reply.orTimeout(timeoutMs, TimeUnit.MILLISECONDS).whenComplete((r, e) -> {
            WebSocketSession session = sessionRef.get();
            if (session != null && session.isOpen()) {
                try {
                    session.close(CloseStatus.NORMAL);
                } catch (Exception ignored) {
                    // closing is best-effort
                }
            }
        });
    }

    public static class OrchestratorException extends RuntimeException {
        public OrchestratorException(String message) {
            super(message);
        }

        public OrchestratorException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
