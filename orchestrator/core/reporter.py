"""5. 최종 보고 및 제안 — 실행 결과를 요약하고 다음 액션을 제안한다."""
from __future__ import annotations

from typing import Optional

from orchestrator.models.execution_plan import ExecutionPlan


def build_final_report(
    final_status: str,
    report,
    plan: ExecutionPlan,
    aggregated: dict,
    iteration: int,
) -> dict:
    """최종 상태에 따라 요약·제안·다음 액션을 생성한다.

    Returns:
        {
            "summary"          : str,
            "next_action"      : str,
            "improvement_note" : str | None,
            "suggestions"      : list[dict],
            "db_warning"       : str | None,
        }
    """
    suggestions: list[dict] = []

    if final_status == "COMPLIANCE_PASSED":
        summary = (
            f"총 {iteration}회 반복 끝에 법률 규제 검증을 통과했습니다. "
            f"({plan.document_type} / {plan.product_name})"
        )
        next_action = "PUBLISH_READY"

    elif final_status == "MANUAL_REVIEW_REQUIRED":
        remaining = len(report.violations) if report else 0
        summary = (
            f"{plan.max_iterations}회 반복 후에도 위반 사항 {remaining}건이 남아 "
            "담당자의 수동 검토가 필요합니다."
        )
        next_action = "MANUAL_REVIEW_REQUIRED"

        if report:
            for v in report.violations:
                suggestions.append({
                    "violation_id": v.violation_id,
                    "type": getattr(v.type, "value", str(v.type)),
                    "severity": getattr(v.severity, "value", str(v.severity)),
                    "action": v.reason,
                    "target_text": v.original_text,
                    "requires_manual_review": getattr(v, "manual_flag", False),
                })

    else:
        summary = "오케스트레이터 실행 중 오류가 발생했습니다."
        next_action = "ERROR"

    db_warning = _db_mode_warning(plan)

    return {
        "summary": summary,
        "next_action": next_action,
        "improvement_note": _improvement_note(aggregated),
        "suggestions": suggestions,
        "db_warning": db_warning,
    }


def _db_mode_warning(plan: ExecutionPlan) -> Optional[str]:
    """MOCK_MODE일 때 MISSING_REQUIREMENT 탐지 정확도 저하 경고 문자열을 반환한다."""
    if plan.db_mode == "MOCK":
        return (
            "DB_API_URL이 설정되지 않아 규제 DB가 MOCK 모드로 동작했습니다. "
            "MISSING_REQUIREMENT 위반 탐지 결과가 실제와 다를 수 있습니다. "
            "정확한 검증을 위해 DB_API_URL 환경변수를 설정하세요."
        )
    return None


def _improvement_note(aggregated: dict) -> Optional[str]:
    """위반 건수 변화를 자연어로 표현한다."""
    total = aggregated.get("total_improvement")
    if total is None:
        return None
    if total > 0:
        rate = aggregated.get("improvement_rate_pct", "")
        return f"위반 건수가 {total}건 감소했습니다. (개선율 {rate}%)"
    if total == 0:
        return "반복 간 위반 건수 변화가 없었습니다."
    return f"위반 건수가 {abs(total)}건 증가했습니다. 생성 품질을 점검하세요."
