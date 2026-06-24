# 시퀀스 다이어그램

**시스템명**: PoCat — 실손의료보험 약관 자동 생성 시스템  
**버전**: 2.0.0  
**작성일**: 2026-06-20  
**소스**: `backend/src/graph/nodes.py`, `backend/src/graph/builder.py`, `backend/src/service/workflow_service.py`

---

## 1. 정상 흐름 (Compliance PASS)

약관 초안이 1회 생성 후 법규 검증을 통과하여 최종 3종 문서가 완성되는 시나리오.

```mermaid
sequenceDiagram
    actor 담당자 as 보험사 담당자
    participant FE as Frontend<br/>(Streamlit)
    participant API as Backend<br/>(FastAPI)
    participant WF as workflow_service
    participant COORD as coordinator
    participant PLAN as planner
    participant SUP as supervisor
    participant GEN as generation
    participant COMP as compliance
    participant EDIT as edit
    participant FV as final_validation
    participant LLM as 외부 LLM<br/>(OpenRouter)
    participant RAG as ChromaDB<br/>(RAG)

    담당자->>FE: 상품 조건 입력
    FE->>API: POST /generate<br/>(GenerateRequest)
    API->>API: session_id 자동 생성<br/>basic_coverage_items 검증
    API->>WF: run_workflow(payload)
    WF->>WF: _initial_state() 구성<br/>Langfuse 핸들러 등록

    WF->>COORD: graph.ainvoke(initial_state)
    COORD->>LLM: ainvoke(coordinator_prompt)<br/>wait_for(timeout=60s)
    LLM-->>COORD: 요청 분석 결과
    COORD-->>SUP: messages에 coordinator 결과 추가

    SUP->>PLAN: (자동 edge)
    PLAN->>LLM: ainvoke(planner_prompt)<br/>wait_for(timeout=60s)
    LLM-->>PLAN: 작업 전략
    PLAN-->>SUP: messages에 planner 결과 추가

    Note over SUP: last_role=planner<br/>→ next_step=generation
    SUP->>LLM: ainvoke(supervisor_prompt)<br/>wait_for(timeout=60s)
    LLM-->>SUP: 라우팅 코멘트

    SUP->>GEN: route_supervisor() → "generation"
    GEN->>RAG: similarity_search(query, k=5)<br/>회사+문서유형 필터
    RAG-->>GEN: 참고 약관 청크 5개
    GEN->>LLM: invoke(clause_prompt + RAG context)
    LLM-->>GEN: 약관 초안
    GEN-->>SUP: draft_content, iteration=1

    Note over SUP: last_role=generation<br/>→ next_step=compliance
    SUP->>LLM: ainvoke(supervisor_prompt)
    LLM-->>SUP: 라우팅 코멘트

    SUP->>COMP: route_supervisor() → "compliance"
    Note over COMP: 3종 문서 병렬 검증<br/>asyncio.gather(3개 validate_async)
    COMP->>COMP: ViolationDetector.detect()<br/>5개 탐지기 병렬 실행<br/>각 60초 타임아웃
    COMP-->>SUP: status=PASS, compliance_score=0.95<br/>post_edit_compliance_done=False

    Note over SUP: last_role=compliance<br/>status=PASS, post_edit_done=False<br/>→ next_step=edit
    SUP->>LLM: ainvoke(supervisor_prompt)
    LLM-->>SUP: 라우팅 코멘트

    SUP->>EDIT: route_supervisor() → "edit"
    Note over EDIT: 위반 항목 부분 수정 +<br/>상품설명서·사업방법서 동시 생성
    EDIT->>LLM: ainvoke(edit_prompt)<br/>wait_for(timeout=60s)
    LLM-->>EDIT: 수정된 약관 (final_content)
    EDIT->>RAG: similarity_search(상품설명서/사업방법서)
    RAG-->>EDIT: 참고 문서 청크
    EDIT->>LLM: invoke(description_prompt)
    LLM-->>EDIT: 상품설명서
    EDIT->>LLM: invoke(biz_method_prompt)
    LLM-->>EDIT: 사업방법서
    EDIT-->>SUP: final_content, product_description, business_method
    Note over SUP: last_role=edit, post_edit_done=True<br/>→ next_step=final_validation (supervisor 조건부 라우팅 경유)
    SUP->>FV: route_supervisor() → "final_validation"

    FV->>LLM: arun_final_validation()<br/>(3종 문서 최종 검증)
    LLM-->>FV: passed=True, summary="최종 검증 완료"
    FV-->>SUP: status=PASS

    Note over SUP: last_role=final_validation<br/>→ next_step=end
    SUP->>SUP: END 라우팅

    WF-->>WF: _build_result(final_state)<br/>상태 정규화 (PASS→COMPLIANCE_PASSED)
    WF-->>API: GenerateResponse
    API-->>FE: HTTP 200 JSON
    FE-->>담당자: 약관·상품설명서·사업방법서 표시
```

---

## 2. 재생성 흐름 (Compliance FAIL → 재생성 → PASS)

약관 초안이 법규 검증에서 실패하여 위반 피드백을 반영해 재생성한 후 통과하는 시나리오.

