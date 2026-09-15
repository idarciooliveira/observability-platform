package org.idarciooliveira.insuranceservices.infra.persistence;

import io.opentelemetry.instrumentation.annotations.WithSpan;
import org.idarciooliveira.insuranceservices.domain.model.Claim;
import org.idarciooliveira.insuranceservices.domain.repository.ClaimRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public class ClaimRepositoryAdapter implements ClaimRepository {

    private final ClaimJpaRepository jpaRepository;

    public ClaimRepositoryAdapter(ClaimJpaRepository jpaRepository) {
        this.jpaRepository = jpaRepository;
    }

    @WithSpan("database.update")
    @Override
    public void save(Claim claim) {
        ClaimEntity entity = new ClaimEntity(
                claim.getId(),
                claim.getPolicyId(),
                claim.getAmount(),
                claim.getCreatedAt(),
                claim.getStatus());
        jpaRepository.save(entity);
    }

    @Override
    public Optional<Claim> findById(UUID id) {
        return jpaRepository.findById(id)
                .map(entity -> new Claim(
                        entity.getId(),
                        entity.getPolicyId(),
                        entity.getAmount(),
                        entity.getCreatedAt(),
                        entity.getStatus()));
    }
}
