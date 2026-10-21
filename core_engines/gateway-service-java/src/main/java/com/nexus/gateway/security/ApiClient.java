package com.nexus.gateway.security;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;

@Entity
@Table(name = "api_clients")
public class ApiClient {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 64)
    private String name;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private Role role;

    @Column(name = "key_hash", nullable = false, unique = true, length = 64, columnDefinition = "bpchar(64)")
    private String keyHash;

    @Column(nullable = false)
    private boolean active = true;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "rotated_at", nullable = false)
    private OffsetDateTime rotatedAt = OffsetDateTime.now();

    protected ApiClient() {
    }

    public ApiClient(String name, Role role, String keyHash) {
        this.name = name;
        this.role = role;
        this.keyHash = keyHash;
    }

    public void rotate(Role newRole, String newKeyHash) {
        this.role = newRole;
        this.keyHash = newKeyHash;
        this.active = true;
        this.rotatedAt = OffsetDateTime.now();
    }

    public String getName() {
        return name;
    }

    public Role getRole() {
        return role;
    }

    public String getKeyHash() {
        return keyHash;
    }

    public boolean isActive() {
        return active;
    }
}
