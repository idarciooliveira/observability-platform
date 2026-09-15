package org.idarciooliveira.retailordersservices.domain.usecase;

import org.idarciooliveira.retailordersservices.domain.exception.InvalidOrderException;
import org.idarciooliveira.retailordersservices.domain.model.Order;
import org.idarciooliveira.retailordersservices.domain.repository.OrderRepository;

import java.math.BigDecimal;
import java.util.Map;

public class CreateOrderUseCase {

    // Synthetic catalog only — prices mirrored in data.sql, no PII.
    private static final Map<String, BigDecimal> CATALOG = Map.of(
            "PROD-001", new BigDecimal("29.99"),
            "PROD-002", new BigDecimal("49.99"),
            "PROD-003", new BigDecimal("99.99"));

    private final OrderRepository orderRepository;

    public CreateOrderUseCase(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    public Order create(String productId, int quantity) {
        BigDecimal unitPrice = CATALOG.get(productId);
        if (unitPrice == null) {
            throw new InvalidOrderException("Unknown product: " + productId);
        }
        if (quantity <= 0 || quantity > 100) {
            throw new InvalidOrderException("Quantity must be between 1 and 100");
        }
        BigDecimal total = unitPrice.multiply(BigDecimal.valueOf(quantity));
        Order order = Order.created(productId, quantity, total);
        orderRepository.save(order);
        return order;
    }

    public static boolean isKnownProduct(String productId) {
        return CATALOG.containsKey(productId);
    }
}
