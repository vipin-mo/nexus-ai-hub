package com.nexus.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.context.request.async.DeferredResult;
import org.springframework.web.socket.client.standard.StandardWebSocketClient;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketHttpHeaders;
import org.springframework.web.socket.CloseStatus;
import java.net.URI;
import java.util.HashMap;
import java.util.Map;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

@RestController
@RequestMapping("/api/v1/gateway")
public class GatewayController {

    @Value("${nexus.orchestrator.ws-uri:ws://localhost:8765}")
    private String pythonWsUri;

    private final StandardWebSocketClient webSocketClient = new StandardWebSocketClient();
    private final ObjectMapper objectMapper = new ObjectMapper();

    @PostMapping("/dispatch")
    public DeferredResult<Map<String, Object>> dispatchToAgentEngine(@RequestBody Map<String, Object> payload) {
        DeferredResult<Map<String, Object>> deferredResult = new DeferredResult<>(30000L);

        deferredResult.onTimeout(() -> {
            Map<String, Object> timeoutResponse = new HashMap<>();
            timeoutResponse.put("status", "GATEWAY_TIMEOUT");
            timeoutResponse.put("message", "Orchestration engine did not respond within 30 seconds.");
            deferredResult.setResult(timeoutResponse);
        });

        String queryValue;
        String sessionId = (String) payload.getOrDefault("session_id", "docker_network_session_001");

        if (payload.containsKey("frame_id") && payload.containsKey("amplitude_db")) {
            Object frameId = payload.get("frame_id");
            Object amplitude = payload.get("amplitude_db");
            queryValue = "Audio telemetry trigger event. Frame ID: " + frameId + " with Energy: " + amplitude + " dB.";
        } else {
            queryValue = (String) payload.getOrDefault("query", payload.getOrDefault("input_query", "Ping audit payload."));
        }

        Map<String, Object> cleanPayload = new HashMap<>();
        cleanPayload.put("session_id", sessionId);
        cleanPayload.put("input_query", queryValue);
        cleanPayload.put("cleaned_query", queryValue);
        cleanPayload.put("security_passed", true);
        cleanPayload.put("tokens_used", 0);

        try {
            URI targetUri = URI.create(pythonWsUri.trim());

            webSocketClient.execute(new TextWebSocketHandler() {
                @Override
                public void afterConnectionEstablished(WebSocketSession session) throws Exception {
                    String jsonPayload = objectMapper.writeValueAsString(cleanPayload);
                    session.sendMessage(new TextMessage(jsonPayload));
                }

                @Override
                protected void handleTextMessage(WebSocketSession session, TextMessage message) {
                    try {
                        Map<String, Object> parsedMap = objectMapper.readValue(
                            message.getPayload(),
                            new TypeReference<Map<String, Object>>() {}
                        );
                        deferredResult.setResult(parsedMap);
                    } catch (Exception e) {
                        Map<String, Object> responseMap = new HashMap<>();
                        responseMap.put("status", "ERROR_PARSING_STREAM");
                        responseMap.put("raw_output", message.getPayload());
                        deferredResult.setResult(responseMap);
                    } finally {
                        try { session.close(CloseStatus.NORMAL); } catch (Exception ignored) {}
                    }
                }

                @Override
                public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
                    if (!deferredResult.isSetOrExpired()) {
                        Map<String, Object> responseMap = new HashMap<>();
                        responseMap.put("status", "CONNECTION_DROPPED");
                        responseMap.put("details", "WebSocket channel closed before agent execution completed.");
                        deferredResult.setResult(responseMap);
                    }
                }

                @Override
                public void handleTransportError(WebSocketSession session, Throwable exception) {
                    if (!deferredResult.isSetOrExpired()) {
                        Map<String, Object> responseMap = new HashMap<>();
                        responseMap.put("status", "CONNECTION_FAILURE");
                        responseMap.put("details", exception.getMessage());
                        deferredResult.setResult(responseMap);
                    }
                }
            }, new WebSocketHttpHeaders(), targetUri);

        } catch (Exception e) {
            Map<String, Object> responseMap = new HashMap<>();
            responseMap.put("status", "HANDSHAKE_ERROR");
            responseMap.put("details", e.getMessage());
            deferredResult.setResult(responseMap);
        }

        return deferredResult;
    }
}
