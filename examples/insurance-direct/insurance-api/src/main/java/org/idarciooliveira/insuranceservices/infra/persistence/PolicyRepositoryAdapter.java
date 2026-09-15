package org.idarciooliveira.insuranceservices.infra.persistence;

import io.opentelemetry.instrumentation.annotations.WithSpan;
import org.idarciooliveira.insuranceservices.domain.model.Policy;
import org.idarciooliveira.insuranceservices.domain.repository.PolicyRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public class PolicyRepositoryAdapter implements PolicyRepository {

    private final PolicyJpaRepository jpaRepository;

    public PolicyRepositoryAdapter(PolicyJpaRepository jpaRepository) {
        this.jpaRepository = jpaRepository;
    }

    @Override
    public Optional<Policy> findById(UUID id) {
        return jpaRepository.findById(id).map(this::toDomain);
    }

    @Override
    public Optional<Policy> findByPolicyNumber(String policyNumber) {
        return jpaRepository.findByPolicyNumber(policyNumber).map(this::toDomain);
    }

    @WithSpan("database.update")
    @Override
    public void save(Policy policy) {
        jpaRepository.save(toEntity(policy));
    }

    private Policy toDomain(PolicyEntity entity) {
        return new Policy(
                entity.getId(),
                entity.getPolicyNumber(),
                entity.getHolderName(),
                entity.getStatus(),
                entity.getCoverageLimit(),
                entity.getCreatedAt());
    }

    private PolicyEntity toEntity(Policy policy) {
        return new PolicyEntity(
                policy.getId(),
                policy.getPolicyNumber(),
                policy.getHolderName(),
                policy.getStatus(),
                policy.getCoverageLimit(),
                policy.getCreatedAt());
    }
}
