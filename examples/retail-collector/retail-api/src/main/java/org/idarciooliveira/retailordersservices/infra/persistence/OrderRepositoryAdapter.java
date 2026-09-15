package org.idarciooliveira.retailordersservices.infra.persistence;

import org.idarciooliveira.retailordersservices.domain.model.Order;
import org.idarciooliveira.retailordersservices.domain.repository.OrderRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public class OrderRepositoryAdapter implements OrderRepository {

    private final OrderJpaRepository jpaRepository;

    public OrderRepositoryAdapter(OrderJpaRepository jpaRepository) {
        this.jpaRepository = jpaRepository;
    }

    @Override
    public Order save(Order order) {
        OrderEntity entity = new OrderEntity(
                order.getId(), order.getProductId(), order.getQuantity(),
                order.getTotal(), order.getCreatedAt(), order.getStatus());
        OrderEntity saved = jpaRepository.save(entity);
        return new Order(saved.getId(), saved.getProductId(), saved.getQuantity(),
                saved.getTotal(), saved.getCreatedAt(), saved.getStatus());
    }

    @Override
    public Optional<Order> findById(UUID id) {
        return jpaRepository.findById(id)
                .map(e -> new Order(e.getId(), e.getProductId(), e.getQuantity(),
                        e.getTotal(), e.getCreatedAt(), e.getStatus()));
    }
}
