package org.idarciooliveira.insuranceservices.infra.metrics;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

/**
 * Business metrics for the insurance domain.
 * Infra-layer component; the domain stays metrics-free.
 * Tag values are a fixed low-cardinality set — never policy numbers.
 */
@Component
public class ClaimMetrics {

    public static final String CLAIMS_TOTAL = "insurance.claims.total";
    public static final String CLAIM_DURATION = "insurance.claim.duration";

    public static final String STATUS_SUCCESS = "success";
    public static final String STATUS_POLICY_NOT_FOUND = "policy_not_found";
    public static final String STATUS_POLICY_INACTIVE = "policy_inactive";
    public static final String STATUS_COVERAGE_EXCEEDED = "coverage_exceeded";
    public static final String STATUS_RISK_REJECTED = "risk_rejected";
    public static final String STATUS_INVALID = "invalid";
    public static final String STATUS_ERROR = "error";

    private final MeterRegistry registry;
    private final Timer claimDuration;

    public ClaimMetrics(MeterRegistry registry) {
        this.registry = registry;
        this.claimDuration = Timer.builder(CLAIM_DURATION)
                .description("End-to-end claim processing latency")
                .register(registry);
    }

    public void countClaim(String status) {
        Counter.builder(CLAIMS_TOTAL)
                .description("Total number of claim attempts")
                .tag("status", status)
                .register(registry)
                .increment();
    }

    public void recordClaimDuration(long nanos) {
        claimDuration.record(nanos, TimeUnit.NANOSECONDS);
    }
}
