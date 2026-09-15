package org.idarciooliveira.insuranceservices.domain.exception;

import java.math.BigDecimal;
import java.util.UUID;

public class CoverageExceededException extends RuntimeException {

    public CoverageExceededException(UUID policyId, BigDecimal amount, BigDecimal coverageLimit) {
        super("Claim amount " + amount + " exceeds coverage limit " + coverageLimit + " for policy: " + policyId);
    }
}
