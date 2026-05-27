"""오케스트레이터 최종 반환 데이터클래스."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OrchestratorResult:
    """run()의 반환값을 구조화한 결과 객체."""
    status: str                         # COMPLIANCE_PASSED | MANUAL_REVIEW_REQUIRED | ORCHESTRATOR_ERROR
    content: str                        # 최종 생성 약관 텍스트
    iteration: int                      # 실제 수행된 반복 횟수
    violations_for_ui: list = field(default_factory=list)   # apply_violation_highlights() 입력용
    report: dict = field(default_factory=dict)              # ComplianceReport.to_dict()
    error: Optional[str] = None

    # 5. 최종 보고 및 제안
    summary: str = ""                   # 실행 결과 요약 문장
    next_action: str = ""               # PUBLISH_READY | MANUAL_REVIEW_REQUIRED | ERROR
    improvement_note: Optional[str] = None   # 위반 건수 개선 추이 메시지
    suggestions: list = field(default_factory=list)  # 남은 위반별 수정 제안

    # 데이터 파이프라인 연동 상태
    db_warning: Optional[str] = None   # MOCK_MODE 시 규제 DB 미연결 경고

    # 메타
    plan: dict = field(default_factory=dict)        # ExecutionPlan.to_dict()
    aggregated: dict = field(default_factory=dict)  # 반복별 집계

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "content": self.content,
            "iteration": self.iteration,
            "violations_for_ui": self.violations_for_ui,
            "report": self.report,
            "error": self.error,
            "summary": self.summary,
            "next_action": self.next_action,
            "improvement_note": self.improvement_note,
            "suggestions": self.suggestions,
            "db_warning": self.db_warning,
            "plan": self.plan,
            "aggregated": self.aggregated,
        }
