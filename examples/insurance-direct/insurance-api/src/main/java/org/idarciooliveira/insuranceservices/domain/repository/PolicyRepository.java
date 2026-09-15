package org.idarciooliveira.insuranceservices.domain.repository;

import org.idarciooliveira.insuranceservices.domain.model.Policy;

import java.util.Optional;
import java.util.UUID;

public interface PolicyRepository {

    Optional<Policy> findById(UUID id);

    Optional<Policy> findByPolicyNumber(String policyNumber);

    void save(Policy policy);
}
