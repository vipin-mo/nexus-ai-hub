package com.nexus.gateway.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "nexus")
public record NexusProperties(Orchestrator orchestrator, int maxInflight, Clients clients) {

    public record Orchestrator(String wsUri, String internalToken, Duration timeout) {
    }

    public record Clients(String adminKey, String analystKey, String ingestKey) {
    }
}
