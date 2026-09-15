package org.idarciooliveira.insuranceservices.domain.usecase;

import org.idarciooliveira.insuranceservices.domain.exception.CoverageExceededException;
import org.idarciooliveira.insuranceservices.domain.exception.PolicyInactiveException;
import org.idarciooliveira.insuranceservices.domain.exception.PolicyNotFoundException;
import org.idarciooliveira.insuranceservices.domain.exception.RiskRejectedException;
import org.idarciooliveira.insuranceservices.domain.model.Claim;
import org.idarciooliveira.insuranceservices.domain.model.Policy;
import org.idarciooliveira.insuranceservices.domain.repository.ClaimRepository;
import org.idarciooliveira.insuranceservices.domain.repository.PolicyRepository;

import java.math.BigDecimal;
import java.util.UUID;

public class ProcessClaimUseCase {

    private final PolicyRepository policyRepository;
    private final ClaimRepository claimRepository;
    private final RiskEvaluation riskEvaluation;

    public ProcessClaimUseCase(PolicyRepository policyRepository,
                               ClaimRepository claimRepository,
                               RiskEvaluation riskEvaluation) {
        this.policyRepository = policyRepository;
        this.claimRepository = claimRepository;
        this.riskEvaluation = riskEvaluation;
    }

    public Claim process(UUID policyId, BigDecimal amount) {
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("Claim amount must be greater than zero");
        }

        Policy policy = policyRepository.findById(policyId)
                .orElseThrow(() -> new PolicyNotFoundException(policyId));

        if (!policy.isActive()) {
            throw new PolicyInactiveException(policyId);
        }

        if (!policy.canCover(amount)) {
            throw new CoverageExceededException(policyId, amount, policy.getCoverageLimit());
        }

        if (!riskEvaluation.isApproved(policyId, amount, policy.getCoverageLimit())) {
            throw new RiskRejectedException(policyId);
        }

        Claim claim = Claim.requested(policyId, amount);
        claimRepository.save(claim);
        return claim;
    }
}
