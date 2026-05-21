"""
루프 종료 조건을 판단한다.
CLAUDE.md 종료 조건:
  PASS       – violations == 0
  FAIL_MAX   – iteration >= 3
  FAIL_LOOP  – 동일 위반 2회 이상 반복
"""
from __future__ import annotations

from enum import Enum

from .iteration_tracker import IterationTracker, MAX_ITERATIONS
from compliance_agent.models import Violation


class TerminationReason(str, Enum):
    PASS = "PASS"
    FAIL_MAX = "FAIL_MAX"
    FAIL_LOOP = "FAIL_LOOP"   # deprecated: HARD_LOOP으로 대체
    HARD_LOOP = "HARD_LOOP"   # 위반 수 delta >= 0 (개선 없음) → GENERATOR_FAILURE
    CONTINUE = "CONTINUE"


class TerminationLogic:
    def evaluate(
        self,
        violations: list[Violation],
        tracker: IterationTracker,
        current_iteration: int,
    ) -> TerminationReason:
        if not violations:
            return TerminationReason.PASS
        # HARD_LOOP: 직전 대비 위반 수 감소 없음 → 생성 에이전트가 수렴 불가 판정
        if tracker.has_hard_loop():
            return TerminationReason.HARD_LOOP
        if current_iteration >= MAX_ITERATIONS:
            return TerminationReason.FAIL_MAX
        return TerminationReason.CONTINUE
