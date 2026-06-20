"""LangGraph 노드 함수 정의

플로우 (AI 생성 모드):
  START → coordinator → planner → supervisor(허브)
  supervisor → generation → supervisor
  supervisor → compliance → supervisor
  supervisor → edit → supervisor
  supervisor → END

플로우 (사용자 작성 약관 검증·수정 모드, request.user_document 존재 시):
  START → coordinator → planner → supervisor(허브)
  supervisor → compliance → supervisor   (generation 건너뜀)
  supervisor → revise → supervisor       (compliance FAIL 시 위반만 수정, 반복)
  supervisor → END                       (PASS 또는 최대 반복 도달 시, 약관만 출력)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from .types import State
from ..agents.agents import get_coordinator_llm, get_planner_llm, get_supervisor_llm, get_edit_llm
# ── A2A 보조 레이어 ───────────────────────────────────────────────────────────
# 기존 라우팅(builder.py의 edge)은 그대로 두고, 노드 간 전달 내용을
# 표준 A2A 메시지로 기록하기 위한 helper. 실행 흐름에는 영향을 주지 않는다.
from ..A2A import create_a2a_message, append_a2a_message, A2AStatus

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


# ── 지연 초기화 ───────────────────────────────────────────────────────────────

_generation_agent = None
_compliance_agent = None
_langfuse_handler = None


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


def _get_langfuse_handler():
    global _langfuse_handler
    if _langfuse_handler is None:
        from langfuse.langchain import CallbackHandler
        _langfuse_handler = CallbackHandler()
    return _langfuse_handler


# ── 노드 함수 ─────────────────────────────────────────────────────────────────

async def coordinator_node(state: State, model_override: Optional[str] = None) -> dict:
    """요청 분석 및 유효성 검증"""
    llm = get_coordinator_llm(model_override)
    messages = [
        SystemMessage(content=_prompt("coordinator")),
        HumanMessage(content=json.dumps(state["request"], ensure_ascii=False)),
    ]
    try:
        response = await llm.ainvoke(messages, config={"callbacks": state.get("langfuse_callbacks", [])})
        logger.info("[coordinator] %s", response.content[:80])
        # ── A2A: coordinator → planner (요청 검증 완료를 planner에 전달) ──────
        a2a_msg = create_a2a_message(
            sender="coordinator", receiver="planner",
            task="작업 계획 수립 요청",
            status=A2AStatus.REQUEST_VALIDATED,
            payload={"summary": "사용자 요청 분석 및 유효성 검증 완료"},
        )
        return {
            "messages": state.get("messages", []) + [
                {"role": "coordinator", "content": response.content}
            ],
            "a2a_messages": append_a2a_message(state, a2a_msg),
        }
    except Exception as e:
        logger.error("[coordinator] 실패: %s", e)
        return {
            "messages": state.get("messages", []) + [
                {"role": "coordinator", "content": f"coordinator 오류: {e}"}
            ]
        }


async def planner_node(state: State, model_override: Optional[str] = None) -> dict:
    """작업 전략 수립"""
    llm = get_planner_llm(model_override)
    messages = [
        SystemMessage(content=_prompt("planner")),
        HumanMessage(content=json.dumps(state["request"], ensure_ascii=False)),
    ]
    try:
        response = await llm.ainvoke(messages, config={"callbacks": state.get("langfuse_callbacks", [])})
        logger.info("[planner] %s", response.content[:80])
        # ── A2A: planner → supervisor (수립한 계획을 허브에 전달) ─────────────
        a2a_msg = create_a2a_message(
            sender="planner", receiver="supervisor",
            task="작업 계획 전달 및 라우팅 요청",
            status=A2AStatus.PLAN_READY,
            payload={"summary": "약관 생성 작업 전략 수립 완료"},
        )
        return {
            "messages": state["messages"] + [
                {"role": "planner", "content": response.content}
            ],
            "a2a_messages": append_a2a_message(state, a2a_msg),
        }
    except Exception as e:
        logger.error("[planner] 실패: %s", e)
        return {
            "messages": state.get("messages", []) + [
                {"role": "planner", "content": f"planner 오류: {e}"}
            ]
        }


async def supervisor_node(state: State, model_override: Optional[str] = None) -> dict:
    """중앙 허브 — last_role을 보고 next_step을 결정한 뒤 LLM으로 이유를 생성"""
    msgs = state.get("messages", [])
    last_role = msgs[-1]["role"] if msgs else "planner"
    iteration = state.get("iteration", 0)
    status = state.get("status", "")
    violations = state.get("violations", [])
    is_revise_mode = bool(state["request"].get("user_document"))
    compliance_next_action = state.get("compliance_next_action", "")
    extra: dict = {}

    # ── 규칙 기반 라우팅 결정 ──────────────────────────────────────────────────
    if last_role == "planner":
        if is_revise_mode:
            next_step = "compliance"
            situation = "사용자 작성 약관 확인. 생성 단계를 건너뛰고 법규 검증을 시작합니다."
        else:
            next_step = "generation"
            situation = "작업 계획 완료. 약관 초안 생성을 시작합니다."

    elif last_role == "generation":
        next_step = "compliance"
        situation = f"초안 생성 완료 (iteration {iteration}). 법규 검증을 실행합니다."

    elif last_role == "compliance":
        if is_revise_mode:
            # 사용자 작성 약관 모드: generation/edit을 타지 않으므로 compliance_next_action도
            # 여기서 직접 종료 조건으로 반영한다 (post_edit_compliance_done은 edit을 거치지
            # 않으므로 해당 없음).
            if status == "PASS":
                next_step = "end"
                extra["final_content"] = state["draft_content"]
                situation = "법규 준수 확인. 위반 없음 — 최종 약관을 출력합니다."
            elif (
                iteration >= 3
                or compliance_next_action.startswith("GENERATOR_FAILURE")
                or compliance_next_action == "MANUAL_REVIEW_REQUIRED"
            ):
                next_step = "end"
                extra["final_content"] = state["draft_content"]
                situation = f"최대 반복({iteration}회) 도달 또는 수동 검토 필요 — 최종 약관을 출력합니다."
            else:
                next_step = "revise"
                situation = f"위반 {len(violations)}건 발견 (iteration {iteration}). 약관을 수정합니다."
        elif state.get("post_edit_compliance_done", False):
            # 최종 검증 후 종료하되 실패는 수동 검토 상태로 보존한다.
            next_step = "end"
            situation = (
                "최종 검증 통과. 워크플로우를 종료합니다."
                if status == "PASS"
                else "최종 검증에서 위반이 남아 수동 검토 상태로 종료합니다."
            )
        elif compliance_next_action.startswith("GENERATOR_FAILURE"):
            next_step = "end"
            situation = "생성 결과가 수렴하지 않아 수동 검토 상태로 종료합니다."
        elif compliance_next_action == "MANUAL_REVIEW_REQUIRED":
            next_step = "end"
            situation = "최대 검증 횟수에 도달해 수동 검토 상태로 종료합니다."
        elif status == "PASS":
            next_step = "edit"
            situation = "법규 준수 확인. edit 노드에서 3종 문서를 생성합니다."
        elif iteration >= 3:
            next_step = "edit"
            situation = f"최대 반복({iteration}회) 도달. edit 노드에서 나머지 문서를 생성합니다."
        else:
            next_step = "generation"
            situation = f"위반 {len(violations)}건 발견 (iteration {iteration}). 재생성합니다."

    elif last_role == "revise":
        next_step = "compliance"
        situation = "약관 수정 완료. 재검증합니다."

    elif last_role == "edit":
        if not state.get("post_edit_compliance_done", False):
            next_step = "compliance"
            situation = "편집 완료. 3종 문서(약관+상품설명서+사업방법서) 최종 검증을 실행합니다."
        else:
            next_step = "end"
            situation = "최종 검증 완료. 워크플로우를 종료합니다."

    else:
        next_step = "compliance" if is_revise_mode else "generation"
        situation = "초기 상태. 검증을 시작합니다." if is_revise_mode else "초기 상태. 약관 생성을 시작합니다."

    # ── MANUAL_REVIEW_REQUIRED 상태 갱신 ─────────────────────────────────────
    updated_status = status
    if last_role == "compliance" and status == "FAIL" and (
        iteration >= 3
        or state.get("post_edit_compliance_done", False)
        or compliance_next_action.startswith("GENERATOR_FAILURE")
        or compliance_next_action == "MANUAL_REVIEW_REQUIRED"
    ):
        updated_status = "MANUAL_REVIEW_REQUIRED"

    # ── LLM 평가 코멘트 생성 ──────────────────────────────────────────────────
    ctx = {
        "last_action":      last_role,
        "situation":        situation,
        "next_step":        next_step,
        "iteration":        iteration,
        "violations_count": len(violations),
        "status":           updated_status,
    }
    llm = get_supervisor_llm(model_override)
    llm_messages = [
        SystemMessage(content=_prompt("supervisor")),
        HumanMessage(content=json.dumps(ctx, ensure_ascii=False)),
    ]
    try:
        response = await llm.ainvoke(llm_messages, config={"callbacks": state.get("langfuse_callbacks", [])})
        logger.info("[supervisor] %s → next=%s", situation, next_step)
        supervisor_comment = f"[→{next_step.upper()}] {response.content}"
    except Exception as e:
        logger.error("[supervisor] LLM 실패: %s", e)
        supervisor_comment = f"[→{next_step.upper()}] supervisor 오류: {e}"

    # ── A2A: supervisor → (next_step) 분기 결정을 메시지로 기록 ──────────────
    # supervisor는 허브라 receiver가 매번 달라진다. next_step을 그대로 receiver로 쓴다.
    a2a_receiver = "END" if next_step == "end" else next_step
    a2a_status = A2AStatus.WORKFLOW_END if next_step == "end" else A2AStatus.ROUTING
    a2a_msg = create_a2a_message(
        sender="supervisor", receiver=a2a_receiver,
        task=situation,
        status=a2a_status,
        payload={"next_step": next_step, "decided_status": updated_status},
        metadata={"iteration": iteration, "violations_count": len(violations)},
    )

    return {
        "next_step":  next_step,
        "status":     updated_status,
        "messages":   msgs + [{"role": "supervisor", "content": supervisor_comment}],
        "a2a_messages": append_a2a_message(state, a2a_msg),
        **extra,
    }


async def generation_node(state: State, model_override: Optional[str] = None) -> dict:
    """약관 초안 생성 — GenerationAgent 재활용"""
    agent = _get_generation_agent()
    iteration = state.get("iteration", 0)

    try:
        handler = _get_langfuse_handler()
        request = {**state["request"], "model": model_override}

        if iteration == 0:
            result = await asyncio.to_thread(agent.generate, request)
        else:
            violations = state.get("violations", [])
            priority_fixes = [
                f"{v.get('type', 'UNKNOWN')}: \"{v.get('original_text', '')[:80]}\" "
                f"→ {v.get('reason', v.get('regulation', ''))}"
                for v in violations[:5]
            ]
            feedback = {"priority_fixes": priority_fixes}
            result = await asyncio.to_thread(agent.regenerate, request, feedback, iteration + 1)

        new_iter = iteration + 1
        logger.info("[generation] iteration=%d model=%s 완료", new_iter, model_override or "default")
        # ── A2A: generation → compliance (생성한 초안 검토 요청) ─────────────
        a2a_msg = create_a2a_message(
            sender="generation", receiver="compliance",
            task="약관 초안 검토 요청",
            status=A2AStatus.DRAFT_GENERATED,
            payload={"summary": "약관 초안 생성 완료"},
            metadata={"iteration": new_iter},
        )
        return {
            "draft_content": result.get("content", ""),
            "iteration": new_iter,
            "messages": state["messages"] + [
                {"role": "generation", "content": f"초안 생성 완료 (iteration {new_iter}, model={model_override or 'default'})"}
            ],
            "a2a_messages": append_a2a_message(state, a2a_msg),
        }
    except Exception as e:
        logger.error("[generation] 실패: %s", e)
        return {
            "draft_content": state.get("draft_content", ""),
            "iteration": iteration + 1,
            "messages": state.get("messages", []) + [
                {"role": "generation", "content": f"생성 오류: {e}"}
            ],
        }


async def compliance_node(state: State, model_override: Optional[str] = None) -> dict:
    """법규 준수 검증 — ComplianceAgent 재활용"""
    from compliance_agent.models.violation import DetectionInput, CoverageContext

    agent = _get_compliance_agent()
    coverage = state["request"].get("coverage_conditions", {})
    doc_req  = state["request"].get("document_request", {})
    session_id = state["request"].get("session_id", "langgraph-default")

    # 문서를 합치면 한 문서의 키워드가 다른 문서의 필수항목 누락을 가리므로
    # section_type별로 독립 검증한다.
    documents = []
    if state.get("final_content"):
        documents.append(("terms", "약관", state["final_content"]))
    elif state.get("draft_content"):
        documents.append(("terms", "약관", state["draft_content"]))
    if state.get("product_description"):
        documents.append(
            ("product_description", "상품설명서", state["product_description"])
        )
    if state.get("business_method"):
        documents.append(("business_method", "사업방법서", state["business_method"]))

    terms_coverage_context = CoverageContext(
        coverage_limit=coverage.get("coverage_limit"),
        deductible_required=bool(coverage.get("deductible_rule")),
        three_major_noncovered_required=bool(
            coverage.get("three_major_noncovered_items")
        ),
        exclusions=coverage.get("noncovered_rider_items", []),
    )
    product_coverage_context = CoverageContext(
        coverage_limit=coverage.get("coverage_limit"),
        deductible_required=bool(coverage.get("deductible_rule")),
        three_major_noncovered_required=bool(
            coverage.get("three_major_noncovered_items")
        ),
        exclusions=coverage.get("noncovered_rider_items", []),
    )
    coverage_by_section = {
        "약관": terms_coverage_context,
        "상품설명서": product_coverage_context,
        # 사업방법서에는 약관 필수기재 규칙을 적용하지 않는다.
        "사업방법서": None,
    }
    detection_inputs = [
        (
            document_key,
            DetectionInput(
                iteration=state["iteration"],
                section_type=section_type,
                content=document_content,
                session_id=f"{session_id}:{document_key}",
                product_meta={"product_name": doc_req.get("product_name", "")},
                coverage_context=coverage_by_section[section_type],
                model_override=model_override,
            ),
        )
        for document_key, section_type, document_content in documents
    ]

    try:
        reports = await asyncio.gather(
            *(agent.validate_async(item) for _, item in detection_inputs)
        )

        violations = [
            {
                "violation_id": f"{document_key}:{v.violation_id}",
                "document_type": document_key,
                "type":         str(v.type.value) if hasattr(v.type, "value") else str(v.type),
                "severity":     str(v.severity.value) if hasattr(v.severity, "value") else str(v.severity),
                "original_text": v.original_text,
                "regulation":   v.regulation,
                "reason":       v.reason,
                "manual_flag":  v.manual_flag,
            }
            for (document_key, _), report in zip(detection_inputs, reports)
            for v in report.violations
        ]
        status = (
            "PASS"
            if reports and all(r.status == "COMPLIANCE_PASSED" for r in reports)
            else "FAIL"
        )
        document_scores = {
            document_key: {
                "section_type": item.section_type,
                "status": report.status,
                "compliance_score": round(report.compliance_score, 4),
                "compliance_score_pct": round(report.compliance_score * 100, 1),
            }
            for (document_key, item), report in zip(detection_inputs, reports)
        }
        total_length = sum(len(item.content) for _, item in detection_inputs)
        if total_length:
            compliance_score = sum(
                report.compliance_score * len(item.content)
                for (_, item), report in zip(detection_inputs, reports)
            ) / total_length
        else:
            compliance_score = 0.0

        next_actions = [report.next_action for report in reports if report.next_action]
        if any(a.startswith("GENERATOR_FAILURE") for a in next_actions):
            compliance_next_action = "GENERATOR_FAILURE"
        elif "MANUAL_REVIEW_REQUIRED" in next_actions:
            compliance_next_action = "MANUAL_REVIEW_REQUIRED"
        elif status == "FAIL":
            compliance_next_action = "REGENERATE"
        elif "THRESHOLD_PASSED" in next_actions:
            compliance_next_action = "THRESHOLD_PASSED"
        else:
            compliance_next_action = "READY_FOR_DELIVERY"

        logger.info("[compliance] status=%s violations=%d", status, len(violations))

        is_post_edit = bool(state.get("final_content") or state.get("product_description"))
        # ── A2A: compliance → supervisor (검증 결과 보고, 다음 분기는 supervisor가 결정) ──
        a2a_msg = create_a2a_message(
            sender="compliance", receiver="supervisor",
            task="법규 검증 결과 보고",
            status=(A2AStatus.COMPLIANCE_PASSED if status == "PASS"
                    else A2AStatus.COMPLIANCE_FAILED),
            payload={
                "summary": f"검증 {status} / 위반 {len(violations)}건",
                "compliance_next_action": compliance_next_action,
            },
            metadata={"iteration": state["iteration"], "violations_count": len(violations)},
        )
        return {
            "violations":               violations,
            "status":                   status,
            "compliance_next_action":   compliance_next_action,
            "compliance_score":         round(compliance_score, 4),
            "compliance_score_pct":     round(compliance_score * 100, 1),
            "document_compliance_scores": document_scores,
            "post_edit_compliance_done": is_post_edit,
            "messages":                 state["messages"] + [
                {
                    "role": "compliance",
                    "content": (
                        f"검증 완료: {status} / 준수율 {compliance_score * 100:.1f}% "
                        f"(위반 {len(violations)}건)"
                    ),
                }
            ],
            "a2a_messages":             append_a2a_message(state, a2a_msg),
        }

    except Exception as e:
        logger.error("[compliance] 검증 실패: %s", e)
        return {
            "violations":               [],
            "status":                   "ERROR",
            "compliance_next_action":   "ERROR",
            "compliance_score":         0.0,
            "compliance_score_pct":     0.0,
            "document_compliance_scores": {},
            "post_edit_compliance_done": False,
            "messages":                 state["messages"] + [
                {"role": "compliance", "content": f"검증 오류 발생: {e}"}
            ],
        }


def _build_fix_prompt(draft: str, violations: list) -> str:
    """위반 항목 부분 수정 프롬프트 — edit_node, revise_node 공용."""
    fix_items = []
    for i, v in enumerate(violations, 1):
        fix_items.append(
            f"[수정 {i}]\n"
            f"- 위반 유형: {v.get('type', '')}\n"
            f"- 원문: \"{v.get('original_text', '')}\"\n"
            f"- 근거 법령: {v.get('regulation', '')}\n"
            f"- 수정 사유: {v.get('reason', '')}"
        )
    return (
        f"다음 약관에서 지정된 위반 항목만 최소한으로 수정하세요. "
        f"다른 내용은 절대 변경하지 마세요.\n\n"
        f"=== 약관 전문 ===\n{draft}\n\n"
        f"=== 수정 대상 ({len(violations)}건) ===\n"
        + "\n\n".join(fix_items)
    )


async def edit_node(state: State, model_override: Optional[str] = None) -> dict:
    """위반 항목만 부분 수정 + 상품설명서·사업방법서 동시 생성"""
    llm        = get_edit_llm(model_override)
    agent      = _get_generation_agent()
    violations = state.get("violations", [])
    draft      = state["draft_content"]

    try:
        # ── Step 1: 약관 위반 항목 부분 수정 ──────────────────────────────────
        if violations:
            edit_prompt   = _build_fix_prompt(draft, violations)
            response      = await llm.ainvoke(
                [SystemMessage(content=_prompt("edit")), HumanMessage(content=edit_prompt)],
                config={"callbacks": state.get("langfuse_callbacks", [])},
            )
            final_content = response.content
        else:
            final_content = draft

        # ── Step 2: 상품설명서 + 사업방법서 동시 생성 ────────────────────────
        # generate_product_description이 이제 dict {"product_description", "business_method"} 반환
        generated_docs = await asyncio.to_thread(
            agent.generate_product_description, final_content, state["request"]
        )

        logger.info("[edit] 부분 수정 완료 violations=%d + 상품설명서·사업방법서 생성 완료", len(violations))
        # ── A2A: edit → supervisor (3종 문서 완성 보고, 최종 검증/종료는 supervisor가 결정) ──
        a2a_msg = create_a2a_message(
            sender="edit", receiver="supervisor",
            task="편집 및 3종 문서 생성 완료 보고",
            status=A2AStatus.EDIT_DONE,
            payload={"summary": f"약관 부분 수정({len(violations)}건) + 상품설명서·사업방법서 생성 완료"},
            metadata={"iteration": state.get("iteration", 0)},
        )
        return {
            "final_content":       final_content,
            "product_description": generated_docs["product_description"],
            "business_method":     generated_docs["business_method"],
            "messages": state["messages"] + [
                {
                    "role": "edit",
                    "content": (
                        f"부분 수정 완료 ({len(violations)}건) "
                        "+ 상품설명서·사업방법서 생성 완료"
                    ),
                }
            ],
            "a2a_messages": append_a2a_message(state, a2a_msg),
        }
    except Exception as e:
        logger.error("[edit] 실패: %s", e)
        return {
            "final_content":       draft,
            "product_description": "",
            "business_method":     "",
            "messages": state.get("messages", []) + [
                {"role": "edit", "content": f"편집 오류: {e}"}
            ],
        }


async def revise_node(state: State, model_override: Optional[str] = None) -> dict:
    """검증-수정 반복 전용 노드 (사용자 작성 약관 모드).

    edit_node와 달리 위반 항목만 수정하고 상품설명서·사업방법서는 생성하지 않은 채
    재검증을 위해 supervisor → compliance로 되돌아간다.
    """
    llm        = get_edit_llm(model_override)
    violations = state.get("violations", [])
    draft      = state["draft_content"]
    iteration  = state.get("iteration", 0)

    if not violations:
        return {
            "draft_content": draft,
            "iteration": iteration + 1,
            "messages": state["messages"] + [
                {"role": "revise", "content": "수정 대상 없음"}
            ],
        }

    try:
        edit_prompt = _build_fix_prompt(draft, violations)
        response = await llm.ainvoke(
            [SystemMessage(content=_prompt("edit")), HumanMessage(content=edit_prompt)],
            config={"callbacks": state.get("langfuse_callbacks", [])},
        )
        logger.info("[revise] 수정 완료 violations=%d", len(violations))
        return {
            "draft_content": response.content,
            "iteration": iteration + 1,
            "messages": state["messages"] + [
                {"role": "revise", "content": f"수정 완료 ({len(violations)}건)"}
            ],
        }
    except Exception as e:
        logger.error("[revise] 실패: %s", e)
        return {
            "draft_content": draft,
            "iteration": iteration + 1,
            "messages": state.get("messages", []) + [
                {"role": "revise", "content": f"수정 오류: {e}"}
            ],
        }


# ── 라우터 ────────────────────────────────────────────────────────────────────

def route_supervisor(state: State) -> Literal["generation", "compliance", "edit", "revise", "end"]:
    """supervisor가 state["next_step"]에 설정한 값을 그대로 반환"""
    return state.get("next_step", "generation")
