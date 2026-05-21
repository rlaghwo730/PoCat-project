"""
반복 상태와 위반 이력을 추적한다.
FAIL_LOOP 조건(동일 위반 2회 이상 반복) 감지에 사용된다.
"""
from __future__ import annotations

from compliance_agent.models import Violation

MAX_ITERATIONS = 3


class IterationTracker:
    def __init__(self) -> None:
        self._history: list[list[Violation]] = []

    @property
    def iteration(self) -> int:
        return len(self._history)

    def record(self, violations: list[Violation]) -> None:
        self._history.append(violations)

    def repeated_violation_ids(self) -> set[str]:
        """서로 다른 2개 이상의 iteration run에서 등장한 violation_id 집합."""
        from collections import defaultdict
        id_to_runs: defaultdict[str, set[int]] = defaultdict(set)
        for run_idx, run in enumerate(self._history):
            for v in run:
                id_to_runs[v.violation_id].add(run_idx)
        return {vid for vid, runs in id_to_runs.items() if len(runs) >= 2}

    def violation_delta(self) -> int | None:
        """최근 두 iteration의 위반 수 차이. 양수=악화, 0=정체, 음수=개선. history < 2이면 None."""
        if len(self._history) < 2:
            return None
        return len(self._history[-1]) - len(self._history[-2])

    def consecutive_violation_ids(self, min_consecutive: int = 3) -> set[str]:
        """최근 min_consecutive 번의 run에서 연속으로 등장한 violation_id 집합 (SOFT_LOOP 판정용)."""
        if len(self._history) < min_consecutive:
            return set()
        recent = self._history[-min_consecutive:]
        id_sets = [set(v.violation_id for v in run) for run in recent]
        return id_sets[0].intersection(*id_sets[1:])

    def is_max_iteration_reached(self) -> bool:
        return self.iteration >= MAX_ITERATIONS

    def has_loop_failure(self) -> bool:
        return len(self.repeated_violation_ids()) > 0

    def has_soft_loop(self) -> bool:
        """3회 연속 등장한 violation_id가 존재하면 True."""
        return len(self.consecutive_violation_ids()) > 0

    def has_hard_loop(self) -> bool:
        """직전 대비 위반 수 감소가 없으면(delta >= 0) True → GENERATOR_FAILURE 대상."""
        delta = self.violation_delta()
        return delta is not None and delta >= 0
