"""작업계획 데이터클래스."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExecutionPlan:
    """Planner가 수립한 실행 계획."""
    document_type: str
    product_name: str
    max_iterations: int
    complexity: str          # "NORMAL" | "HIGH"
    priority_checks: list[str] = field(default_factory=list)
    db_mode: str = "MOCK"    # "LIVE" | "MOCK" — DB_API_URL 환경변수 유무로 결정

    def to_dict(self) -> dict:
        return {
            "document_type": self.document_type,
            "product_name": self.product_name,
            "max_iterations": self.max_iterations,
            "complexity": self.complexity,
            "priority_checks": self.priority_checks,
            "db_mode": self.db_mode,
        }
