package com.nexus.gateway.audit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.nexus.gateway.security.ApiClient;
import com.nexus.gateway.security.ApiClientRepository;
import com.nexus.gateway.security.Role;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.data.jpa.test.autoconfigure.DataJpaTest;
import org.springframework.boot.jdbc.test.autoconfigure.AutoConfigureTestDatabase;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;

/** Runs the real Flyway migration against PostgreSQL 16 and checks the ledger's guarantees. */
@DataJpaTest
@Testcontainers
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
class AuditLedgerIT {

    @Container
    @ServiceConnection
    static PostgreSQLContainer postgres = new PostgreSQLContainer("postgres:16-alpine");

    @Autowired AuditEventRepository events;
    @Autowired ApiClientRepository clients;
    @Autowired JdbcTemplate jdbc;

    @Test
    void schemaIsCreatedByFlywayAndEntitiesValidate() {
        clients.saveAndFlush(new ApiClient("analyst-ui", Role.ANALYST, "a".repeat(64)));
        assertThat(clients.findByKeyHashAndActiveTrue("a".repeat(64))).isPresent();
        Integer migrations = jdbc.queryForObject("select count(*) from flyway_schema_history where success", Integer.class);
        assertThat(migrations).isEqualTo(1);
    }

    @Test
    @Transactional(propagation = Propagation.NOT_SUPPORTED) // each statement in its own transaction
    void ledgerIsAppendOnly() {
        UUID requestId = UUID.randomUUID();
        events.saveAndFlush(AuditEvent.builder(requestId, "RECEIVED", "analyst-ui", "/api/v1/query", "RECEIVED")
                .role("ANALYST").querySha256("b".repeat(64)).build());

        assertThatThrownBy(() -> jdbc.update("update audit_events set status = 'TAMPERED' where request_id = ?", requestId))
                .hasMessageContaining("append-only");
        assertThatThrownBy(() -> jdbc.update("delete from audit_events where request_id = ?", requestId))
                .hasMessageContaining("append-only");
        assertThatThrownBy(() -> jdbc.execute("truncate audit_events"))
                .hasMessageContaining("append-only");
        Integer remaining = jdbc.queryForObject(
                "select count(*) from audit_events where request_id = ? and status = 'RECEIVED'", Integer.class, requestId);
        assertThat(remaining).isEqualTo(1);
    }

    @Test
    void oneEventTypePerRequest() {
        UUID requestId = UUID.randomUUID();
        events.saveAndFlush(AuditEvent.builder(requestId, "RECEIVED", "c", "/api/v1/query", "RECEIVED").build());
        assertThatThrownBy(() -> events.saveAndFlush(
                AuditEvent.builder(requestId, "RECEIVED", "c", "/api/v1/query", "RECEIVED").build()))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
    }
}
