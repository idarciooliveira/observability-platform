package org.idarciooliveira.retailordersservices.domain.exception;

import java.util.UUID;

public class OrderAlreadyCancelledException extends RuntimeException {
    public OrderAlreadyCancelledException(UUID id) {
        super("Order already cancelled: " + id);
    }
}
