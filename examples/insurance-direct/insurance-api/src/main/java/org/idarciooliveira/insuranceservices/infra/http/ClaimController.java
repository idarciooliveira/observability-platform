package org.idarciooliveira.insuranceservices.infra.http;

import jakarta.validation.Valid;
import org.idarciooliveira.insuranceservices.domain.model.Claim;
import org.idarciooliveira.insuranceservices.infra.application.ClaimApplicationService;
import org.idarciooliveira.insuranceservices.infra.http.dto.ClaimRequest;
import org.idarciooliveira.insuranceservices.infra.http.dto.ClaimResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequestMapping("/policies")
public class ClaimController {

    private final ClaimApplicationService claimApplicationService;

    public ClaimController(ClaimApplicationService claimApplicationService) {
        this.claimApplicationService = claimApplicationService;
    }

    @PostMapping("/{policyId}/claims")
    public ResponseEntity<ClaimResponse> createClaim(@PathVariable UUID policyId,
                                                     @Valid @RequestBody ClaimRequest request) {
        Claim claim = claimApplicationService.processClaim(policyId, request.amount());
        return ResponseEntity.status(HttpStatus.CREATED).body(ClaimResponse.from(claim));
    }
}
