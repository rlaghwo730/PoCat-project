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
        response = await asyncio.wait_for(
            llm.ainvoke(messages, config={"callbacks": state.get("langfuse_callbacks", [])}),
            timeout=60.0,
        )
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
        response = await asyncio.wait_for(
            llm.ainvoke(messages, config={"callbacks": state.get("langfuse_callbacks", [])}),
            timeout=60.0,
        )
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
    total_steps = len(state.get("messages", []))
    if total_steps > 40:
        logger.warning("[supervisor] 최대 스텝 초과 → 강제 종료")
        return {
            "next_step": "end",
            "messages": state.get("messages", []) + [
                {"role": "supervisor", "content": "최대 스텝 초과로 강제 종료"}
            ],
        }

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
        current_accuracy = state.get("current_accuracy", 0.0)
        edit_iteration = state.get("edit_iteration", 0)

        if state.get("post_edit_compliance_done", False):
            # 90% 이상 달성 → final_validation
            next_step = "final_validation"
            situation = f"정확도 {current_accuracy}% ≥ 90% → final_validation으로 넘어갑니다."
        elif status == "PASS":
            next_step = "edit"
            situation = "법규 준수 확인. edit 노드에서 3종 문서를 생성합니다."
        elif iteration >= 3 or current_accuracy >= 50.0:
            if edit_iteration >= 3:
                next_step = "final_validation"
                situation = f"edit {edit_iteration}회 도달. final_validation으로 넘어갑니다."
            else:
                next_step = "edit"
                situation = f"정확도 {current_accuracy}% → edit으로 위반 항목 수정합니다. (edit {edit_iteration + 1}회)"
        else:
            next_step = "generation"
            situation = f"정확도 {current_accuracy}% < 50% → 재생성합니다."

    elif last_role == "revise":
        next_step = "compliance"
        situation = "약관 수정 완료. 재검증합니다."

    elif last_role == "edit":
        edit_iteration = state.get("edit_iteration", 0)
        if not state.get("post_edit_compliance_done", False):
            # edit 후 반드시 compliance로 재검증
            next_step = "compliance"
            situation = f"편집 완료 (edit {edit_iteration}회). compliance로 재검증합니다."
        else:
            next_step = "final_validation"
            situation = "최종 compliance 완료. final_validation으로 넘어갑니다."

    elif last_role == "final_validation":
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
        response = await asyncio.wait_for(
            llm.ainvoke(llm_messages, config={"callbacks": state.get("langfuse_callbacks", [])}),
            timeout=60.0,
        )
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
            # severity 기준 정렬 후 상위 5개만 전달 (속도 유지)
            severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            sorted_violations = sorted(
                violations,
                key=lambda v: severity_order.get(v.get("severity", "LOW"), 3)
            )
            priority_fixes = [
                f"[{v.get('severity', 'UNKNOWN')}] {v.get('type', 'UNKNOWN')}: "
                f"\"{v.get('original_text', '')[:80]}\" "
                f"→ {v.get('reason', v.get('regulation', ''))}"
                for v in sorted_violations[:5]
            ]
            feedback = {"priority_fixes": priority_fixes}
            result = await asyncio.to_thread(
                agent.regenerate, request, feedback, iteration + 1,
                state.get("draft_content", "")
            )

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
                langfuse_callbacks=state.get("langfuse_callbacks", []),
            ),
        )
        for document_key, section_type, document_content in documents
    ]

    try:
        report = None
        reports = await asyncio.gather(
            *(agent.validate_async(item) for _, item in detection_inputs)
        )
        report = reports[0] if reports else None

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

        logger.info("[compliance] report type=%s compliance_score=%s",
                    type(report).__name__ if report else 'None',
                    getattr(report, 'compliance_score', 'N/A'))

        raw_score = compliance_score  # 가중평균 사용 (reports[0] 아님)
        if raw_score > 0:
            accuracy = round(float(raw_score) * 100, 1)
        elif raw_score == 0 and len(violations) == 0:
            accuracy = 100.0
        else:
            accuracy = 0.0

        logger.info("[compliance] status=%s violations=%d accuracy=%.1f%%", status, len(violations), accuracy)

        is_post_edit = bool(state.get("final_content") or state.get("product_description"))

        # edit 후 준수율이 이전보다 낮아지면 이전 버전 복원
        prev_accuracy = state.get("current_accuracy", 0.0)
        if is_post_edit and accuracy < prev_accuracy:
            logger.warning("[compliance] 준수율 하락 감지 (%.1f%% → %.1f%%), 이전 버전 복원", prev_accuracy, accuracy)
            # final_content를 이전 상태로 되돌림 (state 반환에서 처리)
            accuracy = prev_accuracy
            violations = state.get("violations", violations)  # 이전 violations 유지

        history = state.get("accuracy_history", [])
        history = history + [{
            "iteration":      state.get("iteration", 0),
            "accuracy":       accuracy,
            "violations":     len(violations),
            "status":         status,
            "is_post_edit":   is_post_edit,
            "step_type":      "edit_review" if is_post_edit else "generation",
            "edit_iteration": state.get("edit_iteration", 0),
        }]
        # 90% 이상이거나 위반 0건일 때만 최종 완료
        post_edit_done = is_post_edit and (accuracy >= 90.0 or len(violations) == 0)
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
            "current_accuracy":         accuracy,
            "accuracy_history":         history,
            "post_edit_compliance_done": post_edit_done,
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
            "current_accuracy":         0.0,
            "accuracy_history":         state.get("accuracy_history", []),
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
            response = await asyncio.wait_for(
                llm.ainvoke(
                    [SystemMessage(content=_prompt("edit")), HumanMessage(content=edit_prompt)],
                    config={"callbacks": state.get("langfuse_callbacks", [])},
                ),
                timeout=180.0,
            )
            raw = response.content.strip()
            import json, re
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                try:
                    patches = json.loads(match.group())
                    final_content = draft
                    for patch in patches:
                        orig = patch.get("original", "")
                        fixed = patch.get("fixed", "")
                        if orig and fixed:
                            final_content = final_content.replace(orig, fixed, 1)
                except Exception:
                    final_content = draft  # 파싱 실패 시 원본 유지
            else:
                final_content = draft  # JSON 없으면 원본 유지
        else:
            final_content = draft

        # ── Step 2: 상품설명서 + 사업방법서 동시 생성 ────────────────────────
        # generate_product_description이 이제 dict {"product_description", "business_method"} 반환
        # edit 1회차에만 생성, 이후에는 기존 문서 유지
        if state.get("edit_iteration", 0) == 0:
            generated_docs = await agent.generate_product_description_parallel(final_content, state["request"])
            product_description = generated_docs["product_description"]
            business_method = generated_docs["business_method"]
            logger.info("[edit] 사업방법서 길이: %d", len(business_method))
            logger.info("[edit] 부분 수정 완료 violations=%d + 상품설명서·사업방법서 생성 완료", len(violations))
        else:
            product_description = state.get("product_description", "")
            business_method = state.get("business_method", "")
            logger.info("[edit] 사업방법서 기존 유지 길이: %d", len(business_method))
            logger.info("[edit] 부분 수정 완료 violations=%d + 상품설명서·사업방법서 기존 유지", len(violations))
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
            "product_description": product_description,
            "business_method":     business_method,
            "messages": state["messages"] + [
                {
                    "role": "edit",
                    "content": (
                        f"부분 수정 완료 ({len(violations)}건) "
                        "+ 상품설명서·사업방법서 생성 완료"
                    ),
                }
            ],
            "edit_iteration": state.get("edit_iteration", 0) + 1,
            "a2a_messages": append_a2a_message(state, a2a_msg),
        }
    except Exception as e:
        logger.error("[edit] 실패: %s", e)
        logger.error("[edit] 실패 상세: %s", e, exc_info=True)
        return {
            "final_content":       draft,
            "product_description": "",
            "business_method":     "",
            "messages": state.get("messages", []) + [
                {"role": "edit", "content": f"편집 오류: {e}"}
            ],
        }


