"""비동기 워크플로우 실행 및 결과 변환"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import asyncio

from ..graph.builder import workflow
from ..graph.nodes import _get_generation_agent
from ..graph.types import State

logger = logging.getLogger(__name__)

# PoCat-project 루트: backend/src/service/workflow_service.py 기준 4단계 상위
_ROOT = Path(__file__).parent.parent.parent.parent


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────

def _load_business_method(request: dict) -> str:
    """사업방법서 JSON에서 해당 보험사 청크 반환"""
    data_path = _ROOT / "generation_agent" / "data" / "일반_사업방법서_3사통합.json"
    if not data_path.exists():
        logger.warning("[workflow] 사업방법서 데이터 파일 없음: %s", data_path)
        return "사업방법서 데이터 파일을 찾을 수 없습니다."
    try:
        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)
        company = request.get("document_request", {}).get("insurance_company", "삼성화재")
        chunks = [
            item["page_content"]
            for item in data
            if item.get("metadata", {}).get("company") == company
        ]
        if not chunks:
            chunks = [item["page_content"] for item in data]
        return "\n\n".join(chunks)
    except Exception as e:
        logger.error("[workflow] 사업방법서 로드 실패: %s", e)
        return f"사업방법서 로드 오류: {e}"


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


# ── 메인 실행 함수 ────────────────────────────────────────────────────────────

async def run_workflow(request: dict) -> dict:
    """
    LangGraph 워크플로우를 비동기로 실행하고 API 응답 형식으로 변환하여 반환.

    반환 키:
        status            - COMPLIANCE_PASSED | MANUAL_REVIEW_REQUIRED | ORCHESTRATOR_ERROR
        content           - 최종 약관 전문 (final_content)
        iteration         - 완료된 반복 횟수
        violations_for_ui - 하이라이트용 위반 목록
        suggestions       - 수동 검토 항목 목록
        product_description - 상품설명서 텍스트
        business_method   - 사업방법서 텍스트
        improvement_note  - 진행 요약 메시지
        db_warning        - DB 미연결 경고 (없으면 null)
    """
    db_warning = _check_db_warning()

    # ── State 초기값 ──────────────────────────────────────────────────────────
    initial_state: State = {
        "messages":           [],
        "request":            request,
        "draft_content":      "",
        "violations":         [],
        "iteration":          0,
        "final_content":      "",
        "product_description": "",
        "business_method":    "",
        "status":             "PASS",
        "next_step":          "",
    }

    # ── 그래프 실행 ───────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        result = await workflow.ainvoke(initial_state)
    except Exception as exc:
        logger.exception("[workflow] 실행 중 예외 발생: %s", exc)
        return {
            "status":             "ORCHESTRATOR_ERROR",
            "content":            "",
            "iteration":          0,
            "violations_for_ui":  [],
            "suggestions":        [],
            "product_description": "",
            "business_method":    _load_business_method(request),
            "improvement_note":   f"워크플로우 오류: {exc}",
            "db_warning":         db_warning,
            "error":              str(exc),
        }

    elapsed = time.perf_counter() - t0
    logger.info("[workflow] 완료 (%.1fs)", elapsed)

    # ── 결과 추출 ─────────────────────────────────────────────────────────────
    raw_status  = result.get("status", "PASS")
    iteration   = result.get("iteration", 0)
    violations  = result.get("violations", [])
    messages    = result.get("messages", [])

    # final_content가 없으면 draft_content로 대체 (PASS→end 경로에서 supervisor가 설정)
    final_content = result.get("final_content") or result.get("draft_content", "")

    # PASS 경로(edit_node 미실행)일 때 product_description 보완 생성
    product_description = result.get("product_description", "")
    if not product_description and final_content:
        try:
            agent = _get_generation_agent()
            product_description = await asyncio.to_thread(
                agent.generate_product_description, final_content, request
            )
        except Exception as pd_exc:
            logger.warning("[workflow] product_description 생성 실패: %s", pd_exc)
            product_description = ""

    # 상태 매핑
    if raw_status == "PASS":
        api_status = "COMPLIANCE_PASSED"
    elif raw_status == "MANUAL_REVIEW":
        api_status = "MANUAL_REVIEW_REQUIRED"
    else:
        api_status = "ORCHESTRATOR_ERROR"

    improvement_note = _build_improvement_note(messages, iteration, api_status)
    business_method  = _load_business_method(request)

    logger.info(
        "[workflow] status=%s iteration=%d violations=%d elapsed=%.1fs",
        api_status, iteration, len(violations), elapsed,
    )

    return {
        "status":             api_status,
        "content":            final_content,
        "iteration":          iteration,
        "violations_for_ui":  _violations_to_ui(violations),
        "suggestions":        _build_suggestions(violations) if api_status != "COMPLIANCE_PASSED" else [],
        "product_description": product_description,
        "business_method":    business_method,
        "improvement_note":   improvement_note,
        "db_warning":         db_warning,
    }
