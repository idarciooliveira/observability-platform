package org.idarciooliveira.insuranceservices.infra.application;

import io.opentelemetry.instrumentation.annotations.WithSpan;
import org.idarciooliveira.insuranceservices.domain.exception.CoverageExceededException;
import org.idarciooliveira.insuranceservices.domain.exception.PolicyInactiveException;
import org.idarciooliveira.insuranceservices.domain.exception.PolicyNotFoundException;
import org.idarciooliveira.insuranceservices.domain.exception.RiskRejectedException;
import org.idarciooliveira.insuranceservices.domain.model.Claim;
import org.idarciooliveira.insuranceservices.domain.usecase.ProcessClaimUseCase;
import org.idarciooliveira.insuranceservices.infra.metrics.ClaimMetrics;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.UUID;

/**
 * Application-layer transaction boundary.
 * Keeps the domain use case a pure POJO; Spring concerns (@Transactional)
 * live here in infra.
 */
@Service
public class ClaimApplicationService {

    private static final Logger log = LoggerFactory.getLogger(ClaimApplicationService.class);

    private final ProcessClaimUseCase processClaimUseCase;
    private final ClaimMetrics metrics;

    public ClaimApplicationService(ProcessClaimUseCase processClaimUseCase, ClaimMetrics metrics) {
        this.processClaimUseCase = processClaimUseCase;
        this.metrics = metrics;
    }

    @WithSpan("claim.process")
    @Transactional
    public Claim processClaim(UUID policyId, BigDecimal amount) {
        long start = System.nanoTime();
        try {
            Claim claim = processClaimUseCase.process(policyId, amount);
            metrics.countClaim(ClaimMetrics.STATUS_SUCCESS);
            metrics.recordClaimDuration(System.nanoTime() - start);
            log.info("claim.process status=success policy={} amount={}", policyId, amount);
            return claim;
        } catch (RiskRejectedException e) {
            metrics.countClaim(ClaimMetrics.STATUS_RISK_REJECTED);
            metrics.recordClaimDuration(System.nanoTime() - start);
            log.warn("claim.process status=risk_rejected policy={} amount={}", policyId, amount);
            throw e;
        } catch (CoverageExceededException e) {
            metrics.countClaim(ClaimMetrics.STATUS_COVERAGE_EXCEEDED);
            metrics.recordClaimDuration(System.nanoTime() - start);
            log.warn("claim.process status=coverage_exceeded policy={} amount={}", policyId, amount);
            throw e;
        } catch (PolicyInactiveException e) {
            metrics.countClaim(ClaimMetrics.STATUS_POLICY_INACTIVE);
            metrics.recordClaimDuration(System.nanoTime() - start);
            log.warn("claim.process status=policy_inactive policy={}", policyId);
            throw e;
        } catch (PolicyNotFoundException e) {
            metrics.countClaim(ClaimMetrics.STATUS_POLICY_NOT_FOUND);
            metrics.recordClaimDuration(System.nanoTime() - start);
            log.warn("claim.process status=policy_not_found policy={}", policyId);
            throw e;
        } catch (IllegalArgumentException e) {
            metrics.countClaim(ClaimMetrics.STATUS_INVALID);
            metrics.recordClaimDuration(System.nanoTime() - start);
            log.warn("claim.process status=invalid policy={} amount={} reason={}", policyId, amount, e.getMessage());
            throw e;
        } catch (RuntimeException e) {
            metrics.countClaim(ClaimMetrics.STATUS_ERROR);
            metrics.recordClaimDuration(System.nanoTime() - start);
            log.error("claim.process status=error policy={} amount={}", policyId, amount, e);
            throw e;
        }
    }
}
