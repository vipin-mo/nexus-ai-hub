package com.nexus.gateway.security;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;

/** The authenticated API client. Its role is decided here, never by the request body. */
public record ClientPrincipal(String name, Role role) {

    public Collection<GrantedAuthority> authorities() {
        List<GrantedAuthority> out = new ArrayList<>();
        out.add(new SimpleGrantedAuthority("ROLE_" + role.name()));
        role.permissions().forEach(p -> out.add(new SimpleGrantedAuthority(p.authority())));
        return out;
    }
}
