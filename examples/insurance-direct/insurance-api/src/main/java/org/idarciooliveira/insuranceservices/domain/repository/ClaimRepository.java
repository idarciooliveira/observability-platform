package org.idarciooliveira.insuranceservices.domain.repository;

import org.idarciooliveira.insuranceservices.domain.model.Claim;

import java.util.Optional;
import java.util.UUID;

public interface ClaimRepository {

    void save(Claim claim);

    Optional<Claim> findById(UUID id);
}
