package org.idarciooliveira.riskservice;

import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.util.UUID;

public record RiskCheckRequest(
    @NotNull UUID policyId,
    @NotNull BigDecimal claimAmount,
    @NotNull BigDecimal coverageLimit
) {}