```mermaid
sequenceDiagram
    actor 담당자 as 보험사 담당자
    participant FE as Frontend<br/>(Streamlit)
    participant API as Backend<br/>(FastAPI)
    participant SUP as supervisor
    participant GEN as generation
    participant COMP as compliance
    participant EDIT as edit
    participant FV as final_validation
    participant LLM as 외부 LLM<br/>(OpenRouter)
    participant RAG as ChromaDB<br/>(RAG)

    Note over 담당자,RAG: coordinator → planner → supervisor → generation (1차) 생략

    GEN->>RAG: similarity_search(약관, k=5)
    RAG-->>GEN: 참고 약관 청크
    GEN->>LLM: invoke(clause_prompt) — 1차 생성
    LLM-->>GEN: 약관 초안 #1
    GEN-->>SUP: draft_content, iteration=1

    Note over SUP: last_role=generation<br/>→ next_step=compliance
    SUP->>COMP: route_supervisor() → "compliance"

    COMP->>COMP: ViolationDetector (5개 탐지기 병렬)
    Note over COMP: OVERSTATEMENT 3건<br/>MISSING_REQUIREMENT 2건 발견
    COMP-->>SUP: status=FAIL, violations=5건<br/>compliance_score=0.62<br/>next_action=REGENERATE

    Note over SUP: last_role=compliance<br/>status=FAIL, iteration=1<br/>→ next_step=generation (재생성)
    SUP->>LLM: ainvoke(supervisor_prompt)
    LLM-->>SUP: "위반 5건 발견, 재생성합니다"

    SUP->>GEN: route_supervisor() → "generation"
    Note over GEN: iteration=1이므로 regenerate() 호출<br/>violations[:5]에서 priority_fixes 구성
    GEN->>RAG: similarity_search(약관, k=5)
    RAG-->>GEN: 참고 약관 청크
    GEN->>LLM: invoke(clause_prompt + regeneration_feedback)<br/>— 피드백 포함 재생성
    LLM-->>GEN: 약관 초안 #2 (위반 수정됨)
    GEN-->>SUP: draft_content, iteration=2

    Note over SUP: last_role=generation<br/>→ next_step=compliance
    SUP->>COMP: route_supervisor() → "compliance"

    COMP->>COMP: ViolationDetector (5개 탐지기 병렬)
    Note over COMP: 위반 없음 — COMPLIANCE_PASSED
    COMP-->>SUP: status=PASS, compliance_score=0.97<br/>post_edit_compliance_done=False<br/>next_action=READY_FOR_DELIVERY

    Note over SUP: last_role=compliance<br/>status=PASS, post_edit_done=False<br/>→ next_step=edit
    SUP->>EDIT: route_supervisor() → "edit"

    Note over EDIT: violations 없음 → final_content = draft_content<br/>상품설명서·사업방법서만 생성
    EDIT->>LLM: invoke(description_prompt)
    LLM-->>EDIT: 상품설명서
    EDIT->>LLM: invoke(biz_method_prompt)
    LLM-->>EDIT: 사업방법서
    EDIT-->>SUP: final_content, product_description, business_method
    Note over SUP: last_role=edit, post_edit_done=True<br/>→ next_step=final_validation (supervisor 조건부 라우팅 경유)
    SUP->>FV: route_supervisor() → "final_validation"

    FV->>LLM: arun_final_validation()
    LLM-->>FV: passed=True
    FV-->>SUP: status=PASS

    Note over SUP: last_role=final_validation → END
    SUP->>SUP: END

    SUP-->>API: final_state<br/>(status=PASS, iteration=2, compliance_score=0.97)
    API-->>FE: HTTP 200<br/>status=COMPLIANCE_PASSED
    FE-->>담당자: "2회 재생성 후 법규 준수 완료"
```

---

## 3. 사용자 작성 약관 검증·수정 흐름

`user_document` 필드 제공 시 generation 생략, compliance → revise 반복 모드.

```mermaid
sequenceDiagram
    actor 담당자 as 보험사 담당자
    participant API as Backend
    participant SUP as supervisor
    participant COMP as compliance
    participant REV as revise
    participant LLM as 외부 LLM

    담당자->>API: POST /generate<br/>user_document="제1관..."
    Note over API: draft_content = user_document<br/>(generation 건너뜀)

    Note over SUP: last_role=planner<br/>is_revise_mode=True<br/>→ next_step=compliance
    SUP->>COMP: route_supervisor() → "compliance"

    COMP->>COMP: 사용자 약관 검증
    Note over COMP: 위반 3건 발견
    COMP-->>SUP: status=FAIL, iteration=1

    Note over SUP: is_revise_mode=True<br/>→ next_step=revise
    SUP->>REV: route_supervisor() → "revise"

    REV->>LLM: ainvoke(edit_prompt + violations)
    LLM-->>REV: 수정된 약관
    REV-->>SUP: draft_content=수정본, iteration=2

    Note over SUP: last_role=revise → next_step=compliance
    SUP->>COMP: route_supervisor() → "compliance"

    COMP->>COMP: 수정된 약관 재검증
    Note over COMP: 위반 없음
    COMP-->>SUP: status=PASS

    Note over SUP: is_revise_mode=True, status=PASS<br/>→ next_step=end
    SUP-->>API: final_state (약관만, 상품설명서 없음)
    API-->>담당자: status=COMPLIANCE_PASSED
```
