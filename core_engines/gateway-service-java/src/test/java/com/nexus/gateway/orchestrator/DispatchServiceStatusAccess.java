package com.nexus.gateway.orchestrator;

import org.springframework.http.HttpStatus;

/** Test-only bridge to the package-private status mapping. */
public final class DispatchServiceStatusAccess {

    private DispatchServiceStatusAccess() {
    }

    public static HttpStatus map(String status) {
        return DispatchService.httpStatusFor(status);
    }
}
