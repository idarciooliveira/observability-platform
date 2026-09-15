package org.idarciooliveira.insuranceservices.domain.exception;

import java.util.UUID;

public class PolicyNotFoundException extends RuntimeException {

    public PolicyNotFoundException(UUID policyId) {
        super("Policy not found: " + policyId);
    }
}
