package org.idarciooliveira.insuranceservices.infra.config;

import org.idarciooliveira.insuranceservices.domain.repository.ClaimRepository;
import org.idarciooliveira.insuranceservices.domain.repository.PolicyRepository;
import org.idarciooliveira.insuranceservices.domain.usecase.ProcessClaimUseCase;
import org.idarciooliveira.insuranceservices.domain.usecase.RiskEvaluation;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class UseCaseConfig {

    @Bean
    public ProcessClaimUseCase processClaimUseCase(PolicyRepository policyRepository,
                                                   ClaimRepository claimRepository,
                                                   RiskEvaluation riskEvaluation) {
        return new ProcessClaimUseCase(policyRepository, claimRepository, riskEvaluation);
    }
}
