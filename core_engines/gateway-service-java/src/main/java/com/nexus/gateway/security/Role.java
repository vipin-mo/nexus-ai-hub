package com.nexus.gateway.security;

import java.util.EnumSet;
import java.util.Set;

/** Roles and the permissions they grant (least privilege, see access_control_policy.md). */
public enum Role {
    ADMIN(EnumSet.of(Permission.QUERY, Permission.AUDIT_READ)),
    ANALYST(EnumSet.of(Permission.QUERY)),
    INGEST_SERVICE(EnumSet.of(Permission.AUDIO_INGEST));

    private final Set<Permission> permissions;

    Role(Set<Permission> permissions) {
        this.permissions = permissions;
    }

    public Set<Permission> permissions() {
        return permissions;
    }

    public enum Permission {
        QUERY, AUDIT_READ, AUDIO_INGEST;

        public String authority() {
            return "PERM_" + name();
        }
    }
}
