package com.nexus.gateway.orchestrator;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.nexus.gateway.audit.AuditService;
import com.nexus.gateway.config.NexusProperties;
import com.nexus.gateway.security.ClientPrincipal;
import com.nexus.gateway.security.Role;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import tools.jackson.databind.json.JsonMapper;

class DispatchServiceTest {

    static NexusProperties props(String uri, int maxInflight) {
        return new NexusProperties(new NexusProperties.Orchestrator(uri, "", Duration.ofSeconds(5)), maxInflight,
                                   new NexusProperties.Clients("", "", ""));
    }

    @Test
    @SuppressWarnings("unchecked")
    void synchronousSendFailureReleasesPermitAndIsAudited() {
        OrchestratorClient orchestrator = mock(OrchestratorClient.class);
        AuditService audit = mock(AuditService.class);
        when(orchestrator.timeoutMs()).thenReturn(5_000L);
        when(orchestrator.send(anyMap())).thenThrow(new IllegalArgumentException("hostname can't be null"))
                .thenReturn(CompletableFuture.completedFuture(Map.of("status", "OK", "answer", "fine")));
        DispatchService dispatch = new DispatchService(orchestrator, audit, props("ws://localhost:8765", 1));
        ClientPrincipal client = new ClientPrincipal("analyst-ui", Role.ANALYST);

        var first = (ResponseEntity<Map<String, Object>>) dispatch.dispatch(client, "/api/v1/query", "text", "q1", null, null).getResult();
        assertThat(first.getStatusCode().value()).isEqualTo(502);
        verify(audit).completed(any(), eq(client), eq("/api/v1/query"), eq("text"), anyString(), anyMap(), anyLong());

        // With max-inflight 1, a leaked permit would turn this into a 429.
        var second = (ResponseEntity<Map<String, Object>>) dispatch.dispatch(client, "/api/v1/query", "text", "q2", null, null).getResult();
        assertThat(second.getStatusCode().value()).isEqualTo(200);
    }

    @Test
    void malformedOrchestratorUriFailsAtStartup() {
        assertThatThrownBy(() -> new OrchestratorClient(props("ws://orchestrator:tcp://10.0.0.1:8765", 4), JsonMapper.builder().build()))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("Invalid nexus.orchestrator.ws-uri");
    }
}
