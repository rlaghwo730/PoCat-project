"""
위반이 없을 때 OUTPUT B (COMPLIANCE_PASSED)를 생성한다.
"""
from __future__ import annotations

from compliance_agent.models import ComplianceReport, FinalValidation, Violation
from .confidence_calculator import calculate


class FinalCheck:
    def build_passed_report(
        self, violations: list[Violation], iteration: int, content_length: int = 0
    ) -> ComplianceReport:
        confidence_score, checks = calculate(violations, content_length)
        return ComplianceReport(
            status="COMPLIANCE_PASSED",
            iteration=iteration,
            violations=[],
            final_validation=FinalValidation(
                passed=True,
                confidence_score=confidence_score,
                checks=checks,
            ),
            next_action="READY_FOR_DELIVERY",
        )
