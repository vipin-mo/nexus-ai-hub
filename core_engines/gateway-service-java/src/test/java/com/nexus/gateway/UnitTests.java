package com.nexus.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import com.nexus.gateway.orchestrator.DispatchServiceStatusAccess;
import com.nexus.gateway.security.ClientPrincipal;
import com.nexus.gateway.security.Hashing;
import com.nexus.gateway.security.Role;
import com.nexus.gateway.security.Role.Permission;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.GrantedAuthority;

class UnitTests {

    @Test
    void sha256MatchesKnownVector() {
        assertThat(Hashing.sha256Hex("abc"))
                .isEqualTo("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    }

    @Test
    void rolesFollowLeastPrivilege() {
        assertThat(Role.ADMIN.permissions()).containsExactlyInAnyOrder(Permission.QUERY, Permission.AUDIT_READ);
        assertThat(Role.ANALYST.permissions()).containsExactly(Permission.QUERY);
        assertThat(Role.INGEST_SERVICE.permissions()).containsExactly(Permission.AUDIO_INGEST);
    }

    @Test
    void principalAuthoritiesIncludeRoleAndPermissions() {
        var authorities = new ClientPrincipal("analyst-ui", Role.ANALYST).authorities().stream()
                .map(GrantedAuthority::getAuthority).toList();
        assertThat(authorities).containsExactlyInAnyOrder("ROLE_ANALYST", "PERM_QUERY");
    }

    @Test
    void orchestratorStatusesMapToHttp() {
        assertThat(DispatchServiceStatusAccess.map("OK")).isEqualTo(HttpStatus.OK);
        assertThat(DispatchServiceStatusAccess.map("BLOCKED")).isEqualTo(HttpStatus.OK);
        assertThat(DispatchServiceStatusAccess.map("BUSY")).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        assertThat(DispatchServiceStatusAccess.map("TIMEOUT")).isEqualTo(HttpStatus.GATEWAY_TIMEOUT);
        assertThat(DispatchServiceStatusAccess.map("ERROR")).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
    }
}
