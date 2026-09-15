package org.idarciooliveira.insuranceservices.infra.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.idarciooliveira.insuranceservices.domain.model.ClaimStatus;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "claims")
public class ClaimEntity {

    @Id
    private UUID id;

    @Column(name = "policy_id", nullable = false)
    private UUID policyId;

    @Column(name = "amount", nullable = false)
    private BigDecimal amount;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false)
    private ClaimStatus status;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected ClaimEntity() {
    }

    public ClaimEntity(UUID id, UUID policyId, BigDecimal amount, Instant createdAt, ClaimStatus status) {
        this.id = id;
        this.policyId = policyId;
        this.amount = amount;
        this.createdAt = createdAt;
        this.status = status;
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
