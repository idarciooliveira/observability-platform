package org.idarciooliveira.insuranceservices.domain.model;

public enum ClaimStatus {
    APPROVED,
    REJECTED_POLICY_NOT_FOUND,
    REJECTED_POLICY_INACTIVE,
    REJECTED_COVERAGE_EXCEEDED,
    REJECTED_RISK
}
