"""비동기 워크플로우 실행 및 결과 변환"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import AsyncGenerator, Optional
import os

import asyncio

from ..graph.builder import build_graph
from ..graph.types import State

logger = logging.getLogger(__name__)


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────

def _violations_to_ui(violations: list) -> list:
    """Violation dict → 프론트엔드 하이라이트 형식"""
    return [
        {
            "original_text": v.get("original_text", ""),
            "type":          v.get("type", ""),
            "legal_basis":   v.get("regulation", ""),
            "fix":           v.get("reason", ""),
        }
        for v in violations
    ]


def _build_suggestions(violations: list) -> list:
    """위반 항목 → 수동 검토 suggestions 목록"""
    return [
        {
            "severity":               v.get("severity", "MEDIUM"),
            "type":                   v.get("type", ""),
            "action":                 v.get("reason", ""),
            "target_text":            v.get("original_text", "")[:100],
            "requires_manual_review": v.get("manual_flag", False),
        }
        for v in violations
    ]


def _check_db_warning() -> Optional[str]:
    """DB 연결 불가 시 경고 메시지 반환"""
    if not os.getenv("DB_API_URL"):
        return "DB_API_URL 미설정 — MOCK 모드: 법률 DB 조회 없이 실행됩니다."
    return None


def _build_improvement_note(messages: list, iteration: int, status: str) -> str:
    """메시지 이력 → 사람이 읽기 쉬운 진행 요약"""
    compliance_results = [
        m["content"]
        for m in messages
        if m.get("role") == "compliance"
    ]
    if not compliance_results:
        return "워크플로우가 완료되었습니다."

    if status == "COMPLIANCE_PASSED":
        if iteration == 1:
            return "1회 생성 만에 법규 준수 완료."
        return f"{iteration}회 재생성 후 법규 준수 완료. ({' → '.join(compliance_results)})"

    if status == "MANUAL_REVIEW_REQUIRED":
        last = compliance_results[-1] if compliance_results else ""
        return f"최대 {iteration}회 도달 — 수동 검토 필요. 마지막 검증: {last}"

    return "워크플로우 완료."


# ── 결과 조립 헬퍼 ───────────────────────────────────────────────────────────

def _build_result(result: dict, db_warning: Optional[str]) -> dict:
    """최종 state → API 응답 dict 변환 (run_workflow / stream_workflow 공용).

    상품설명서·사업방법서는 edit_node가 이미 state에 담아 두므로
    여기서는 state에서 꺼내기만 한다. 별도 LLM 호출 없음.
    """
    raw_status  = result.get("status", "")
    iteration   = result.get("iteration", 0)
    violations  = result.get("violations", [])
    messages    = result.get("messages", [])

    # 약관: edit_node가 수정한 final_content 우선, 없으면 draft_content
    final_content       = result.get("final_content") or result.get("draft_content", "")
    # 상품설명서·사업방법서: edit_node에서 생성해서 state에 저장한 값 그대로 사용
    product_description = result.get("product_description", "")
    business_method     = result.get("business_method", "")

    # 상태명 정규화: nodes.py 의 raw 상태 → 프론트가 기대하는 API 상태명
    if raw_status == "PASS":
        api_status = "COMPLIANCE_PASSED"
    elif raw_status == "MANUAL_REVIEW_REQUIRED":
        api_status = "MANUAL_REVIEW_REQUIRED"
    else:
        api_status = "ORCHESTRATOR_ERROR"

    return {
        "status":              api_status,
        "content":             final_content,
        "iteration":           iteration,
        "violations_for_ui":   _violations_to_ui(violations),
        "suggestions":         _build_suggestions(violations) if api_status != "COMPLIANCE_PASSED" else [],
        "product_description": product_description,
        "business_method":     business_method,
        "improvement_note":    _build_improvement_note(messages, iteration, api_status),
        "db_warning":          db_warning,
    }


# ── 공통 초기 State ───────────────────────────────────────────────────────────

def _initial_state(request: dict) -> State:
    """워크플로우 시작 시 초기 State 생성."""
    return {
        "messages":            [],
        "request":             request,
        "draft_content":       "",
        "violations":          [],
        "iteration":           0,
        "final_content":       "",
        "product_description": "",
        "business_method":     "",
        "status":              "",   # supervisor가 첫 판단 전까지 빈 문자열
        "next_step":           "",
    }


# ── 메인 실행 함수 ────────────────────────────────────────────────────────────

async def run_workflow(request: dict) -> dict:
    """
    LangGraph 워크플로우를 비동기로 실행하고 API 응답 형식으로 반환.

    반환 키:
        status              - COMPLIANCE_PASSED | MANUAL_REVIEW_REQUIRED | ORCHESTRATOR_ERROR
        content             - 최종 약관 전문
        iteration           - 완료된 반복 횟수
        violations_for_ui   - 하이라이트용 위반 목록
        suggestions         - 수동 검토 항목 목록
        product_description - 상품설명서 (edit_node 생성)
        business_method     - 사업방법서 (edit_node 생성)
        improvement_note    - 진행 요약 메시지
        db_warning          - DB 미연결 경고 (없으면 null)
    """
    model_override: Optional[str] = request.get("model")
    db_warning = _check_db_warning()

    # Langfuse 세션 태그 설정
    try:
        from langfuse import Langfuse
        lf = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        lf.trace(
            name="insurance-policy-generation",
            session_id=request.get("session_id", ""),
            tags=[model_override or "upstage-solar", "pocat5"],
            metadata={"model": model_override or "upstage-solar"},
        )
        lf.flush()
        logger.info("[Langfuse] trace 생성 완료: model=%s", model_override or "upstage-solar")
    except Exception as e:
        logger.warning("[Langfuse] trace 생성 실패: %s", e)

    t0 = time.perf_counter()
    try:
        graph = build_graph(model_override=model_override)
        result = await graph.ainvoke(_initial_state(request))
    except Exception as exc:
        logger.exception("[workflow] 실행 중 예외 발생: %s", exc)
        return {
            "status":              "ORCHESTRATOR_ERROR",
            "content":             "",
            "iteration":           0,
            "violations_for_ui":   [],
            "suggestions":         [],
            "product_description": "",
            "business_method":     "",
            "improvement_note":    f"워크플로우 오류: {exc}",
            "db_warning":          db_warning,
            "error":               str(exc),
            "model_used":          model_override or "default",
        }

    elapsed = time.perf_counter() - t0
    output = _build_result(result, db_warning)
    logger.info(
        "[workflow] status=%s iteration=%d violations=%d elapsed=%.1fs",
        output["status"], output["iteration"],
        len(output["violations_for_ui"]), elapsed,
    )
    return output


# ── 스트리밍 실행 함수 ────────────────────────────────────────────────────────

async def stream_workflow(request: dict) -> AsyncGenerator[str, None]:
    """
    LangGraph 워크플로우를 SSE 형식으로 스트리밍.

    각 노드 완료 시 progress 이벤트를 emit하고,
    마지막에 result 이벤트(전체 결과)를 emit한다.
    """
    model_override: Optional[str] = request.get("model")
    db_warning = _check_db_warning()

    final_state = None
    try:
        graph = build_graph(model_override=model_override)
        async for snapshot in graph.astream(_initial_state(request), stream_mode="values"):
            final_state = snapshot
            msgs = snapshot.get("messages", [])
            last_msg = msgs[-1] if msgs else {}
            progress = {
                "type":      "progress",
                "node":      last_msg.get("role", ""),
                "status":    snapshot.get("status"),
                "iteration": snapshot.get("iteration", 0),
                "message":   last_msg.get("content", ""),
            }
            yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"

    except Exception as exc:
        logger.exception("[stream] 실행 중 예외: %s", exc)
        error_event = {"type": "error", "message": str(exc)}
        yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    if final_state is None:
        yield f"data: {json.dumps({'type': 'error', 'message': '워크플로우 결과 없음'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    result = _build_result(final_state, db_warning)
    yield f"data: {json.dumps({'type': 'result', **result}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"
