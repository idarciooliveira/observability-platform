package org.idarciooliveira.retailordersservices.infra.http;

import jakarta.validation.Valid;
import org.idarciooliveira.retailordersservices.domain.model.Order;
import org.idarciooliveira.retailordersservices.infra.application.OrderApplicationService;
import org.idarciooliveira.retailordersservices.infra.http.dto.OrderRequest;
import org.idarciooliveira.retailordersservices.infra.http.dto.OrderResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequestMapping("/orders")
public class OrderController {

    private final OrderApplicationService orderApplicationService;

    public OrderController(OrderApplicationService orderApplicationService) {
        this.orderApplicationService = orderApplicationService;
    }

    @PostMapping
    public ResponseEntity<OrderResponse> create(@Valid @RequestBody OrderRequest request) {
        Order order = orderApplicationService.createOrder(request.productId(), request.quantity());
        return ResponseEntity.status(HttpStatus.CREATED).body(OrderResponse.from(order));
    }

    @GetMapping("/{id}")
    public ResponseEntity<OrderResponse> get(@PathVariable UUID id) {
        Order order = orderApplicationService.getOrder(id);
        return ResponseEntity.ok(OrderResponse.from(order));
    }

    @PostMapping("/{id}/cancel")
    public ResponseEntity<OrderResponse> cancel(@PathVariable UUID id) {
        Order order = orderApplicationService.cancelOrder(id);
        return ResponseEntity.ok(OrderResponse.from(order));
    }
}
