"""
각 Rule별 PASS/FAIL 결과를 집계하고 신뢰도 점수를 계산한다.
Rule별 가중치: CRITICAL Rule일수록 점수 영향이 크다.

신뢰도 상한:
  - MOCK_MODE(DB_API_URL 미설정): 0.85 — RAG 실증 없이 mock 키워드만 검사한 결과임
  - content_length < 200자: 0.70 — 내용이 너무 짧아 규정 준수 여부 충분히 검증 불가
  - content_length 200-499자: 0.85 — 일부 검증만 가능한 짧은 약관
  - 실제 RAG 연결 + 500자 이상: 1.0 (위반 없음 기준)
"""
from __future__ import annotations

from compliance_agent.models import Violation, ViolationType

# 가중치 근거: 각 Rule의 규제 위반 심각도 기준
# - CONTRADICTION 0.30: 조항 간 모순은 계약 해석 분쟁으로 직결 (민법 §105 신의성실 원칙)
# - FORBIDDEN_WORD 0.25: 보험업법 §95-3 직접 위반 → 과태료·영업정지 처분 대상
# - OVERSTATEMENT 0.20: 시행세칙 §5-18 위반, 소비자 오인 유발
# - SUBJECTIVE 0.15: 시행세칙 §5-17 약관 명확성 원칙, 보완 가능성 있음
# - MISSING_REQUIREMENT 0.10: 시행세칙 §5-16, 누락이지만 추가 기재로 해결 가능
WEIGHT_RATIONALE: dict[str, str] = {
    "CONTRADICTION":       "조항 간 모순 → 계약 해석 분쟁 직결 (민법 §105)",
    "FORBIDDEN_WORD":      "보험업법 §95-3 직접 위반 → 과태료·영업정지",
    "OVERSTATEMENT":       "시행세칙 §5-18 소비자 오인 유발",
    "SUBJECTIVE":          "시행세칙 §5-17 약관 명확성 위반, 보완 여지 있음",
    "MISSING_REQUIREMENT": "시행세칙 §5-16 누락, 기재 추가로 해결 가능",
}

_RULE_WEIGHTS: dict[ViolationType, float] = {
    ViolationType.OVERSTATEMENT: 0.20,       # 소비자 오인, 수정 시 효과 큼
    ViolationType.SUBJECTIVE: 0.15,          # 명확성 위반, 기준 추가로 해결 가능
    ViolationType.CONTRADICTION: 0.30,       # 분쟁 직결, 가장 심각
    ViolationType.FORBIDDEN_WORD: 0.25,      # 법령 직접 위반 (§95-3), 즉각 제재 대상
    ViolationType.MISSING_REQUIREMENT: 0.10, # 누락, 추가 기재로 해결 가능
    # 합계 = 1.00
}

_MOCK_MODE_CONFIDENCE_CAP = 0.85

# (최소 글자 수 미만이면 적용할 상한) — 오름차순 정렬 필수
_CONTENT_COVERAGE_CAPS: list[tuple[int, float]] = [
    (200, 0.70),   # 200자 미만: 짧은 텍스트는 규정 준수 여부 검증 자체가 불충분
    (500, 0.85),   # 200-499자: 일부 조항만 포함된 짧은 약관
]


def calculate(
    violations: list[Violation], content_length: int = 0
) -> tuple[float, dict[str, str]]:
    """(confidence_score, checks_dict) 반환.

    violations: 탐지된 위반 목록 (PASS 시 빈 리스트)
    content_length: 검증 대상 텍스트 길이 — 짧을수록 신뢰도 상한 낮아짐
    """
    from compliance_agent.external_apis.db_client import MOCK_MODE

    failed_types = {v.type for v in violations}
    checks: dict[str, str] = {}
    penalty = 0.0

    for vtype, weight in _RULE_WEIGHTS.items():
        key = vtype.value.lower()
        if vtype in failed_types:
            checks[key] = "FAIL"
            penalty += weight
        else:
            checks[key] = "PASS"

    score = round(max(0.0, 1.0 - penalty), 4)

    if MOCK_MODE:
        score = min(score, _MOCK_MODE_CONFIDENCE_CAP)

    for threshold, cap in _CONTENT_COVERAGE_CAPS:
        if content_length < threshold:
            score = min(score, cap)
            break

    return score, checks