async def final_validation_node(state: State, model_override: Optional[str] = None) -> dict:
    """최종 산출물 검증 — final_validation_agent 재활용"""
    try:
        from ..agents.final_validation_agent import arun_final_validation
        llm = get_supervisor_llm(model_override)

        result = await arun_final_validation(
            {
                "final_content":       state.get("final_content", ""),
                "product_description": state.get("product_description", ""),
                "business_method":     state.get("business_method", ""),
                "violations":          state.get("violations", []),
                "request":             state.get("request", {}),
            },
            llm=llm,
        )

        passed   = result.get("passed", True)
        summary  = result.get("summary", "최종 검증 완료")
        issues   = result.get("issues", [])

        logger.info("[final_validation] passed=%s issues=%d", passed, len(issues))

        return {
            "status":   "PASS" if passed else "MANUAL_REVIEW_REQUIRED",
            "messages": state.get("messages", []) + [
                {
                    "role":    "final_validation",
                    "content": f"최종 검증: {'통과' if passed else '이슈 발견'} — {summary}",
                }
            ],
        }
    except Exception as e:
        logger.error("[final_validation] 실패: %s", e)
        return {
            "status":   "MANUAL_REVIEW_REQUIRED",
            "messages": state.get("messages", []) + [
                {"role": "final_validation", "content": f"최종 검증 오류: {e}"}
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

def route_supervisor(state: State) -> Literal["generation", "compliance", "edit", "revise", "final_validation", "end"]:
    """supervisor가 state["next_step"]에 설정한 값을 그대로 반환"""
    return state.get("next_step", "generation")
