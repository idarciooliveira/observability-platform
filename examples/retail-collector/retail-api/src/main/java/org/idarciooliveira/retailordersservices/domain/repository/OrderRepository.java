package org.idarciooliveira.retailordersservices.domain.repository;

import org.idarciooliveira.retailordersservices.domain.model.Order;

import java.util.Optional;
import java.util.UUID;

public interface OrderRepository {
    Order save(Order order);
    Optional<Order> findById(UUID id);
}
