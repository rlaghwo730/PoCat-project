"""4. 결과 종합 — 반복별 이력을 집계하여 위반 추이와 개선율을 산출한다."""
from __future__ import annotations

from typing import Optional


def aggregate(history: list[dict]) -> dict:
    """dispatcher가 기록한 반복 이력을 집계한다.

    Returns:
        {
            "iterations_run"                  : int,
            "violation_counts_per_iteration"  : list[int],
            "total_improvement"               : int | None,  # 첫 회 - 마지막 회
            "improvement_rate_pct"            : float | None,
            "iteration_history"               : list[dict],
        }
    """
    if not history:
        return {}

    counts = [h["violation_count"] for h in history]

    total_improvement: Optional[int] = (
        counts[0] - counts[-1] if len(counts) >= 2 else None
    )

    improvement_rate: Optional[float] = None
    if total_improvement is not None and counts[0] > 0:
        improvement_rate = round(total_improvement / counts[0] * 100, 1)

    return {
        "iterations_run": len(history),
        "violation_counts_per_iteration": counts,
        "total_improvement": total_improvement,
        "improvement_rate_pct": improvement_rate,
        "iteration_history": history,
    }
