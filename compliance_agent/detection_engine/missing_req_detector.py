"""
Rule 5 – MISSING_REQUIREMENT 탐지기
탐지 레이어: DB 검색 (db_client.search) → 키워드 존재 여부 확인

DB팀 RAG API로 필수 기재사항 목록을 조회하고,
각 항목이 약관 본문에 존재하는지 검사한다.
DB팀 API 미제공 시 mock 데이터로 대체한다.
근거: 보험업 감독업무 시행세칙 제5-16조 (보험약관 필수 기재사항)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from compliance_agent.models import DetectionInput, Severity, Violation, ViolationType


@dataclass
class _RequiredItem:
    item_id: str
    name: str
    keywords: list[str]        # 하나라도 있으면 기재 인정
    severity: Severity
    section_types: list[str]   # ["약관", "상품설명서"] or 특정 타입만


# ── Mock 필수 기재사항 목록 ──────────────────────────────────────────────────
# DB팀 API 연결 후 이 목록을 동적으로 교체한다.
MOCK_REQUIRED_ITEMS: list[_RequiredItem] = [
    _RequiredItem(
        item_id="REQ_001",
        name="보험금 지급 사유",
        keywords=["보험금 지급", "지급 사유", "보험사고"],
        severity=Severity.CRITICAL,
        section_types=["약관", "상품설명서"],
    ),
    _RequiredItem(
        item_id="REQ_002",
        name="자기부담금 명시",
        keywords=["자기부담금", "본인부담금", "공제금액"],
        severity=Severity.CRITICAL,
        section_types=["약관", "상품설명서"],
    ),
    _RequiredItem(
        item_id="REQ_003",
        name="보장 제외 항목",
        keywords=["면책", "보장하지 않", "제외"],
        severity=Severity.HIGH,
        section_types=["약관", "상품설명서"],
    ),
    _RequiredItem(
        item_id="REQ_004",
        name="보험료 납입 조건",
        keywords=["보험료", "납입", "납부"],
        severity=Severity.HIGH,
        section_types=["약관"],
    ),
    _RequiredItem(
        item_id="REQ_005",
        name="계약 해지 절차",
        keywords=["해지", "계약 해지", "해약"],
        severity=Severity.HIGH,
        section_types=["약관"],
    ),
    _RequiredItem(
        item_id="REQ_006",
        name="분쟁 조정 기관 안내",
        keywords=["금융감독원", "분쟁조정", "금융분쟁"],
        severity=Severity.MEDIUM,
        section_types=["약관", "상품설명서"],
    ),
    _RequiredItem(
        item_id="REQ_007",
        name="보험 기간",
        keywords=["보험기간", "보장기간", "계약기간"],
        severity=Severity.CRITICAL,
        section_types=["약관", "상품설명서"],
    ),
    _RequiredItem(
        item_id="REQ_008",
        name="청구 절차 및 서류",
        keywords=["청구", "청구서류", "청구 방법"],
        severity=Severity.MEDIUM,
        section_types=["약관"],
    ),
    _RequiredItem(
        item_id="REQ_009",
        name="갱신 조건 및 갱신 거절 사유",
        keywords=["갱신", "갱신 거절", "재가입"],
        severity=Severity.HIGH,
        section_types=["약관"],
    ),
    _RequiredItem(
        item_id="REQ_010",
        name="고지의무 및 위반 효과",
        keywords=["고지의무", "알릴 의무", "고지 위반"],
        severity=Severity.HIGH,
        section_types=["약관"],
    ),
]


_VALID_SECTION_TYPES: frozenset[str] = frozenset({"약관", "상품설명서"})


def _fetch_required_items(section_type: str) -> list[_RequiredItem]:
    """DB팀 API 호출 시도 후 실패하거나 MOCK_MODE면 mock 반환."""
    from compliance_agent.external_apis.db_client import MOCK_MODE
    if MOCK_MODE:
        return [item for item in MOCK_REQUIRED_ITEMS if section_type in item.section_types]
    try:
        from compliance_agent.external_apis.db_client import DBClient
        items = DBClient().search(query="필수 기재사항", section_type=section_type)
        return items if items else [
            item for item in MOCK_REQUIRED_ITEMS if section_type in item.section_types
        ]
    except Exception:
        return [item for item in MOCK_REQUIRED_ITEMS if section_type in item.section_types]


class MissingReqDetector:
    """Rule 5: 필수 기재사항 누락 탐지"""

    def detect(self, data: DetectionInput) -> list[Violation]:
        if data.section_type not in _VALID_SECTION_TYPES:
            return [Violation(
                violation_id="VIO_MRQ_INVALID_SECTION",
                type=ViolationType.MISSING_REQUIREMENT,
                severity=Severity.CRITICAL,
                original_text="",
                regulation="보험업 감독업무 시행세칙 제5-16조",
                reason=(
                    f"알 수 없는 section_type '{data.section_type}'. "
                    f"유효값: {sorted(_VALID_SECTION_TYPES)}"
                ),
            )]

        # 기존 하드코딩 체크 (fallback, coverage_context 유무와 무관하게 항상 실행)
        required_items = _fetch_required_items(data.section_type)
        violations: list[Violation] = []
        for item in required_items:
            if not self._is_present(data.content, item.keywords):
                violations.append(self._build_violation(item))

        # coverage_context 기반 동적 체크
        if data.coverage_context is not None:
            violations.extend(self._dynamic_checks(data))

        return violations

    def _dynamic_checks(self, data: DetectionInput) -> list[Violation]:
        """coverage_context 필드별 추가 필수항목 체크. VIO_MSR_005_XXX 형식."""
        ctx = data.coverage_context
        violations: list[Violation] = []
        seq = 1

        def _add(reason: str, severity: Severity = Severity.HIGH) -> None:
            nonlocal seq
            violations.append(Violation(
                violation_id=f"VIO_MSR_005_{seq:03d}",
                type=ViolationType.MISSING_REQUIREMENT,
                severity=severity,
                original_text="(해당 항목 없음)",
                regulation="보험업 감독업무 시행세칙 제5-16조",
                reason=reason,
            ))
            seq += 1

        if ctx.deductible_required:
            if not self._is_present(
                data.content,
                ["급여 자기부담금", "비급여 자기부담금", "3대비급여", "급여·비급여"],
            ):
                _add(
                    "급여·비급여·3대비급여별 자기부담금 구분 명시가 필요합니다.",
                    Severity.CRITICAL,
                )

        if ctx.three_major_noncovered_required:
            for name, kws in [
                ("도수치료·체외충격파·증식치료", ["도수치료", "체외충격파", "증식치료"]),
                ("주사료", ["주사료", "주사치료"]),
                ("MRI", ["MRI", "자기공명영상"]),
            ]:
                if not self._is_present(data.content, kws):
                    _add(f"3대비급여 항목 '{name}' 명시가 필요합니다.")

        if ctx.proportional_compensation:
            if not self._is_present(data.content, ["비례보상", "비례 보상"]):
                _add("비례보상 조항 명시가 필요합니다.")

        if ctx.re_enrollment_condition_required:
            if not self._is_present(data.content, ["재가입", "재가입 조건", "재계약"]):
                _add("재가입 조건 명시가 필요합니다.")

        if ctx.coverage_limit:
            for category, limit in ctx.coverage_limit.items():
                if not self._is_present(data.content, [f"{limit:,}", str(limit)]):
                    _add(
                        f"보장한도 '{category}: {limit:,}원'이 약관 본문에 명시되어야 합니다."
                    )

        if ctx.premium_change_reason_required:
            change_reasons = {
                "나이 증가": ["나이", "연령"],
                "위험률 변동": ["위험률"],
                "의료수가 변동": ["의료수가"],
                "비급여 이용량": ["비급여 이용량"],
            }
            missing = [
                name for name, kws in change_reasons.items()
                if not self._is_present(data.content, kws)
            ]
            if missing:
                _add(
                    f"갱신형 보험료 변경 사유({', '.join(missing)}) 명시가 필요합니다."
                )

        return violations

    def _is_present(self, content: str, keywords: list[str]) -> bool:
        return any(re.search(kw, content) for kw in keywords)

    def _build_violation(self, item: _RequiredItem) -> Violation:
        return Violation(
            violation_id=f"VIO_MRQ_{item.item_id}",
            type=ViolationType.MISSING_REQUIREMENT,
            severity=item.severity,
            original_text="(해당 항목 없음)",
            regulation="보험업 감독업무 시행세칙 제5-16조",
            reason=(
                f"필수 기재사항 '{item.name}'({item.item_id})이 "
                "약관 본문에서 확인되지 않습니다."
            ),
        )
