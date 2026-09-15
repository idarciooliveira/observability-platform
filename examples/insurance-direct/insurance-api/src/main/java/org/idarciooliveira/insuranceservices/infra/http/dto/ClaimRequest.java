package org.idarciooliveira.insuranceservices.infra.http.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;

public record ClaimRequest(
        @NotNull @DecimalMin(value = "0.01") BigDecimal amount) {
}
