"""
총괄 오케스트레이터 — 진입점.

실제 역할별 로직은 core/ 하위 모듈에 위임한다.
  core/request_handler.py  → 1. 요청이해
  core/planner.py          → 2. 작업계획
  core/dispatcher.py       → 3. 작업 분배
  core/aggregator.py       → 4. 결과 종합
  core/reporter.py         → 5. 최종 보고 및 제안
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from langfuse import observe

from compliance_agent.compliance_agent import ComplianceAgent
from generation_agent.agents.generation_agent import GenerationAgent

from orchestrator.adapters import build_violations_for_ui
from orchestrator.core import aggregator, dispatcher, planner, reporter, request_handler
from orchestrator.core.observability import bind_session, create_langfuse_handler
from orchestrator.models.execution_plan import ExecutionPlan
from orchestrator.models.orchestrator_result import OrchestratorResult

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self) -> None:
        self._gen = GenerationAgent()
        self._comp = ComplianceAgent()

    def generate_description(self, content: str, request: dict) -> str:
        """GenerationAgent.generate_product_description()를 위임한다."""
        return self._gen.generate_product_description(content, request)

    @observe(name="orchestrator_run", capture_input=False)
    def run(
        self,
        request: dict,
        session_id: str,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """생성 → 검증 → 재생성 루프를 실행하고 최종 결과 dict를 반환한다."""
        def _notify(msg: str) -> None:
            if status_callback:
                status_callback(msg)
            logger.info(msg)

        gen_result: dict = {}
        plan = ExecutionPlan(
            document_type="", product_name="",
            max_iterations=3, complexity="NORMAL",
        )
        iteration = 0

        try:
            # Langfuse: 현재 trace에 session_id 연결 + 매 요청마다 새 핸들러 주입
            bind_session(session_id)
            self._gen.langfuse_handler = create_langfuse_handler()

            # 1. 요청이해
            _notify("[Orchestrator] 요청 검증 중...")
            request_handler.validate(request)
            _notify("[Orchestrator] 요청 검증 완료")

            # 2. 작업계획
            plan = planner.build_plan(request)
            _notify(
                f"[Orchestrator] 작업 계획 수립 — "
                f"문서 유형: {plan.document_type} | "
                f"복잡도: {plan.complexity} | "
                f"최대 반복: {plan.max_iterations}회"
            )

            # 3. 작업 분배
            gen_result, report, history = dispatcher.run_loop(
                self._gen, self._comp, request, plan, session_id, _notify
            )
            iteration = history[-1]["iteration"] if history else 0

            # 최종 상태 결정
            if report is None:
                final_status = "ORCHESTRATOR_ERROR"
            elif report.status == "COMPLIANCE_PASSED":
                final_status = "COMPLIANCE_PASSED"
            else:
                final_status = "MANUAL_REVIEW_REQUIRED"

            # 4. 결과 종합
            aggregated = aggregator.aggregate(history)

            # 5. 최종 보고 및 제안
            final_report = reporter.build_final_report(
                final_status, report, plan, aggregated, iteration
            )
            _notify(f"[Orchestrator] 완료 — {final_status} | {final_report['summary']}")

            try:
                report_dict = report.to_dict() if report else {}
            except Exception:
                report_dict = {
                    "status": getattr(report, "status", ""),
                    "iteration": getattr(report, "iteration", iteration),
                }

            return OrchestratorResult(
                status=final_status,
                content=gen_result.get("content", ""),
                iteration=iteration,
                violations_for_ui=build_violations_for_ui(report) if report else [],
                report=report_dict,
                error=None,
                summary=final_report["summary"],
                next_action=final_report["next_action"],
                improvement_note=final_report["improvement_note"],
                suggestions=final_report["suggestions"],
                db_warning=final_report.get("db_warning"),
                plan=plan.to_dict(),
                aggregated=aggregated,
            ).to_dict()

        except ValueError as ve:
            _notify(f"[Orchestrator] 요청 오류: {ve}")
            return _error_result(gen_result, iteration, str(ve), plan).to_dict()

        except Exception as exc:
            logger.exception("Orchestrator 실행 중 예외 발생: %s", exc)
            return _error_result(gen_result, iteration, str(exc), plan).to_dict()


def _error_result(
    gen_result: dict,
    iteration: int,
    error_msg: str,
    plan: ExecutionPlan,
) -> OrchestratorResult:
    return OrchestratorResult(
        status="ORCHESTRATOR_ERROR",
        content=gen_result.get("content", ""),
        iteration=iteration,
        error=error_msg,
        summary=f"오류 발생: {error_msg}",
        next_action="ERROR",
        plan=plan.to_dict(),
    )
