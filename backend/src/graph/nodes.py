"""LangGraph 노드 함수 정의

플로우:
  START → coordinator → planner → supervisor(허브)
  supervisor → generation → supervisor
  supervisor → compliance → supervisor
  supervisor → edit → supervisor
  supervisor → END
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage

from .types import State
from ..agents.agents import coordinator_llm, planner_llm, supervisor_llm, edit_llm

logger = logging.getLogger(__name__)

# PoCat-project 루트: backend/src/graph/nodes.py 기준 4단계 상위
_ROOT = Path(__file__).parent.parent.parent.parent
_GEN_AGENT_DIR = _ROOT / "generation_agent"

for _p in [str(_ROOT), str(_GEN_AGENT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── 프롬프트 로더 ─────────────────────────────────────────────────────────────

def _prompt(name: str) -> str:
    path = Path(__file__).parent.parent / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")


# ── 기존 에이전트 지연 초기화 ─────────────────────────────────────────────────

_generation_agent = None
_compliance_agent = None


def _get_generation_agent():
    global _generation_agent
    if _generation_agent is None:
        from generation_agent.agents.generation_agent import GenerationAgent
        _generation_agent = GenerationAgent()
    return _generation_agent


def _get_compliance_agent():
    global _compliance_agent
    if _compliance_agent is None:
        from compliance_agent.compliance_agent import ComplianceAgent
        _compliance_agent = ComplianceAgent()
    return _compliance_agent


# ── 노드 함수 ─────────────────────────────────────────────────────────────────

async def coordinator_node(state: State) -> dict:
    """요청 분석 및 유효성 검증"""
    messages = [
        SystemMessage(content=_prompt("coordinator")),
        HumanMessage(content=json.dumps(state["request"], ensure_ascii=False)),
    ]
    response = await coordinator_llm.ainvoke(messages)
    logger.info("[coordinator] %s", response.content[:80])
    return {
        "messages": state.get("messages", []) + [
            {"role": "coordinator", "content": response.content}
        ]
    }


async def planner_node(state: State) -> dict:
    """작업 전략 수립"""
    messages = [
        SystemMessage(content=_prompt("planner")),
        HumanMessage(content=json.dumps(state["request"], ensure_ascii=False)),
    ]
    response = await planner_llm.ainvoke(messages)
    logger.info("[planner] %s", response.content[:80])
    return {
        "messages": state["messages"] + [
            {"role": "planner", "content": response.content}
        ]
    }


async def supervisor_node(state: State) -> dict:
    """중앙 허브 — last_role을 보고 next_step을 결정한 뒤 LLM으로 이유를 생성"""
    msgs = state.get("messages", [])
    last_role = msgs[-1]["role"] if msgs else "planner"
    iteration = state.get("iteration", 0)
    status = state.get("status", "")
    violations = state.get("violations", [])

    # ── 규칙 기반 라우팅 결정 ──────────────────────────────────────────────────
    if last_role == "planner":
        next_step = "generation"
        situation = "작업 계획 완료. 약관 초안 생성을 시작합니다."

    elif last_role == "generation":
        next_step = "compliance"
        situation = f"초안 생성 완료 (iteration {iteration}). 법규 검증을 실행합니다."

    elif last_role == "compliance":
        if status == "PASS":
            next_step = "end"
            situation = "법규 준수 확인. 위반 없음 — 약관 초안을 최종본으로 확정합니다."
        elif iteration >= 3:
            next_step = "edit"
            situation = f"최대 반복({iteration}회) 도달. 잔여 위반항목 수동 검토 필요."
        else:
            next_step = "generation"
            situation = f"위반 {len(violations)}건 발견 (iteration {iteration}). 재생성합니다."

    elif last_role == "edit":
        next_step = "end"
        situation = "편집 완료. 워크플로우를 종료합니다."

    else:
        next_step = "generation"
        situation = "초기 상태. 약관 생성을 시작합니다."

    # ── MANUAL_REVIEW 상태 갱신 ───────────────────────────────────────────────
    updated_status = status
    if last_role == "compliance" and status == "FAIL" and iteration >= 3:
        updated_status = "MANUAL_REVIEW"

    # ── LLM 평가 코멘트 생성 ──────────────────────────────────────────────────
    ctx = {
        "last_action":      last_role,
        "situation":        situation,
        "next_step":        next_step,
        "iteration":        iteration,
        "violations_count": len(violations),
        "status":           updated_status,
    }
    llm_messages = [
        SystemMessage(content=_prompt("supervisor")),
        HumanMessage(content=json.dumps(ctx, ensure_ascii=False)),
    ]
    response = await supervisor_llm.ainvoke(llm_messages)
    logger.info("[supervisor] %s → next=%s", situation, next_step)

    extra: dict = {}
    if next_step == "end" and last_role == "compliance" and status == "PASS":
        extra["final_content"] = state.get("draft_content", "")

    return {
        "next_step":  next_step,
        "status":     updated_status,
        "messages":   msgs + [
            {"role": "supervisor", "content": f"[→{next_step.upper()}] {response.content}"}
        ],
        **extra,
    }


async def generation_node(state: State) -> dict:
    """약관 초안 생성 — GenerationAgent 재활용"""
    agent = _get_generation_agent()
    iteration = state.get("iteration", 0)

    if iteration == 0:
        result = await asyncio.to_thread(agent.generate, state["request"])
    else:
        violations = state.get("violations", [])
        priority_fixes = [
            f"{v.get('type', 'UNKNOWN')}: \"{v.get('original_text', '')[:80]}\" "
            f"→ {v.get('reason', v.get('regulation', ''))}"
            for v in violations[:5]
        ]
        feedback = {"priority_fixes": priority_fixes}
        result = await asyncio.to_thread(
            agent.regenerate, state["request"], feedback, iteration + 1
        )

    new_iter = iteration + 1
    logger.info("[generation] iteration=%d 완료", new_iter)
    return {
        "draft_content": result.get("content", ""),
        "iteration":     new_iter,
        "messages":      state["messages"] + [
            {"role": "generation", "content": f"초안 생성 완료 (iteration {new_iter})"}
        ],
    }


async def compliance_node(state: State) -> dict:
    """법규 준수 검증 — ComplianceAgent 재활용"""
    from compliance_agent.models.violation import DetectionInput, CoverageContext

    agent = _get_compliance_agent()
    coverage = state["request"].get("coverage_conditions", {})
    doc_req  = state["request"].get("document_request", {})
    session_id = state["request"].get("session_id", "langgraph-default")

    detection_input = DetectionInput(
        iteration=state["iteration"],
        section_type="약관",
        content=state["draft_content"],
        session_id=session_id,
        product_meta={"product_name": doc_req.get("product_name", "")},
        coverage_context=CoverageContext(
            coverage_limit=coverage.get("coverage_limit"),
            deductible_required=bool(coverage.get("deductible_rule")),
            three_major_noncovered_required=bool(
                coverage.get("three_major_noncovered_items")
            ),
            exclusions=coverage.get("noncovered_rider_items", []),
        ),
    )

    report = await asyncio.to_thread(agent.validate, detection_input)

    violations = [
        {
            "violation_id": v.violation_id,
            "type":         str(v.type.value) if hasattr(v.type, "value") else str(v.type),
            "severity":     str(v.severity.value) if hasattr(v.severity, "value") else str(v.severity),
            "original_text": v.original_text,
            "regulation":   v.regulation,
            "reason":       v.reason,
            "manual_flag":  v.manual_flag,
        }
        for v in report.violations
    ]
    status = "PASS" if report.status == "COMPLIANCE_PASSED" else "FAIL"
    logger.info("[compliance] status=%s violations=%d", status, len(violations))

    return {
        "violations": violations,
        "status":     status,
        "messages":   state["messages"] + [
            {"role": "compliance", "content": f"검증 완료: {status} (위반 {len(violations)}건)"}
        ],
    }


async def edit_node(state: State) -> dict:
    """위반 항목만 부분 수정 + 상품설명서 생성"""
    agent      = _get_generation_agent()
    violations = state.get("violations", [])
    draft      = state["draft_content"]

    if violations:
        # 위반 항목별 수정 지시서 구성
        fix_items = []
        for i, v in enumerate(violations, 1):
            fix_items.append(
                f"[수정 {i}]\n"
                f"- 위반 유형: {v.get('type', '')}\n"
                f"- 원문: \"{v.get('original_text', '')}\"\n"
                f"- 근거 법령: {v.get('regulation', '')}\n"
                f"- 수정 사유: {v.get('reason', '')}"
            )

        edit_prompt = (
            f"다음 약관에서 지정된 위반 항목만 최소한으로 수정하세요. "
            f"다른 내용은 절대 변경하지 마세요.\n\n"
            f"=== 약관 전문 ===\n{draft}\n\n"
            f"=== 수정 대상 ({len(violations)}건) ===\n"
            + "\n\n".join(fix_items)
        )
        llm_msgs = [
            SystemMessage(content=_prompt("edit")),
            HumanMessage(content=edit_prompt),
        ]
        response      = await edit_llm.ainvoke(llm_msgs)
        final_content = response.content
    else:
        # 위반 없음 — 원문 그대로 사용
        final_content = draft

    product_description = await asyncio.to_thread(
        agent.generate_product_description, final_content, state["request"]
    )

    logger.info("[edit] 부분 수정 완료 violations=%d", len(violations))
    return {
        "final_content":      final_content,
        "product_description": product_description,
        "messages": state["messages"] + [
            {
                "role": "edit",
                "content": f"부분 수정 완료 ({len(violations)}건) + 상품설명서 생성",
            }
        ],
    }


# ── 라우터 ────────────────────────────────────────────────────────────────────

def route_supervisor(state: State) -> Literal["generation", "compliance", "edit", "end"]:
    """supervisor가 state["next_step"]에 설정한 값을 그대로 반환"""
    return state.get("next_step", "generation")
