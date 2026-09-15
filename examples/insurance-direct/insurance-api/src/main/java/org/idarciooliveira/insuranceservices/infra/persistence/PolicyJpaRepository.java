package org.idarciooliveira.insuranceservices.infra.persistence;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

public interface PolicyJpaRepository extends JpaRepository<PolicyEntity, UUID> {

    Optional<PolicyEntity> findByPolicyNumber(String policyNumber);
}
