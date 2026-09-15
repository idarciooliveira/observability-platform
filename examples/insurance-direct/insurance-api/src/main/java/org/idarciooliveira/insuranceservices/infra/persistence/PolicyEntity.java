package org.idarciooliveira.insuranceservices.infra.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.idarciooliveira.insuranceservices.domain.model.PolicyStatus;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "policies")
public class PolicyEntity {

    @Id
    private UUID id;

    @Column(name = "policy_number", nullable = false, unique = true)
    private String policyNumber;

    @Column(name = "holder_name", nullable = false)
    private String holderName;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false)
    private PolicyStatus status;

    @Column(name = "coverage_limit", nullable = false)
    private BigDecimal coverageLimit;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected PolicyEntity() {
    }

    public PolicyEntity(UUID id, String policyNumber, String holderName,
                        PolicyStatus status, BigDecimal coverageLimit, Instant createdAt) {
        this.id = id;
        this.policyNumber = policyNumber;
        this.holderName = holderName;
        this.status = status;
        this.coverageLimit = coverageLimit;
        this.createdAt = createdAt;
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
