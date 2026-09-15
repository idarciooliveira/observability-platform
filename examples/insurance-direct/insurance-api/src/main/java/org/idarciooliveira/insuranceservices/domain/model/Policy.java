package org.idarciooliveira.insuranceservices.domain.model;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public class Policy {

    private final UUID id;
    private final String policyNumber;
    private final String holderName;
    private final PolicyStatus status;
    private final BigDecimal coverageLimit;
    private final Instant createdAt;

    public Policy(UUID id, String policyNumber, String holderName,
                  PolicyStatus status, BigDecimal coverageLimit, Instant createdAt) {
        this.id = id;
        this.policyNumber = policyNumber;
        this.holderName = holderName;
        this.status = status;
        this.coverageLimit = coverageLimit;
        this.createdAt = createdAt;
    }

    public boolean isActive() {
        return this.status == PolicyStatus.ACTIVE;
    }

    public boolean canCover(BigDecimal amount) {
        return this.coverageLimit.compareTo(amount) >= 0;
    }

    public UUID getId() {
        return id;
    }

    public String getPolicyNumber() {
        return policyNumber;
    }

    public String getHolderName() {
        return holderName;
    }

    public PolicyStatus getStatus() {
        return status;
    }

    public BigDecimal getCoverageLimit() {
        return coverageLimit;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
