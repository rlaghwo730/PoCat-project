"""
두 에이전트 간 데이터 변환 어댑터.

- build_detection_input : GenerationAgent 출력 → ComplianceAgent 입력(DetectionInput)
- build_compliance_feedback : ComplianceReport → GenerationAgent.regenerate() feedback dict
- build_violations_for_ui  : ComplianceReport.violations → app.py 하이라이트용 dict 리스트
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from compliance_agent.models import CoverageContext, DetectionInput
from compliance_agent.models.compliance_report import ComplianceReport

logger = logging.getLogger(__name__)

# ── coverage_limit 한국어 금액 표기 파서 ────────────────────────────────────
# ComplianceAgent의 missing_req_detector는 ctx.coverage_limit를 dict[str, int]로 가정하고
# f"{limit:,}" 포맷을 적용한다. UI는 "5천만원" 같은 문자열을 보내므로 정수로 변환해야 한다.
_AMOUNT_PATTERN = re.compile(
    r"^\s*"
    r"(?:(\d+(?:,\d{3})*)\s*억)?\s*"
    r"(?:(\d+(?:,\d{3})*)\s*(천만|만|천))?\s*"
    r"원?\s*$"
)


def _parse_korean_amount(text: str) -> Optional[int]:
    """'5천만원', '1억원', '3억5천만원', '5000만원' 등의 표기를 정수(원)로 변환."""
    if not isinstance(text, str):
        return None
    m = _AMOUNT_PATTERN.match(text.strip())
    if not m:
        return None

    eok_str, num_str, unit = m.group(1), m.group(2), m.group(3)
    if not eok_str and not num_str:
        return None

    total = 0
    if eok_str:
        total += int(eok_str.replace(",", "")) * 100_000_000
    if num_str:
        n = int(num_str.replace(",", ""))
        if unit == "천만":
            total += n * 10_000_000
        elif unit == "만":
            total += n * 10_000
        elif unit == "천":
            total += n * 1_000
    return total or None


def build_detection_input(
    gen_result: dict,
    request: dict,
    session_id: str,
    iteration: int,
    max_iterations: int = 3,
) -> DetectionInput:
    """GenerationAgent 결과 + 원본 request → DetectionInput."""
    cov = request.get("coverage_conditions", {})

    # coverage_limit: ComplianceAgent missing_req_detector는 dict[str, int]를 기대한다.
    # (rule이 f"{limit:,}" 포맷을 적용하므로 값은 반드시 정수여야 한다.)
    # UI는 "5천만원" 같은 문자열을 보내므로 파싱해서 dict로 감싼다.
    coverage_limit_raw = cov.get("coverage_limit")
    coverage_limit: Optional[dict] = None

    if isinstance(coverage_limit_raw, dict):
        # 이미 dict이면 값이 모두 int인지 검증 (다른 타입이면 detector에서 크래시)
        if all(isinstance(v, int) for v in coverage_limit_raw.values()):
            coverage_limit = coverage_limit_raw
        else:
            logger.warning(
                "coverage_limit dict 값에 int가 아닌 항목이 있어 무시합니다: %s",
                coverage_limit_raw,
            )
    elif isinstance(coverage_limit_raw, str) and coverage_limit_raw:
        parsed = _parse_korean_amount(coverage_limit_raw)
        if parsed is not None:
            # category 키는 detector의 오류 메시지에만 노출되므로 UI 라벨과 일치시킨다.
            coverage_limit = {"보장한도": parsed}
        else:
            logger.warning(
                "coverage_limit 문자열 '%s'을 파싱하지 못해 검증에서 제외합니다.",
                coverage_limit_raw,
            )

    noncovered_rider = cov.get("noncovered_rider_items") or []
    three_major = cov.get("three_major_noncovered_items") or []
    deductible_rule = cov.get("deductible_rule", "")

    coverage_context = CoverageContext(
        coverage_limit=coverage_limit,
        deductible_required=bool(deductible_rule),
        three_major_noncovered_required=bool(three_major),
        exclusions=noncovered_rider + three_major if (noncovered_rider or three_major) else None,
        proportional_compensation=None,
        re_enrollment_condition_required=None,
        mandatory_rider_yn=None,
        premium_change_reason_required=None,
    )

    # 데이터 파이프라인 SamsungDataLoader.convert_to_detection_input() 기준으로
    # product_meta 필드를 보강한다. gen_result의 값을 우선하되 누락된 키를 채운다.
    base_meta = gen_result.get("product_meta", {})
    doc_req = request.get("document_request", {})
    product_meta = {
        "company": doc_req.get("insurance_company", base_meta.get("company", "unknown")),
        "document_type": doc_req.get("document_type", base_meta.get("document_type", "약관")),
        "product_name": doc_req.get("product_name", base_meta.get("product_name", "unknown")),
        "policy_type": "medical_loss",
        **base_meta,   # gen_result의 기존 메타 값이 위를 덮어쓰도록 마지막에 병합
    }

    return DetectionInput(
        iteration=iteration,
        section_type=gen_result.get("section_type", "약관"),
        content=gen_result.get("content", ""),
        session_id=session_id,
        product_meta=product_meta,
        coverage_context=coverage_context,
    )


def build_violations_for_ui(report: ComplianceReport) -> list:
    """ComplianceReport.violations → apply_violation_highlights() 호환 dict 리스트."""
    result = []
    for v in report.violations:
        result.append({
            "type": getattr(v.type, "value", str(v.type)),
            "legal_basis": v.regulation,
            "fix": v.reason,
            "original_text": v.original_text,
        })
    return result


def build_compliance_feedback(report: ComplianceReport) -> dict:
    """ComplianceReport → GenerationAgent.regenerate() feedback dict.

    priority_fixes는 PriorityFix 객체 리스트이므로 반드시 str 리스트로 변환한다.
    """
    if report.feedback_to_generator is None:
        priority_fixes: list[str] = []
        violation_summary = None
    else:
        priority_fixes = [
            f"[{fix.violation_id}] {fix.instruction} / 제약: {fix.repair_constraints}"
            for fix in report.feedback_to_generator.priority_fixes
        ]
        vs = report.feedback_to_generator.violation_summary
        if vs is not None:
            violation_summary = {
                "total": vs.total,
                "delivered": vs.delivered,
                "deferred": vs.deferred,
                "deferred_by_type": vs.deferred_by_type,
            }
        else:
            violation_summary = None

    return {
        "status": report.status,
        "priority_fixes": priority_fixes,
        "violation_summary": violation_summary,
        "violations": build_violations_for_ui(report),
    }
