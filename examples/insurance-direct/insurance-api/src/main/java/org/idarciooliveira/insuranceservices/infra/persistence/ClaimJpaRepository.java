package org.idarciooliveira.insuranceservices.infra.persistence;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.UUID;

public interface ClaimJpaRepository extends JpaRepository<ClaimEntity, UUID> {
}
