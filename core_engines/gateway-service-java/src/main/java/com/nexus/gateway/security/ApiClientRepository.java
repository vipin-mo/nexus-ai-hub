package com.nexus.gateway.security;

import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ApiClientRepository extends JpaRepository<ApiClient, Long> {

    Optional<ApiClient> findByKeyHashAndActiveTrue(String keyHash);

    Optional<ApiClient> findByName(String name);
}
