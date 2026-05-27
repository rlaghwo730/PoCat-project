from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ViolationType(str, Enum):
    OVERSTATEMENT = "OVERSTATEMENT"
    SUBJECTIVE = "SUBJECTIVE"
    CONTRADICTION = "CONTRADICTION"
    FORBIDDEN_WORD = "FORBIDDEN_WORD"
    MISSING_REQUIREMENT = "MISSING_REQUIREMENT"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SectionType(str, Enum):
    TERMS = "약관"
    PRODUCT_DESCRIPTION = "상품설명서"


@dataclass
class Violation:
    violation_id: str
    type: ViolationType
    severity: Severity
    original_text: str
    regulation: str
    reason: str
    manual_flag: bool = False  # SOFT_LOOP: 3회 연속 등장 → 수동 검토 필요


@dataclass
class CoverageContext:
    """product_meta에 포함되는 보장 컨텍스트 구조체. 모든 필드는 선택적."""
    coverage_limit: Optional[dict] = None
    deductible_required: Optional[bool] = None
    three_major_noncovered_required: Optional[bool] = None
    proportional_compensation: Optional[bool] = None
    re_enrollment_condition_required: Optional[bool] = None
    exclusions: Optional[list[str]] = None          # Rule 3: 면책 항목 목록
    mandatory_rider_yn: Optional[bool] = None        # Rule 3: 의무 가입 여부
    premium_change_reason_required: Optional[bool] = None  # Rule 5: 보험료 변경 사유 명시 필요


@dataclass
class DetectionInput:
    iteration: int
    section_type: str  # SectionType 값("약관", "상품설명서") 또는 SectionType enum
    content: str
    session_id: str = ""  # 동일 세션의 iteration을 추적하는 키
    product_meta: dict[str, Any] = field(default_factory=dict)
    coverage_context: Optional[CoverageContext] = None
    max_iterations: int = 3  # 오케스트레이터(plan)가 지정. FAIL_MAX 판정 기준의 단일 소스.


@dataclass
class DetectionResult:
    violations: list[Violation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0
