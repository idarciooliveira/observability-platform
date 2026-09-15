package org.idarciooliveira.insuranceservices.domain.exception;

import java.util.UUID;

public class RiskRejectedException extends RuntimeException {

    public RiskRejectedException(UUID policyId) {
        super("Risk check rejected claim for policy: " + policyId);
    }
}
