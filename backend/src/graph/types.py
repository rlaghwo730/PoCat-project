from typing import TypedDict, Optional


class State(TypedDict):
    messages: list
    request: dict              # 사용자 입력 (약관 조건)
    draft_content: str         # 생성된 약관 초안
    violations: list           # Compliance 위반 항목
    iteration: int             # 현재 반복 횟수 (최대 3)
    final_content: str         # 최종 약관
    product_description: str   # 상품설명서
    business_method: str       # 사업방법서
    status: str                # PASS / FAIL / MANUAL_REVIEW
    next_step: str             # supervisor가 설정하는 다음 노드: generation/compliance/edit/end
    langfuse_callbacks: list          # Langfuse CallbackHandler 리스트
    post_edit_compliance_done: bool   # edit 후 compliance 완료 여부
    compliance_next_action: str       # ComplianceAgent가 결정한 후속 조치
    compliance_score: float           # 종합 준수율 (0.0~1.0)
    compliance_score_pct: float       # 종합 준수율 백분율 (0.0~100.0)
    document_compliance_scores: dict  # 문서별 준수율과 상태
    current_accuracy: float           # 현재 compliance 준수율 (룰 기반)
    accuracy_history: list            # iteration별 준수율 히스토리

    # ── A2A(Agent-to-Agent) 보조 레이어 ──────────────────────────────────────
    # 노드 간 전달 내용을 표준 메시지로 누적 기록하는 로그성 필드.
    # 기존 messages 와 동일하게 '전체 리스트 통째 반환' 방식으로 갱신하므로
    # 별도의 LangGraph 리듀서(Annotated) 어노테이션이 필요 없다.
    edit_iteration: int                # edit 반복 횟수
    a2a_messages: list[dict]          # A2A 메시지 목록 (관찰/로깅용)
