"""
법률규제 검증 에이전트 – 메인 오케스트레이터

생성 에이전트로부터 INPUT을 받아:
  - 위반 없음            → COMPLIANCE_PASSED (next_action: READY_FOR_DELIVERY)
  - 준수율 >= 80%        → COMPLIANCE_PASSED (next_action: THRESHOLD_PASSED, 잔여 위반 포함)
  - 위반 있음 / 루프 계속 → VIOLATIONS_FOUND (next_action: REGENERATE)
  - FAIL_MAX             → VIOLATIONS_FOUND (next_action: MANUAL_REVIEW_REQUIRED)
  - HARD_LOOP            → VIOLATIONS_FOUND (next_action: GENERATOR_FAILURE)
"""
from __future__ import annotations

import asyncio
import logging

from compliance_agent.detection_engine.violation_detector import ViolationDetector
from compliance_agent.final_validation.confidence_calculator import calculate
from compliance_agent.final_validation.final_check import FinalCheck
from compliance_agent.iteration_controller.feedback_builder import FeedbackBuilder
from compliance_agent.iteration_controller.iteration_tracker import IterationTracker
from compliance_agent.iteration_controller.termination_logic import (
    ACCURACY_THRESHOLD,
    TerminationLogic,
    TerminationReason,
)
from compliance_agent.models import ComplianceReport, DetectionInput, FinalValidation

logger = logging.getLogger(__name__)


class ComplianceAgent:
    def __init__(self) -> None:
        self._detector = ViolationDetector()
        self._termination = TerminationLogic()
        self._feedback_builder = FeedbackBuilder()
        self._final_check = FinalCheck()
        # session_id 별로 IterationTracker를 관리한다.
        # 동일 세션의 여러 iteration은 같은 ComplianceAgent 인스턴스를 재사용하거나
        # DetectionInput.session_id를 동일하게 설정해야 FAIL_MAX/FAIL_LOOP가 작동한다.
        self._trackers: dict[str, IterationTracker] = {}

    def validate(self, input_data: DetectionInput) -> ComplianceReport:
        """동기 호출용 API. 비동기 코드에서는 ``validate_async``를 사용한다."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.validate_async(input_data))
        raise RuntimeError(
            "실행 중인 event loop에서는 await ComplianceAgent.validate_async(...)를 사용하세요."
        )

    async def validate_async(self, input_data: DetectionInput) -> ComplianceReport:
        """이벤트 루프를 중첩 생성하지 않는 비동기 검증 API."""
        session_key = input_data.session_id or "__default__"
        tracker = self._trackers.setdefault(session_key, IterationTracker())

        logger.info(
            "Iteration %d – session=%s section_type=%s",
            input_data.iteration,
            session_key,
            input_data.section_type,
        )
        if input_data.coverage_context is not None:
            logger.info(
                "coverage_context 주입됨 → missing_req/contradiction 동적 체크 활성화"
            )

        content_length = len(input_data.content)
        try:
            detection_result = await self._detector.detect(input_data)
        except Exception:
            # 탐지 중단 세션은 이후 반복에 사용할 수 없으며, 고유 session_id가
            # 계속 유입될 때 tracker가 누적되지 않도록 즉시 정리한다.
            self._trackers.pop(session_key, None)
            raise
        tracker.record(detection_result.violations)

        # SOFT_LOOP: 3회 연속 등장한 violation을 사전에 MANUAL_FLAG 처리 (루프는 계속)
        soft_loop_ids = tracker.consecutive_violation_ids()
        if soft_loop_ids:
            logger.warning("SOFT_LOOP: persistent violations flagged – %s", soft_loop_ids)
            for v in detection_result.violations:
                if v.violation_id in soft_loop_ids:
                    v.manual_flag = True

        # 위반 여부와 무관하게 준수율 점수를 먼저 계산
        compliance_score, compliance_checks = calculate(detection_result.violations, content_length)
        logger.info(
            "compliance_score=%.4f (%.1f%%) at iteration %d",
            compliance_score,
            compliance_score * 100,
            input_data.iteration,
        )

        reason = self._termination.evaluate(
            detection_result.violations, tracker, input_data.iteration, compliance_score
        )

        if reason == TerminationReason.PASS:
            logger.info("COMPLIANCE_PASSED at iteration %d", input_data.iteration)
            report = self._final_check.build_passed_report(
                detection_result.violations, input_data.iteration, content_length
            )
            self._trackers.pop(session_key, None)
            return report

        if reason == TerminationReason.PASS_THRESHOLD:
            logger.info(
                "PASS_THRESHOLD reached (score=%.1f%% >= %.0f%%) at iteration %d – minor violations remain",
                compliance_score * 100,
                ACCURACY_THRESHOLD * 100,
                input_data.iteration,
            )
            report = ComplianceReport(
                status="COMPLIANCE_PASSED",
                iteration=input_data.iteration,
                violations=detection_result.violations,
                compliance_score=compliance_score,
                final_validation=FinalValidation(
                    passed=True,
                    confidence_score=compliance_score,
                    checks=compliance_checks,
                ),
                next_action="THRESHOLD_PASSED",
            )
            self._trackers.pop(session_key, None)
            return report

        report = self._feedback_builder.build(
            detection_result.violations, input_data.iteration, content_length
        )

        if reason == TerminationReason.FAIL_MAX:
            logger.warning("FAIL_MAX reached – manual review required")
            report.next_action = "MANUAL_REVIEW_REQUIRED"

        elif reason == TerminationReason.HARD_LOOP:
            logger.warning(
                "HARD_LOOP detected - all previous violation IDs remain"
            )
            report.next_action = "GENERATOR_FAILURE - no improvement detected"

        if reason in {TerminationReason.FAIL_MAX, TerminationReason.HARD_LOOP}:
            self._trackers.pop(session_key, None)

        return report
