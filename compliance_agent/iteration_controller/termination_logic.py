"""
루프 종료 조건을 판단한다.
종료 조건:
  PASS            – violations == 0
  PASS_THRESHOLD  – 경미한 위반만 있고 compliance_score >= ACCURACY_THRESHOLD
  FAIL_MAX        – iteration >= MAX_ITERATIONS
  FAIL_LOOP       – deprecated: HARD_LOOP으로 대체
  HARD_LOOP       – 직전 위반 ID가 모두 잔존 (개선 없음) → GENERATOR_FAILURE
"""
from __future__ import annotations

from enum import Enum

from .iteration_tracker import IterationTracker, MAX_ITERATIONS
from compliance_agent.models import Severity, Violation

# 정확도 기반 조기 종료 임계치 (80% 이상이면 잔여 위반이 있어도 루프 종료)
ACCURACY_THRESHOLD = 0.80


class TerminationReason(str, Enum):
    PASS = "PASS"
    PASS_THRESHOLD = "PASS_THRESHOLD"  # 정확도 임계치 달성으로 조기 종료
    FAIL_MAX = "FAIL_MAX"
    FAIL_LOOP = "FAIL_LOOP"   # deprecated: HARD_LOOP으로 대체
    HARD_LOOP = "HARD_LOOP"   # 직전 위반이 모두 잔존 → GENERATOR_FAILURE
    CONTINUE = "CONTINUE"


class TerminationLogic:
    def evaluate(
        self,
        violations: list[Violation],
        tracker: IterationTracker,
        current_iteration: int,
        compliance_score: float = 0.0,
    ) -> TerminationReason:
        if not violations:
            return TerminationReason.PASS
        # 정확도 임계치는 경미한 위반에만 허용한다. CRITICAL/HIGH 및 탐지기
        # 실행 실패를 정상 통과로 바꾸면 안 된다.
        threshold_blocked = any(
            v.severity in {Severity.CRITICAL, Severity.HIGH}
            or v.manual_flag
            or v.violation_id.endswith("LLM_FAIL")
            for v in violations
        )
        if compliance_score >= ACCURACY_THRESHOLD and not threshold_blocked:
            return TerminationReason.PASS_THRESHOLD
        # HARD_LOOP: 직전 위반이 하나도 해결되지 않음 → 생성 에이전트 수렴 불가 판정
        if tracker.has_hard_loop():
            return TerminationReason.HARD_LOOP
        if current_iteration >= MAX_ITERATIONS:
            return TerminationReason.FAIL_MAX
        return TerminationReason.CONTINUE
