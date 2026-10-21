package com.nexus.gateway.web;

import com.nexus.gateway.audit.AuditEvent;
import com.nexus.gateway.audit.AuditEventRepository;
import com.nexus.gateway.orchestrator.DispatchService;
import com.nexus.gateway.security.ClientPrincipal;
import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.context.request.async.DeferredResult;

@RestController
@Validated
@RequestMapping("/api/v1")
public class GatewayController {

    private static final String ID = "^[A-Za-z0-9_.:@-]{1,128}$";

    private final DispatchService dispatch;
    private final AuditEventRepository auditEvents;

    public GatewayController(DispatchService dispatch, AuditEventRepository auditEvents) {
        this.dispatch = dispatch;
        this.auditEvents = auditEvents;
    }

    public record QueryRequest(
            @NotBlank @Size(max = 4000) String query,
            @Pattern(regexp = ID) String sessionId,
            @Pattern(regexp = ID) String userId) {
    }

    public record TranscriptRequest(
            @NotBlank @Size(max = 4000) String transcript,
            @Size(max = 255) String audioFile,
            @PositiveOrZero Long durationMs,
            @DecimalMin("0.0") @DecimalMax("1.0") Double speechRatio,
            @PositiveOrZero Long sttLatencyMs,
            @Pattern(regexp = ID) String sessionId) {
    }

    @PostMapping("/query")
    public DeferredResult<ResponseEntity<Map<String, Object>>> query(
            @AuthenticationPrincipal ClientPrincipal client, @Valid @RequestBody QueryRequest request) {
        return dispatch.dispatch(client, "/api/v1/query", "text", request.query(), request.sessionId(),
                                 request.userId());
    }

    @PostMapping("/audio/transcripts")
    public DeferredResult<ResponseEntity<Map<String, Object>>> transcript(
            @AuthenticationPrincipal ClientPrincipal client, @Valid @RequestBody TranscriptRequest request) {
        return dispatch.dispatch(client, "/api/v1/audio/transcripts", "audio", request.transcript(),
                                 request.sessionId(), null);
    }

    @GetMapping("/audit")
    public List<AuditEvent> audit(@RequestParam(defaultValue = "50") @Min(1) @Max(500) int limit) {
        return auditEvents.findAllByOrderByCreatedAtDescIdDesc(PageRequest.of(0, limit));
    }

    @GetMapping("/me")
    public Map<String, Object> me(@AuthenticationPrincipal ClientPrincipal client) {
        return Map.of("client", client.name(), "role", client.role().name(),
                      "permissions", client.role().permissions().stream().map(Enum::name)
                              .sorted().collect(Collectors.toList()));
    }
}
