"""FastAPI 애플리케이션 — POST /generate, GET /health"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..service.workflow_service import run_workflow

logger = logging.getLogger(__name__)


# ── 수명주기 관리 ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PoCat API 서버 시작 (LangManus 아키텍처)")
    yield
    logger.info("PoCat API 서버 종료")


# ── FastAPI 앱 ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PoCat API",
    version="2.0.0",
    description="실손의료보험 약관 자동 생성 API (LangGraph 기반)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Streamlit 개발 서버 허용
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 요청/응답 모델 ────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    document_request:          dict
    product_design_conditions: dict
    coverage_conditions:       dict
    applicant_info:            dict
    session_id:                str = Field(default="", description="세션 ID (빈 값이면 서버에서 자동 생성)")


class ViolationUI(BaseModel):
    original_text: str
    type:          str
    legal_basis:   str
    fix:           str


class Suggestion(BaseModel):
    severity:               str
    type:                   str
    action:                 str
    target_text:            str
    requires_manual_review: bool


class GenerateResponse(BaseModel):
    status:              str  # COMPLIANCE_PASSED | MANUAL_REVIEW_REQUIRED | ORCHESTRATOR_ERROR
    content:             str
    iteration:           int
    violations_for_ui:   list[ViolationUI]
    suggestions:         list[Suggestion]
    product_description: str
    business_method:     str
    improvement_note:    str
    db_warning:          Optional[str] = None


# ── 미들웨어: 요청 ID 로깅 ─────────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    req_id = str(uuid.uuid4())[:8]
    logger.info("[%s] %s %s", req_id, request.method, request.url.path)
    response = await call_next(request)
    logger.info("[%s] 응답 %d", req_id, response.status_code)
    return response


# ── 전역 예외 핸들러 ──────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("처리되지 않은 예외: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"서버 내부 오류: {exc}"},
    )


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@app.post("/generate", response_model=GenerateResponse)
async def generate_clause(body: GenerateRequest):
    """
    보험 약관 초안 생성.

    LangGraph 워크플로우(coordinator → planner → supervisor 허브 → generation/compliance/edit)를
    실행하여 법규 준수 약관 초안, 상품설명서, 사업방법서를 반환합니다.
    """
    payload = body.model_dump()

    # session_id 자동 생성 (빈 값이면)
    if not payload.get("session_id"):
        payload["session_id"] = str(uuid.uuid4())
        logger.info("[generate] session_id 자동 생성: %s", payload["session_id"])

    # 기본 유효성: 기본보장종목 필수
    basic_items = payload.get("coverage_conditions", {}).get("basic_coverage_items", [])
    if not basic_items:
        raise HTTPException(
            status_code=400,
            detail="coverage_conditions.basic_coverage_items 에 하나 이상의 항목이 필요합니다.",
        )

    try:
        result = await run_workflow(payload)
    except Exception as exc:
        logger.exception("[generate] 워크플로우 실패: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return result


@app.get("/health")
async def health() -> dict[str, Any]:
    """서버 상태 확인"""
    return {"status": "ok", "version": "2.0.0"}
