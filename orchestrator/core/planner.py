"""2. 작업계획 — 요청 분석 결과를 기반으로 실행 계획을 수립한다."""
from __future__ import annotations

from orchestrator.core.request_handler import (
    check_environment,
    parse_coverage,
    parse_document_type,
    parse_product_name,
)
from orchestrator.models.execution_plan import ExecutionPlan

MAX_ITERATIONS = 3

# 복잡도 판단 기준: 비급여 항목 총수가 이 값을 초과하면 HIGH
_HIGH_COMPLEXITY_THRESHOLD = 3


def build_plan(request: dict) -> ExecutionPlan:
    """요청을 분석하여 ExecutionPlan을 수립하고 반환한다.

    복잡도 판단 기준:
    - noncovered_rider_items + three_major_noncovered_items 총 항목 수
    - 3개 초과 → HIGH, 이하 → NORMAL
    """
    document_type = parse_document_type(request)
    product_name = parse_product_name(request)
    coverage = parse_coverage(request)

    three_major = coverage.get("three_major_noncovered_items") or []
    noncovered = coverage.get("noncovered_rider_items") or []
    total_noncovered = len(three_major) + len(noncovered)
    complexity = "HIGH" if total_noncovered > _HIGH_COMPLEXITY_THRESHOLD else "NORMAL"

    priority_checks = (
        ["MISSING_REQUIREMENT", "OVERSTATEMENT", "CONTRADICTION"]
        if complexity == "HIGH"
        else ["MISSING_REQUIREMENT", "OVERSTATEMENT"]
    )

    env = check_environment()

    return ExecutionPlan(
        document_type=document_type,
        product_name=product_name,
        max_iterations=MAX_ITERATIONS,
        complexity=complexity,
        priority_checks=priority_checks,
        db_mode=env["db_mode"],
    )
