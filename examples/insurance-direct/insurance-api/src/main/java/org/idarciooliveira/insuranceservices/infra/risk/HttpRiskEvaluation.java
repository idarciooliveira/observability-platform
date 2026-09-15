package org.idarciooliveira.insuranceservices.infra.risk;

import io.opentelemetry.instrumentation.annotations.WithSpan;
import org.idarciooliveira.insuranceservices.domain.usecase.RiskEvaluation;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.math.BigDecimal;
import java.util.UUID;

/**
 * HTTP client for the external Risk Service (Phase 5 distributed tracing).
 * Wraps the business span "risk.check"; HTTP call auto-instrumented by the agent.
 * On error: wraps as RuntimeException for ClaimApplicationService's catch-all.
 */
@Component
@Profile("!test")
public class HttpRiskEvaluation implements RiskEvaluation {

    private static final Logger log = LoggerFactory.getLogger(HttpRiskEvaluation.class);

    private final RestClient restClient;
    private final String riskServiceUrl;

    public HttpRiskEvaluation(@Value("${risk.service.url}") String riskServiceUrl) {
        this.riskServiceUrl = riskServiceUrl;
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(2000);
        factory.setReadTimeout(2000);
        this.restClient = RestClient.builder()
                .requestFactory(factory)
                .build();
    }

    @WithSpan("risk.check")
    @Override
    public boolean isApproved(UUID policyId, BigDecimal amount, BigDecimal coverageLimit) {
        try {
            RiskCheckRequest request = new RiskCheckRequest(policyId, amount, coverageLimit);
            RiskCheckResponse response = restClient.post()
                    .uri(riskServiceUrl + "/risk-check")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(request)
                    .retrieve()
                    .body(RiskCheckResponse.class);

            if (response == null) {
                throw new RuntimeException("Risk service returned null response");
            }
            return response.approved();
        } catch (Exception e) {
            log.error("Risk check failed for policy {}: {}", policyId, e.getMessage());
            throw new RuntimeException("Risk check service unavailable", e);
        }
    }

    private record RiskCheckRequest(UUID policyId, BigDecimal claimAmount, BigDecimal coverageLimit) {}

    private record RiskCheckResponse(boolean approved, String reason) {}
}
