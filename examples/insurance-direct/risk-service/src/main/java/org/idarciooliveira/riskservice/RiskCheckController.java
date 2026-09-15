package org.idarciooliveira.riskservice;

import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/risk-check")
public class RiskCheckController {

    private final RiskCheckService riskCheckService;

    public RiskCheckController(RiskCheckService riskCheckService) {
        this.riskCheckService = riskCheckService;
    }

    @PostMapping
    public ResponseEntity<RiskCheckResponse> checkRisk(@Valid @RequestBody RiskCheckRequest request) {
        RiskCheckResponse response = riskCheckService.checkRisk(
            request.policyId(),
            request.claimAmount(),
            request.coverageLimit()
        );
        return ResponseEntity.ok(response);
    }
}
