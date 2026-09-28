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

    // Extracted dynamic variable string to ensure clean container mesh discovery bindings
    @Value("${nexus.orchestrator.ws-uri:ws://localhost:8765}")
    private String pythonWsUri;

    @PostMapping("/dispatch")
    public DeferredResult<Map<String, Object>> dispatchToAgentEngine(@RequestBody Map<String, Object> payload) {
        DeferredResult<Map<String, Object>> deferredResult = new DeferredResult<>(30000L);
        ObjectMapper objectMapper = new ObjectMapper();

        // 1. Normalize query parameters and capture input values safely
        String queryValue = (String) payload.getOrDefault("query", payload.getOrDefault("input_query", "Ping audit payload."));
        String sessionId = (String) payload.getOrDefault("session_id", "docker_network_session_001");

        // 2. Build a clean payload structural dictionary matching Python's expected AgentState schema
        Map<String, Object> cleanPayload = new HashMap<>();
        cleanPayload.put("session_id", sessionId);
        cleanPayload.put("input_query", queryValue);
        cleanPayload.put("cleaned_query", queryValue);
        cleanPayload.put("security_passed", true);
        cleanPayload.put("tokens_used", 0);

        System.out.println("☕ [Java Gateway Broker] Passing payload down network socket for session: " + sessionId);

        try {
            StandardWebSocketClient client = new StandardWebSocketClient();
            URI targetUri = URI.create(pythonWsUri.trim());

            System.out.println("🔌 [Java Gateway] Attempting WebSocket handshake with network target: " + targetUri);

            client.execute(new TextWebSocketHandler() {
                @Override
                public void afterConnectionEstablished(WebSocketSession session) throws Exception {
                    System.out.println("✅ [Java Gateway] WebSocket network channel handshakes completed successfully!");
                    String jsonPayload = objectMapper.writeValueAsString(cleanPayload);
                    session.sendMessage(new TextMessage(jsonPayload));
                }

                @Override
                protected void handleTextMessage(WebSocketSession session, TextMessage message) throws Exception {
                    System.out.println("📥 [Java Gateway] Extracted async response frame from orchestration hub platform.");
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
                    }
                    session.close(CloseStatus.NORMAL);
                }

                @Override
                public void handleTransportError(WebSocketSession session, Throwable exception) throws Exception {
                    System.err.println("❌ [Java Gateway] Transport boundary fault caught: " + exception.getMessage());
                    Map<String, Object> responseMap = new HashMap<>();
                    responseMap.put("status", "CONNECTION_FAILURE");
                    responseMap.put("details", exception.getMessage());
                    deferredResult.setResult(responseMap);
                }
            }, new WebSocketHttpHeaders(), targetUri);

        } catch (Exception e) {
            System.err.println("❌ [Java Gateway] Intermittent network processing exception discovered: " + e.getMessage());
            Map<String, Object> responseMap = new HashMap<>();
            responseMap.put("status", "HANDSHAKE_ERROR");
            responseMap.put("details", e.getMessage());
            deferredResult.setResult(responseMap);
        }

        return deferredResult;
    }
}
