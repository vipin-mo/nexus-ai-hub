package com.nexus.gateway.web;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.nexus.gateway.audit.AuditEventRepository;
import com.nexus.gateway.audit.AuditService;
import com.nexus.gateway.config.SecurityConfig;
import com.nexus.gateway.orchestrator.DispatchService;
import com.nexus.gateway.security.ApiClient;
import com.nexus.gateway.security.ApiClientRepository;
import com.nexus.gateway.security.Hashing;
import com.nexus.gateway.security.Role;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.web.context.request.async.DeferredResult;

@WebMvcTest(GatewayController.class)
@Import(SecurityConfig.class)
class RbacWebTest {

    static final String ADMIN_KEY = "admin-key-0123456789abcdefghij";
    static final String ANALYST_KEY = "analyst-key-0123456789abcdefghij";
    static final String INGEST_KEY = "ingest-key-0123456789abcdefghij";

    @Autowired MockMvc mvc;
    @MockitoBean ApiClientRepository clients;
    @MockitoBean AuditService audit;
    @MockitoBean AuditEventRepository auditEvents;
    @MockitoBean DispatchService dispatch;

    @BeforeEach
    void setUp() {
        register(ADMIN_KEY, "admin-console", Role.ADMIN);
        register(ANALYST_KEY, "analyst-ui", Role.ANALYST);
        register(INGEST_KEY, "audio-ingest", Role.INGEST_SERVICE);
        when(clients.findByKeyHashAndActiveTrue(Hashing.sha256Hex("wrong-key"))).thenReturn(Optional.empty());
        DeferredResult<ResponseEntity<Map<String, Object>>> ok = new DeferredResult<>();
        ok.setResult(ResponseEntity.ok(Map.of("status", "OK", "answer", "fine")));
        when(dispatch.dispatch(any(), anyString(), anyString(), anyString(), any(), any())).thenReturn(ok);
        when(auditEvents.findAllByOrderByCreatedAtDescIdDesc(any())).thenReturn(List.of());
    }

    private void register(String key, String name, Role role) {
        when(clients.findByKeyHashAndActiveTrue(Hashing.sha256Hex(key)))
                .thenReturn(Optional.of(new ApiClient(name, role, Hashing.sha256Hex(key))));
    }

    private MvcResult query(String key, String body) throws Exception {
        var req = post("/api/v1/query").contentType(MediaType.APPLICATION_JSON).content(body);
        if (key != null) {
            req.header("X-API-Key", key);
        }
        return mvc.perform(req).andReturn();
    }

    @Test
    void missingOrWrongKeyIsRejectedAndAudited() throws Exception {
        mvc.perform(post("/api/v1/query").contentType(MediaType.APPLICATION_JSON).content("{\"query\":\"hi\"}"))
                .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.status").value("UNAUTHENTICATED"));
        mvc.perform(post("/api/v1/query").header("X-API-Key", "wrong-key")
                        .contentType(MediaType.APPLICATION_JSON).content("{\"query\":\"hi\"}"))
                .andExpect(status().isUnauthorized());
        verify(audit, org.mockito.Mockito.times(2))
                .denied(eq("anonymous"), isNull(), eq("/api/v1/query"), eq("UNAUTHENTICATED"), anyString());
        verify(dispatch, never()).dispatch(any(), anyString(), anyString(), anyString(), any(), any());
    }

    @Test
    void analystCanQueryButNotReadAudit() throws Exception {
        MvcResult result = query(ANALYST_KEY, "{\"query\":\"What is the AI budget?\",\"sessionId\":\"s1\"}");
        mvc.perform(asyncDispatch(result)).andExpect(status().isOk()).andExpect(jsonPath("$.answer").value("fine"));
        mvc.perform(get("/api/v1/audit").header("X-API-Key", ANALYST_KEY)).andExpect(status().isForbidden());
        verify(audit).denied("analyst-ui", "ANALYST", "/api/v1/audit", "FORBIDDEN", "role lacks permission");
    }

    @Test
    void adminCanReadAudit() throws Exception {
        mvc.perform(get("/api/v1/audit?limit=10").header("X-API-Key", ADMIN_KEY)).andExpect(status().isOk());
    }

    @Test
    void ingestServiceCanOnlySubmitTranscripts() throws Exception {
        mvc.perform(post("/api/v1/query").header("X-API-Key", INGEST_KEY)
                        .contentType(MediaType.APPLICATION_JSON).content("{\"query\":\"hi\"}"))
                .andExpect(status().isForbidden());
        MvcResult result = mvc.perform(post("/api/v1/audio/transcripts").header("X-API-Key", INGEST_KEY)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"transcript\":\"what are the safety gates\",\"audioFile\":\"a.wav\",\"speechRatio\":0.6}"))
                .andReturn();
        mvc.perform(asyncDispatch(result)).andExpect(status().isOk());
        verify(dispatch).dispatch(any(), eq("/api/v1/audio/transcripts"), eq("audio"),
                                  eq("what are the safety gates"), isNull(), isNull());
    }

    @Test
    void invalidBodiesAreRejectedBeforeDispatch() throws Exception {
        mvc.perform(post("/api/v1/query").header("X-API-Key", ANALYST_KEY)
                        .contentType(MediaType.APPLICATION_JSON).content("{\"query\":\"\"}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.status").value("INVALID_REQUEST"));
        mvc.perform(post("/api/v1/query").header("X-API-Key", ANALYST_KEY)
                        .contentType(MediaType.APPLICATION_JSON).content("{\"query\":\"hi\",\"sessionId\":\"../etc\"}"))
                .andExpect(status().isBadRequest());
        verify(dispatch, never()).dispatch(any(), anyString(), anyString(), anyString(), any(), any());
    }

    @Test
    void numericSessionIdIsCoercedInsteadOfCrashing() throws Exception {
        // The old controller cast payload values to String and returned HTTP 500 here.
        MvcResult result = query(ANALYST_KEY, "{\"query\":\"hi\",\"sessionId\":42}");
        mvc.perform(asyncDispatch(result)).andExpect(status().isOk());
        verify(dispatch).dispatch(any(), eq("/api/v1/query"), eq("text"), eq("hi"), eq("42"), isNull());
    }

    @Test
    void unknownEndpointsAreDeniedByDefault() throws Exception {
        mvc.perform(get("/api/v1/admin/secrets").header("X-API-Key", ADMIN_KEY)).andExpect(status().isForbidden());
    }

    @Test
    void meReportsRoleAndPermissions() throws Exception {
        mvc.perform(get("/api/v1/me").header("X-API-Key", ADMIN_KEY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.role").value("ADMIN"))
                .andExpect(jsonPath("$.permissions[0]").value("AUDIT_READ"));
    }
}
