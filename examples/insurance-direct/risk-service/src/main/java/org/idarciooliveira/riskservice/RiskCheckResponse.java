package org.idarciooliveira.riskservice;

public record RiskCheckResponse(boolean approved, String reason) {}
