package org.idarciooliveira.riskservice;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

@Component
public class RiskMetrics {

    public static final String RISK_REJECTED = "insurance.risk.rejected";
    public static final String RISK_DURATION = "insurance.risk.duration";

    private final Counter riskRejected;
    private final Timer riskDuration;

    public RiskMetrics(MeterRegistry registry) {
        this.riskRejected = Counter.builder(RISK_REJECTED)
                .description("Number of claims rejected by the risk assessment")
                .register(registry);
        this.riskDuration = Timer.builder(RISK_DURATION)
                .description("Risk-assessment latency")
                .register(registry);
    }

    public void countRiskRejected() {
        riskRejected.increment();
    }

    public void recordRiskDuration(long nanos) {
        riskDuration.record(nanos, TimeUnit.NANOSECONDS);
    }
}
