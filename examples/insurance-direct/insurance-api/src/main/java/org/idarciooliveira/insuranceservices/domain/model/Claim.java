package org.idarciooliveira.insuranceservices.domain.model;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public class Claim {

    private final UUID id;
    private final UUID policyId;
    private final BigDecimal amount;
    private final Instant createdAt;
    private ClaimStatus status;

    public Claim(UUID id, UUID policyId, BigDecimal amount, Instant createdAt, ClaimStatus status) {
        this.id = id;
        this.policyId = policyId;
        this.amount = amount;
        this.createdAt = createdAt;
        this.status = status;
    }

    public static Claim requested(UUID policyId, BigDecimal amount) {
        return new Claim(UUID.randomUUID(), policyId, amount, Instant.now(), ClaimStatus.APPROVED);
    }

    public void reject(ClaimStatus reason) {
        this.status = reason;
    }

    public UUID getId() {
        return id;
    }

    public UUID getPolicyId() {
        return policyId;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public ClaimStatus getStatus() {
        return status;
    }
}
