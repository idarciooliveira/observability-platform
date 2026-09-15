package org.idarciooliveira.retailordersservices.domain.model;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public class Order {

    private final UUID id;
    private final String productId;
    private final int quantity;
    private final BigDecimal total;
    private final Instant createdAt;
    private OrderStatus status;

    public Order(UUID id, String productId, int quantity,
                 BigDecimal total, Instant createdAt, OrderStatus status) {
        this.id = id;
        this.productId = productId;
        this.quantity = quantity;
        this.total = total;
        this.createdAt = createdAt;
        this.status = status;
    }

    public static Order created(String productId, int quantity, BigDecimal total) {
        return new Order(UUID.randomUUID(), productId, quantity,
                total, Instant.now(), OrderStatus.CREATED);
    }

    public void cancel() {
        this.status = OrderStatus.CANCELLED;
    }

    public void fail() {
        this.status = OrderStatus.FAILED;
    }

    public UUID getId() {
        return id;
    }

    public String getProductId() {
        return productId;
    }

    public int getQuantity() {
        return quantity;
    }

    public BigDecimal getTotal() {
        return total;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public OrderStatus getStatus() {
        return status;
    }
}
