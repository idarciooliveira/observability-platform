package org.idarciooliveira.retailordersservices.infra.metrics;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

/**
 * Business metrics for the retail domain (Ch.2 PRD).
 * Infra-layer component; the domain stays metrics-free.
 * Tag values are a fixed low-cardinality set — never customer PII.
 */
@Component
public class OrderMetrics {

    public static final String ORDERS_CREATED = "retail.orders.created";
    public static final String ORDERS_CANCELLED = "retail.orders.cancelled";
    public static final String ORDERS_FAILED = "retail.orders.failed";
    public static final String ORDER_VALUE = "retail.order.value";
    public static final String PROCESSING_DURATION = "retail.order.processing.duration";

    public static final String STATUS_SUCCESS = "success";
    public static final String STATUS_INVALID = "invalid";
    public static final String STATUS_NOT_FOUND = "not_found";
    public static final String STATUS_ALREADY_CANCELLED = "already_cancelled";
    public static final String STATUS_ERROR = "error";

    private final Counter created;
    private final Counter cancelled;
    private final Counter failed;
    private final DistributionSummary orderValue;
    private final Timer processingDuration;

    public OrderMetrics(MeterRegistry registry) {
        this.created = Counter.builder(ORDERS_CREATED)
                .description("Number of retail orders created")
                .register(registry);
        this.cancelled = Counter.builder(ORDERS_CANCELLED)
                .description("Number of retail orders cancelled")
                .register(registry);
        this.failed = Counter.builder(ORDERS_FAILED)
                .description("Number of retail order operations failed")
                .register(registry);
        this.orderValue = DistributionSummary.builder(ORDER_VALUE)
                .description("Retail order total value")
                .baseUnit("currency")
                .register(registry);
        this.processingDuration = Timer.builder(PROCESSING_DURATION)
                .description("Retail order processing latency")
                .register(registry);
    }

    public void countCreated() {
        created.increment();
    }

    public void countCancelled() {
        cancelled.increment();
    }

    public void countFailed(String status) {
        failed.increment();
    }

    public void recordOrderValue(double total) {
        orderValue.record(total);
    }

    public void recordProcessingDuration(long nanos) {
        processingDuration.record(nanos, TimeUnit.NANOSECONDS);
    }
}
