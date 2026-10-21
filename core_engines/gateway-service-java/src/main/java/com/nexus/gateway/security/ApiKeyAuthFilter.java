package com.nexus.gateway.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Resolves the {@code X-API-Key} header to an active {@link ApiClient}. Requests without a valid key
 * stay anonymous and are rejected by the authorization rules in {@code SecurityConfig}.
 */
public class ApiKeyAuthFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-API-Key";

    private final ApiClientRepository clients;

    public ApiKeyAuthFilter(ApiClientRepository clients) {
        this.clients = clients;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String key = request.getHeader(HEADER);
        if (key != null && !key.isBlank()) {
            clients.findByKeyHashAndActiveTrue(Hashing.sha256Hex(key.strip())).ifPresent(client -> {
                ClientPrincipal principal = new ClientPrincipal(client.getName(), client.getRole());
                var auth = new UsernamePasswordAuthenticationToken(principal, null, principal.authorities());
                SecurityContextHolder.getContext().setAuthentication(auth);
            });
        }
        chain.doFilter(request, response);
    }
}
