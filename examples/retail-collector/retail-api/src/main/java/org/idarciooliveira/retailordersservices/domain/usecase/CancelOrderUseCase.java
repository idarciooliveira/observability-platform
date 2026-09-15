package org.idarciooliveira.retailordersservices.domain.usecase;

import org.idarciooliveira.retailordersservices.domain.exception.InvalidOrderException;
import org.idarciooliveira.retailordersservices.domain.exception.OrderAlreadyCancelledException;
import org.idarciooliveira.retailordersservices.domain.exception.OrderNotFoundException;
import org.idarciooliveira.retailordersservices.domain.model.Order;
import org.idarciooliveira.retailordersservices.domain.model.OrderStatus;
import org.idarciooliveira.retailordersservices.domain.repository.OrderRepository;

import java.util.UUID;

public class CancelOrderUseCase {

    private final OrderRepository orderRepository;

    public CancelOrderUseCase(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    public Order cancel(UUID id) {
        Order order = orderRepository.findById(id)
                .orElseThrow(() -> new OrderNotFoundException(id));
        if (order.getStatus() == OrderStatus.CANCELLED) {
            throw new OrderAlreadyCancelledException(id);
        }
        if (order.getStatus() == OrderStatus.FAILED) {
            throw new InvalidOrderException("Cannot cancel a failed order: " + id);
        }
        order.cancel();
        orderRepository.save(order);
        return order;
    }
}
