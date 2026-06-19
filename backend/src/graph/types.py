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
