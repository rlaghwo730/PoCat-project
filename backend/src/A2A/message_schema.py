"""A2A(Agent-to-Agent) 메시지 스키마

이 파일은 LangGraph 라우팅을 '대체'하지 않는다.
기존 흐름(coordinator → planner → supervisor → generation → compliance → edit)은
그대로 두고, 각 노드가 '누가 누구에게 무엇을 넘겼는지'를 표준 메시지로 기록하기 위한
보조 레이어다. 즉 관찰/로깅 목적의 메시지 포맷 정의일 뿐이다.

메시지 형식 (요청받은 단순 구조 그대로):
    {
        "sender":   "generation",            # 보낸 노드
        "receiver": "compliance",            # 받을 노드
        "task":     "약관 초안 검토 요청",     # 무엇을 요청/전달하는지(사람이 읽는 한 줄)
        "status":   "DRAFT_GENERATED",       # 단계 상태 코드
        "payload":  {"summary": "..."},      # 노드가 넘기는 핵심 내용 요약
        "metadata": {"iteration": 1, "timestamp": "..."},
    }
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict


# ── 타입 정의 (문서화 목적) ───────────────────────────────────────────────────
# TypedDict 는 런타임 강제력이 없는 '형태 설명'이다. 실제 생성은 아래 함수로 한다.

class A2AMessage(TypedDict):
    sender: str
    receiver: str
    task: str
    status: str
    payload: dict
    metadata: dict


# ── 상태 코드 상수 (오타 방지용) ──────────────────────────────────────────────
# 문자열을 직접 적어도 되지만, 상수로 두면 노드에서 일관되게 쓸 수 있다.

class A2AStatus:
    REQUEST_VALIDATED   = "REQUEST_VALIDATED"    # coordinator 완료
    PLAN_READY          = "PLAN_READY"           # planner 완료
    ROUTING             = "ROUTING"              # supervisor 분기 결정
    DRAFT_GENERATED     = "DRAFT_GENERATED"      # generation 완료
    COMPLIANCE_PASSED   = "COMPLIANCE_PASSED"    # compliance 통과
    COMPLIANCE_FAILED   = "COMPLIANCE_FAILED"    # compliance 위반 발견
    EDIT_DONE           = "EDIT_DONE"            # edit 완료
    WORKFLOW_END        = "WORKFLOW_END"         # 종료
    ERROR               = "ERROR"                # 노드 내 오류
