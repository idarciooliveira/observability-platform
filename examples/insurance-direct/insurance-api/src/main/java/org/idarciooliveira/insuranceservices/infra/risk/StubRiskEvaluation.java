package org.idarciooliveira.insuranceservices.infra.risk;

import io.opentelemetry.instrumentation.annotations.WithSpan;
import org.idarciooliveira.insuranceservices.domain.usecase.RiskEvaluation;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.UUID;

/**
 * In-process fallback for the "test" profile: mirrors RiskCheckService thresholds
 * so tests run without a live risk-service.
 */
@Component
@Profile("test")
public class StubRiskEvaluation implements RiskEvaluation {

    private static final Logger log = LoggerFactory.getLogger(StubRiskEvaluation.class);
    private static final BigDecimal HIGH_VALUE_THRESHOLD = new BigDecimal("50000");
    private static final BigDecimal COVERAGE_EXHAUSTION_RATIO = new BigDecimal("0.80");

    @WithSpan("risk.check")
    @Override
    public boolean isApproved(UUID policyId, BigDecimal amount, BigDecimal coverageLimit) {
        if (amount.compareTo(HIGH_VALUE_THRESHOLD) > 0) {
            log.warn("risk.check status=rejected policy={} amount={} reason=high_value", policyId, amount);
            return false;
        }
        if (amount.compareTo(coverageLimit.multiply(COVERAGE_EXHAUSTION_RATIO)) > 0) {
            log.warn("risk.check status=rejected policy={} amount={} reason=coverage_exhaustion", policyId, amount);
            return false;
        }
        log.info("risk.check status=approved policy={} amount={}", policyId, amount);
        return true;
    }
}
