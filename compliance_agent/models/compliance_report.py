from __future__ import annotations

from dataclasses import dataclass, field

from .violation import Violation


@dataclass
class PriorityFix:
    violation_id: str
    instruction: str
    repair_constraints: str  # 수정 원칙·금지/필수 조건 (수정안 자체는 생성 에이전트 담당)


@dataclass
class ViolationSummary:
    """priority_fixes로 전달되지 않은 위반의 카테고리 집계 — 생성 에이전트가 전체 맥락 파악용."""
    total: int
    delivered: int
    deferred: int
    deferred_by_type: dict[str, int] = field(default_factory=dict)


@dataclass
class FeedbackToGenerator:
    action: str = "REGENERATE"
    priority_fixes: list[PriorityFix] = field(default_factory=list)
    violation_summary: ViolationSummary | None = None


@dataclass
class FinalValidation:
    passed: bool
    confidence_score: float
    checks: dict[str, str] = field(default_factory=dict)  # rule → "PASS" | "FAIL"


@dataclass
class ComplianceReport:
    """CLAUDE.md I/O Contract의 OUTPUT A / OUTPUT B를 모두 표현."""

    status: str                   # "VIOLATIONS_FOUND" | "COMPLIANCE_PASSED"
    iteration: int
    violations: list[Violation] = field(default_factory=list)

    # OUTPUT A 전용
    feedback_to_generator: FeedbackToGenerator | None = None

    # OUTPUT B 전용
    final_validation: FinalValidation | None = None
    next_action: str | None = None

    def to_dict(self) -> dict:
        base = {
            "status": self.status,
            "iteration": self.iteration,
            "violations": [
                {
                    "violation_id": v.violation_id,
                    "type": v.type.value,
                    "severity": v.severity.value,
                    "original_text": v.original_text,
                    "regulation": v.regulation,
                    "reason": v.reason,
                    **({"manual_flag": True} if v.manual_flag else {}),
                }
                for v in self.violations
            ],
        }
        if self.feedback_to_generator:
            fb: dict = {
                "action": self.feedback_to_generator.action,
                "priority_fixes": [
                    {
                        "violation_id": f.violation_id,
                        "instruction": f.instruction,
                        "repair_constraints": f.repair_constraints,
                    }
                    for f in self.feedback_to_generator.priority_fixes
                ],
            }
            if self.feedback_to_generator.violation_summary:
                s = self.feedback_to_generator.violation_summary
                fb["violation_summary"] = {
                    "total": s.total,
                    "delivered": s.delivered,
                    "deferred": s.deferred,
                    "deferred_by_type": s.deferred_by_type,
                }
            base["feedback_to_generator"] = fb
        if self.final_validation:
            base["final_validation"] = {
                "passed": self.final_validation.passed,
                "confidence_score": self.final_validation.confidence_score,
                "checks": self.final_validation.checks,
            }
        if self.next_action:
            base["next_action"] = self.next_action
        return base
