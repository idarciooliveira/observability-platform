package org.idarciooliveira.insuranceservices.domain.usecase;

import java.math.BigDecimal;
import java.util.UUID;

public interface RiskEvaluation {

    boolean isApproved(UUID policyId, BigDecimal amount, BigDecimal coverageLimit);
}
