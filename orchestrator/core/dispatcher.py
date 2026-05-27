"""3. 작업 분배 — GenerationAgent → ComplianceAgent 순차 실행 루프."""
from __future__ import annotations

import logging
from typing import Callable

from orchestrator.adapters import build_compliance_feedback, build_detection_input
from orchestrator.models.execution_plan import ExecutionPlan

logger = logging.getLogger(__name__)


def run_loop(
    gen_agent,
    comp_agent,
    request: dict,
    plan: ExecutionPlan,
    session_id: str,
    notify: Callable[[str], None],
) -> tuple[dict, object, list[dict]]:
    """생성 → 검증 → 재생성 루프를 실행한다.

    Returns:
        gen_result  : 마지막 GenerationAgent 출력
        report      : 마지막 ComplianceReport
        history     : 반복별 상태 이력 리스트
    """
    gen_result: dict = {}
    report = None
    compliance_feedback: dict = {}
    history: list[dict] = []

    for iteration in range(1, plan.max_iterations + 1):
        # ── 약관 생성 or 재생성 ─────────────────────────────────────────
        if iteration == 1:
            notify(f"[Iteration {iteration}] 약관 생성 중...")
            gen_result = gen_agent.generate(request)
        else:
            notify(f"[Iteration {iteration}] 약관 재생성 중...")
            gen_result = gen_agent.regenerate(request, compliance_feedback, iteration)

        notify(f"[Iteration {iteration}] 약관 생성 완료")

        # ── 법률 규제 검증 ──────────────────────────────────────────────
        detection_input = build_detection_input(
            gen_result, request, session_id, iteration, plan.max_iterations
        )
        report = comp_agent.validate(detection_input)
        notify(f"[Iteration {iteration}] 법률 규제 검토 완료: {report.status}")

        # ── 반복 이력 기록 ──────────────────────────────────────────────
        history.append({
            "iteration": iteration,
            "status": report.status,
            "violation_count": len(report.violations),
            "violation_types": list(
                {getattr(v.type, "value", str(v.type)) for v in report.violations}
            ),
        })

        if report.status == "COMPLIANCE_PASSED":
            break

        # 조기 종료: ComplianceAgent가 수렴 불가(HARD_LOOP) 또는 최대 반복 도달(FAIL_MAX)을
        # 판정하면 남은 반복을 돌지 않고 종료해 불필요한 재생성 LLM 호출을 막는다.
        next_action = getattr(report, "next_action", None) or ""
        if next_action == "MANUAL_REVIEW_REQUIRED" or next_action.startswith("GENERATOR_FAILURE"):
            notify(f"[Iteration {iteration}] 조기 종료 — {next_action}")
            break

        compliance_feedback = build_compliance_feedback(report)

    return gen_result, report, history
