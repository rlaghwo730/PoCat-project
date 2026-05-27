"""
법률규제 검증 에이전트 – 메인 오케스트레이터

생성 에이전트로부터 INPUT을 받아:
  - 위반 있음 → OUTPUT A (VIOLATIONS_FOUND) 반환
  - 위반 없음 → OUTPUT B (COMPLIANCE_PASSED) 반환
  - FAIL_MAX / FAIL_LOOP → 경고 포함 OUTPUT A 반환
"""
from __future__ import annotations

import logging

from compliance_agent.detection_engine.violation_detector import ViolationDetector
from compliance_agent.final_validation.final_check import FinalCheck
from compliance_agent.iteration_controller.feedback_builder import FeedbackBuilder
from compliance_agent.iteration_controller.iteration_tracker import IterationTracker
from compliance_agent.iteration_controller.termination_logic import (
    TerminationLogic,
    TerminationReason,
)
from compliance_agent.models import ComplianceReport, DetectionInput

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

        detection_result = self._detector.detect(input_data)
        tracker.record(detection_result.violations)

        # SOFT_LOOP: 3회 연속 등장한 violation을 사전에 MANUAL_FLAG 처리 (루프는 계속)
        soft_loop_ids = tracker.consecutive_violation_ids()
        if soft_loop_ids:
            logger.warning("SOFT_LOOP: persistent violations flagged – %s", soft_loop_ids)
            for v in detection_result.violations:
                if v.violation_id in soft_loop_ids:
                    v.manual_flag = True

        reason = self._termination.evaluate(
            detection_result.violations, tracker, input_data.iteration
        )

        if reason == TerminationReason.PASS:
            logger.info("COMPLIANCE_PASSED at iteration %d", input_data.iteration)
            return self._final_check.build_passed_report(
                detection_result.violations, input_data.iteration, len(input_data.content)
            )

        report = self._feedback_builder.build(
            detection_result.violations, input_data.iteration
        )

        if reason == TerminationReason.FAIL_MAX:
            logger.warning("FAIL_MAX reached – manual review required")
            report.next_action = "MANUAL_REVIEW_REQUIRED"

        elif reason == TerminationReason.HARD_LOOP:
            logger.warning(
                "HARD_LOOP detected - no improvement in violation count (delta >= 0)"
            )
            report.next_action = "GENERATOR_FAILURE - no improvement detected"

        return report
