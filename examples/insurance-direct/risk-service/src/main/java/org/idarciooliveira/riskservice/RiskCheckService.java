package org.idarciooliveira.riskservice;

import io.opentelemetry.instrumentation.annotations.WithSpan;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;

@Service
public class RiskCheckService {

    private static final Logger log = LoggerFactory.getLogger(RiskCheckService.class);
    private static final BigDecimal HIGH_VALUE_THRESHOLD = new BigDecimal("50000");
    private static final BigDecimal COVERAGE_EXHAUSTION_RATIO = new BigDecimal("0.80");

    private final RiskMetrics metrics;
    private final long chaosLatencyMs;
    private final double chaosRejectRate;

    public RiskCheckService(
            RiskMetrics metrics,
            // Phase 8 fault injection (env-driven, no rebuild to toggle).
            // CHAOS_LATENCY_MS > 2000 also trips the API's 2s risk-evaluation
            // timeout, exercising the timeout error path for free.
            @Value("${CHAOS_LATENCY_MS:0}") long chaosLatencyMs,
            @Value("${CHAOS_REJECT_RATE:0}") double chaosRejectRate) {
        this.metrics = metrics;
        this.chaosLatencyMs = chaosLatencyMs;
        this.chaosRejectRate = chaosRejectRate;
        if (chaosLatencyMs > 0 || chaosRejectRate > 0) {
            log.warn("chaos enabled latency_ms={} reject_rate={}", chaosLatencyMs, chaosRejectRate);
        }
    }

    @WithSpan("risk.assessment")
    public RiskCheckResponse checkRisk(UUID policyId, BigDecimal claimAmount, BigDecimal coverageLimit) {
        long start = System.nanoTime();
        try {
            if (chaosLatencyMs > 0) {
                sleepUninterruptibly(chaosLatencyMs);
            }

            // Chaos forced rejection (overrides an approval, never an existing rejection).
            if (chaosRejectRate > 0 && ThreadLocalRandom.current().nextDouble() < chaosRejectRate) {
                log.warn("risk.assessment status=rejected policy={} amount={} reason=chaos_forced",
                         policyId, claimAmount);
                metrics.countRiskRejected();
                return new RiskCheckResponse(false, "chaos_forced");
            }

            // Check for high-value claims
            if (claimAmount.compareTo(HIGH_VALUE_THRESHOLD) > 0) {
                log.warn("risk.assessment status=rejected policy={} amount={} reason=high_value",
                         policyId, claimAmount);
                metrics.countRiskRejected();
                return new RiskCheckResponse(false, "high_value");
            }

            // Check for coverage exhaustion risk (claim > 80% of coverage limit)
            BigDecimal exhaustionThreshold = coverageLimit.multiply(COVERAGE_EXHAUSTION_RATIO);
            if (claimAmount.compareTo(exhaustionThreshold) > 0) {
                log.warn("risk.assessment status=rejected policy={} amount={} coverageLimit={} reason=coverage_exhaustion",
                         policyId, claimAmount, coverageLimit);
                metrics.countRiskRejected();
                return new RiskCheckResponse(false, "coverage_exhaustion");
            }

            // Approve claim
            log.info("risk.assessment status=approved policy={} amount={} coverageLimit={}",
                     policyId, claimAmount, coverageLimit);
            return new RiskCheckResponse(true, "approved");
        } finally {
            metrics.recordRiskDuration(System.nanoTime() - start);
        }
    }

    private void sleepUninterruptibly(long millis) {
        long deadline = System.currentTimeMillis() + millis;
        long remaining;
        while ((remaining = deadline - System.currentTimeMillis()) > 0) {
            try {
                Thread.sleep(remaining);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }
}
