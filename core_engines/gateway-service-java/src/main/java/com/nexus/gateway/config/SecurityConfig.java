package com.nexus.gateway.config;

import com.nexus.gateway.audit.AuditService;
import com.nexus.gateway.security.ApiClientRepository;
import com.nexus.gateway.security.ApiKeyAuthFilter;
import com.nexus.gateway.security.ClientPrincipal;
import com.nexus.gateway.security.Role.Permission;
import jakarta.servlet.DispatcherType;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.AnonymousAuthenticationFilter;

@Configuration
public class SecurityConfig {

    @Bean
    SecurityFilterChain api(HttpSecurity http, ApiClientRepository clients, AuditService audit) throws Exception {
        http.csrf(AbstractHttpConfigurer::disable)   // stateless API authenticated by header, no cookies
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .httpBasic(AbstractHttpConfigurer::disable)
            .formLogin(AbstractHttpConfigurer::disable)
            .addFilterBefore(new ApiKeyAuthFilter(clients), AnonymousAuthenticationFilter.class)
            .authorizeHttpRequests(auth -> auth
                // DeferredResult replies are written in a second (ASYNC) dispatch of a request that was
                // already authorised on its first dispatch; ERROR dispatches render error bodies.
                .dispatcherTypeMatchers(DispatcherType.ASYNC, DispatcherType.ERROR).permitAll()
                .requestMatchers("/actuator/health/**", "/actuator/health", "/actuator/info").permitAll()
                .requestMatchers("/actuator/prometheus").hasAuthority(Permission.AUDIT_READ.authority())
                .requestMatchers(HttpMethod.POST, "/api/v1/query").hasAuthority(Permission.QUERY.authority())
                .requestMatchers(HttpMethod.POST, "/api/v1/audio/transcripts")
                    .hasAuthority(Permission.AUDIO_INGEST.authority())
                .requestMatchers(HttpMethod.GET, "/api/v1/audit").hasAuthority(Permission.AUDIT_READ.authority())
                .requestMatchers(HttpMethod.GET, "/api/v1/me").authenticated()
                .requestMatchers("/error").permitAll()
                .anyRequest().denyAll())
            .exceptionHandling(e -> e
                .authenticationEntryPoint((req, res, ex) -> {
                    audit.denied("anonymous", null, req.getRequestURI(), "UNAUTHENTICATED",
                                 req.getHeader(ApiKeyAuthFilter.HEADER) == null ? "missing API key" : "invalid API key");
                    write(res, 401, "UNAUTHENTICATED", "A valid X-API-Key header is required.");
                })
                .accessDeniedHandler((req, res, ex) -> {
                    ClientPrincipal p = principal();
                    audit.denied(p == null ? "unknown" : p.name(), p == null ? null : p.role().name(),
                                 req.getRequestURI(), "FORBIDDEN", "role lacks permission");
                    write(res, 403, "FORBIDDEN", "Your role is not allowed to call " + req.getRequestURI() + ".");
                }));
        return http.build();
    }

    private static ClientPrincipal principal() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        return auth != null && auth.getPrincipal() instanceof ClientPrincipal p ? p : null;
    }

    private static void write(HttpServletResponse res, int status, String code, String message) throws IOException {
        res.setStatus(status);
        res.setContentType(MediaType.APPLICATION_JSON_VALUE);
        res.getWriter().write("{\"status\":\"" + code + "\",\"error\":\"" + message.replace("\"", "'") + "\"}");
    }
}
