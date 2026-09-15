package org.idarciooliveira.retailordersservices.infra.application;

import io.opentelemetry.instrumentation.annotations.WithSpan;
import org.idarciooliveira.retailordersservices.domain.exception.InvalidOrderException;
import org.idarciooliveira.retailordersservices.domain.exception.OrderAlreadyCancelledException;
import org.idarciooliveira.retailordersservices.domain.exception.OrderNotFoundException;
import org.idarciooliveira.retailordersservices.domain.model.Order;
import org.idarciooliveira.retailordersservices.domain.usecase.CancelOrderUseCase;
import org.idarciooliveira.retailordersservices.domain.usecase.CreateOrderUseCase;
import org.idarciooliveira.retailordersservices.domain.usecase.GetOrderUseCase;
import org.idarciooliveira.retailordersservices.infra.metrics.OrderMetrics;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;

/**
 * Application-layer transaction boundary.
 * Keeps the domain use cases pure POJOs; Spring concerns (@Transactional)
 * live here in infra. Chaos flags enable latency/error investigation demos.
 */
@Service
public class OrderApplicationService {

    private static final Logger log = LoggerFactory.getLogger(OrderApplicationService.class);

    private final CreateOrderUseCase createOrderUseCase;
    private final GetOrderUseCase getOrderUseCase;
    private final CancelOrderUseCase cancelOrderUseCase;
    private final OrderMetrics metrics;

    private final long chaosLatencyMs;
    private final double chaosFailRate;

    public OrderApplicationService(CreateOrderUseCase createOrderUseCase,
                                   GetOrderUseCase getOrderUseCase,
                                   CancelOrderUseCase cancelOrderUseCase,
                                   OrderMetrics metrics,
                                   @Value("${chaos.latency-ms:0}") long chaosLatencyMs,
                                   @Value("${chaos.fail-rate:0}") double chaosFailRate) {
        this.createOrderUseCase = createOrderUseCase;
        this.getOrderUseCase = getOrderUseCase;
        this.cancelOrderUseCase = cancelOrderUseCase;
        this.metrics = metrics;
        this.chaosLatencyMs = chaosLatencyMs;
        this.chaosFailRate = chaosFailRate;
    }

    @WithSpan("order.process")
    @Transactional
    public Order createOrder(String productId, int quantity) {
        long start = System.nanoTime();
        try {
            applyChaos("create");
            Order order = createOrderUseCase.create(productId, quantity);
            metrics.countCreated();
            metrics.recordOrderValue(order.getTotal().doubleValue());
            metrics.recordProcessingDuration(System.nanoTime() - start);
            log.info("order.process status=success orderId={} product={} qty={} total={}",
                    order.getId(), productId, quantity, order.getTotal());
            return order;
        } catch (InvalidOrderException e) {
            metrics.countFailed(OrderMetrics.STATUS_INVALID);
            metrics.recordProcessingDuration(System.nanoTime() - start);
            log.warn("order.process status=invalid product={} qty={} reason={}",
                    productId, quantity, e.getMessage());
            throw e;
        } catch (RuntimeException e) {
            metrics.countFailed(OrderMetrics.STATUS_ERROR);
            metrics.recordProcessingDuration(System.nanoTime() - start);
            log.error("order.process status=error product={} qty={}", productId, quantity, e);
            throw e;
        }
    }

    @WithSpan("order.get")
    @Transactional(readOnly = true)
    public Order getOrder(UUID id) {
        try {
            return getOrderUseCase.get(id);
        } catch (OrderNotFoundException e) {
            log.warn("order.get status=not_found orderId={}", id);
            throw e;
        }
    }

    @WithSpan("order.cancel")
    @Transactional
    public Order cancelOrder(UUID id) {
        long start = System.nanoTime();
        try {
            applyChaos("cancel");
            Order order = cancelOrderUseCase.cancel(id);
            metrics.countCancelled();
            metrics.recordProcessingDuration(System.nanoTime() - start);
            log.info("order.cancel status=success orderId={}", order.getId());
            return order;
        } catch (OrderNotFoundException e) {
            metrics.countFailed(OrderMetrics.STATUS_NOT_FOUND);
            log.warn("order.cancel status=not_found orderId={}", id);
            throw e;
        } catch (OrderAlreadyCancelledException e) {
            metrics.countFailed(OrderMetrics.STATUS_ALREADY_CANCELLED);
            log.warn("order.cancel status=already_cancelled orderId={}", id);
            throw e;
        } catch (InvalidOrderException e) {
            metrics.countFailed(OrderMetrics.STATUS_INVALID);
            log.warn("order.cancel status=invalid orderId={} reason={}", id, e.getMessage());
            throw e;
        } catch (RuntimeException e) {
            metrics.countFailed(OrderMetrics.STATUS_ERROR);
            log.error("order.cancel status=error orderId={}", id, e);
            throw e;
        }
    }

    private void applyChaos(String operation) {
        if (chaosLatencyMs > 0) {
            try {
                Thread.sleep(chaosLatencyMs);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        if (chaosFailRate > 0 && ThreadLocalRandom.current().nextDouble() < chaosFailRate) {
            throw new RuntimeException("simulated processing failure (" + operation + ")");
        }
    }
}
