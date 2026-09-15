package org.idarciooliveira.retailordersservices.infra.config;

import org.idarciooliveira.retailordersservices.domain.repository.OrderRepository;
import org.idarciooliveira.retailordersservices.domain.usecase.CancelOrderUseCase;
import org.idarciooliveira.retailordersservices.domain.usecase.CreateOrderUseCase;
import org.idarciooliveira.retailordersservices.domain.usecase.GetOrderUseCase;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class UseCaseConfig {

    @Bean
    public CreateOrderUseCase createOrderUseCase(OrderRepository orderRepository) {
        return new CreateOrderUseCase(orderRepository);
    }

    @Bean
    public GetOrderUseCase getOrderUseCase(OrderRepository orderRepository) {
        return new GetOrderUseCase(orderRepository);
    }

    @Bean
    public CancelOrderUseCase cancelOrderUseCase(OrderRepository orderRepository) {
        return new CancelOrderUseCase(orderRepository);
    }
}
