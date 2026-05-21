from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
class DetectionInput:
    iteration: int
    section_type: str  # SectionType 값("약관", "상품설명서") 또는 SectionType enum
    content: str
    session_id: str = ""  # 동일 세션의 iteration을 추적하는 키
    product_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionResult:
    violations: list[Violation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0
