"""
위반 목록을 생성 에이전트용 피드백(OUTPUT A)으로 변환한다.
CRITICAL/HIGH 우선으로 priority_fixes를 구성한다.
"""
from __future__ import annotations

from compliance_agent.models import (
    ComplianceReport,
    FeedbackToGenerator,
    PriorityFix,
    Severity,
    Violation,
    ViolationSummary,
)

_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}

# 한 번에 생성 에이전트에 전달할 priority_fixes 최대 개수.
# 30+ 위반이 동시에 발견되면 생성 에이전트가 한 iteration에 모두 처리하기 어려우므로
# severity 상위 N개만 우선 수정 지시를 내린다. (violations 리스트는 전체 유지)
_MAX_PRIORITY_FIXES = 10

_INSTRUCTION_TEMPLATE = {
    "OVERSTATEMENT": "과장 표현을 제거하고 자기부담금·보장 한도를 명시하세요.",
    "SUBJECTIVE": "모호한 표현을 구체적인 수치·기간·조건으로 대체하세요.",
    "CONTRADICTION": "충돌하는 두 조항을 검토하여 일관성 있게 수정하세요.",
    "FORBIDDEN_WORD": "금지어를 삭제하거나 허용 표현으로 교체하세요.",
    "MISSING_REQUIREMENT": "해당 필수 기재사항을 약관에 추가하세요.",
}

_REPAIR_CONSTRAINTS_TEMPLATE = {
    "OVERSTATEMENT": (
        "절대적 보장 표현 금지. "
        "인근 문장에 자기부담금 금액 또는 '보장 한도 내' 문구를 명시할 것."
    ),
    "SUBJECTIVE": (
        "수치·기간·열거된 사례 없이 추상적 판단에 맡기는 표현 금지. "
        "예: '상당한 기간' → '30일 이내', '적절한 조치' → '약관 제N조에 따른 조치'."
    ),
    "CONTRADICTION": (
        "보장 범위와 면책 범위가 동일 대상에 대해 상충하면 안 됨. "
        "특약·단서 조항이 본문보다 우선할 경우 명시적으로 표기할 것."
    ),
    "FORBIDDEN_WORD": (
        "감독원 금지어 및 비교 우위 표현 사용 불가. "
        "원금·예금자보호 등 실손보험에 적용 불가한 금융 개념 표현 금지."
    ),
    "MISSING_REQUIREMENT": (
        "보험업감독업무시행세칙 제5-16조 필수 기재사항을 해당 섹션에 추가할 것. "
        "키워드 포함 여부가 아닌 실질적 내용이 기재되어야 함."
    ),
}


class FeedbackBuilder:
    def build(
        self, violations: list[Violation], iteration: int
    ) -> ComplianceReport:
        sorted_violations = sorted(
            violations, key=lambda v: _SEVERITY_ORDER.get(v.severity, 9)
        )
        # 상위 N개만 priority_fixes에 포함. 동일 (type, violation_id prefix) 중복은 압축.
        priority_fixes: list[PriorityFix] = []
        seen_keys: set[tuple[str, str]] = set()
        for v in sorted_violations:
            # 같은 패턴의 다중 매치(VIO_OVR_001_001, _002 …)는 첫 번째만 priority_fix에 포함
            id_prefix = "_".join(v.violation_id.split("_")[:3])
            key = (v.type.value, id_prefix)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            priority_fixes.append(
                PriorityFix(
                    violation_id=v.violation_id,
                    instruction=_INSTRUCTION_TEMPLATE.get(v.type.value, "수정이 필요합니다."),
                    repair_constraints=_REPAIR_CONSTRAINTS_TEMPLATE.get(
                        v.type.value, "관련 규정을 확인하고 수정하세요."
                    ),
                )
            )
            if len(priority_fixes) >= _MAX_PRIORITY_FIXES:
                break
        summary = self._build_summary(sorted_violations, priority_fixes)
        return ComplianceReport(
            status="VIOLATIONS_FOUND",
            iteration=iteration,
            violations=sorted_violations,
            feedback_to_generator=FeedbackToGenerator(
                action="REGENERATE",
                priority_fixes=priority_fixes,
                violation_summary=summary,
            ),
        )

    def _build_summary(
        self, all_violations: list[Violation], delivered_fixes: list[PriorityFix]
    ) -> ViolationSummary | None:
        total = len(all_violations)
        delivered = len(delivered_fixes)
        deferred = total - delivered
        if deferred <= 0:
            return None  # 전량 전달 시 summary 불필요

        delivered_ids = {f.violation_id for f in delivered_fixes}
        deferred_by_type: dict[str, int] = {}
        for v in all_violations:
            if v.violation_id not in delivered_ids:
                key = v.type.value
                deferred_by_type[key] = deferred_by_type.get(key, 0) + 1
        return ViolationSummary(
            total=total,
            delivered=delivered,
            deferred=deferred,
            deferred_by_type=deferred_by_type,
        )
