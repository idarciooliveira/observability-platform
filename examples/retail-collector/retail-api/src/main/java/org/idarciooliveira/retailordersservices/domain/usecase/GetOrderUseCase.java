package org.idarciooliveira.retailordersservices.domain.usecase;

import org.idarciooliveira.retailordersservices.domain.exception.OrderNotFoundException;
import org.idarciooliveira.retailordersservices.domain.model.Order;
import org.idarciooliveira.retailordersservices.domain.repository.OrderRepository;

import java.util.UUID;

public class GetOrderUseCase {

    private final OrderRepository orderRepository;

    public GetOrderUseCase(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    public Order get(UUID id) {
        return orderRepository.findById(id)
                .orElseThrow(() -> new OrderNotFoundException(id));
    }
}
