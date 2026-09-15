package org.idarciooliveira.retailordersservices.infra.http.dto;

import org.idarciooliveira.retailordersservices.domain.model.Order;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public record OrderResponse(
        UUID id,
        String productId,
        int quantity,
        BigDecimal total,
        String status,
        Instant createdAt) {

    public static OrderResponse from(Order order) {
        return new OrderResponse(
                order.getId(),
                order.getProductId(),
                order.getQuantity(),
                order.getTotal(),
                order.getStatus().name(),
                order.getCreatedAt());
    }
}
