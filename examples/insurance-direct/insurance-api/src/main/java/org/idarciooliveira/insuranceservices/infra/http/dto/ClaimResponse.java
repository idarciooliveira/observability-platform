package org.idarciooliveira.insuranceservices.infra.http.dto;

import org.idarciooliveira.insuranceservices.domain.model.Claim;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public record ClaimResponse(
        UUID id,
        UUID policyId,
        BigDecimal amount,
        String status,
        Instant createdAt) {

    public static ClaimResponse from(Claim claim) {
        return new ClaimResponse(
                claim.getId(),
                claim.getPolicyId(),
                claim.getAmount(),
                claim.getStatus().name(),
                claim.getCreatedAt());
    }
}
