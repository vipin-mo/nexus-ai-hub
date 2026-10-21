package com.nexus.gateway.security;

import com.nexus.gateway.config.NexusProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * Registers the three standard clients from environment variables on startup. Changing a key in
 * the environment rotates it: the stored hash is replaced, the old key stops working.
 */
@Component
public class ApiClientBootstrap implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(ApiClientBootstrap.class);

    private final ApiClientRepository clients;
    private final NexusProperties properties;

    public ApiClientBootstrap(ApiClientRepository clients, NexusProperties properties) {
        this.clients = clients;
        this.properties = properties;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        NexusProperties.Clients keys = properties.clients();
        upsert("admin-console", Role.ADMIN, keys.adminKey());
        upsert("analyst-ui", Role.ANALYST, keys.analystKey());
        upsert("audio-ingest", Role.INGEST_SERVICE, keys.ingestKey());
    }

    private void upsert(String name, Role role, String key) {
        if (key == null || key.isBlank()) {
            log.warn("No API key configured for client '{}'; it cannot authenticate", name);
            return;
        }
        if (key.length() < 24) {
            throw new IllegalStateException("API key for '" + name + "' is too short (min 24 characters)");
        }
        String hash = Hashing.sha256Hex(key.strip());
        ApiClient client = clients.findByName(name).orElse(null);
        if (client == null) {
            clients.save(new ApiClient(name, role, hash));
            log.info("Registered API client '{}' with role {}", name, role);
        } else if (!client.getKeyHash().equals(hash) || client.getRole() != role) {
            client.rotate(role, hash);
            log.info("Rotated API key for client '{}'", name);
        }
    }
}
