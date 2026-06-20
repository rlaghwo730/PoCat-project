# 컴포넌트 설계서

**시스템명**: PoCat — 실손의료보험 약관 자동 생성 시스템  
**버전**: 2.0.0  
**작성일**: 2026-06-20

---

## 1. 시스템 전체 구조

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (Streamlit)                                           │
│  └─ 상품 조건 입력 UI → POST /generate or /generate/stream     │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP / SSE
┌────────────────────────▼────────────────────────────────────────┐
│  Backend (FastAPI)                                              │
│  ├─ app.py  (API 라우터, Pydantic 모델)                        │
│  ├─ workflow_service.py  (LangGraph 실행, 결과 변환)           │
│  └─ agents/llm.py  (LLM 팩토리 — OpenRouter + Upstage 폴백)   │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  LangGraph 워크플로우  (graph/builder.py + nodes.py)           │
│  coordinator → planner → supervisor(허브)                       │
│    supervisor → generation → compliance → edit                  │
│    edit → final_validation → supervisor → END                   │
└──┬──────────┬──────────────────────────────────────────────────┘
   │          │
   │     ┌────▼──────────────────────────────────────────────┐
   │     │  Generation Agent (generation_agent/)             │
   │     │  ├─ GenerationAgent.generate()                    │
   │     │  ├─ GenerationAgent.regenerate()                  │
   │     │  └─ GenerationAgent.generate_product_description()│
   │     └────────────────────────────────────────────────────┘
   │
   │     ┌────────────────────────────────────────────────────┐
   │     │  Compliance Agent (compliance_agent/)              │
   │     │  ├─ ComplianceAgent.validate_async()               │
   │     │  └─ ViolationDetector (5개 탐지기 병렬)            │
   │     └────────────────────────────────────────────────────┘
   │
   ├─ ChromaDB (RAG 벡터 저장소)
   ├─ pgvector (unified_retrieval_chunk 법률 DB)
   └─ Langfuse (LLM 트레이싱)
```

---

## 2. Frontend (Streamlit)

**역할**: 보험사 담당자가 상품 조건을 입력하고 생성 결과를 확인하는 Web UI.

**주요 파일**: `frontend/` 또는 루트의 Streamlit 앱 파일

**인터페이스**
- `POST /generate` — 동기 결과 수신
- `POST /generate/stream` — SSE 스트리밍으로 진행 상황 실시간 표시

**입력 항목**
- `document_request`: 보험회사, 상품명, 문서 유형
- `product_design_conditions`: 보험기간, 갱신 유형, 가입나이 등
- `coverage_conditions`: 기본보장종목, 비급여 특약, 보장한도, 자기부담금
- `user_document` (선택): 사용자 직접 작성 약관 (검증·수정 모드 전환)

---

## 3. Backend (FastAPI)

**역할**: REST API 진입점. 요청 유효성 검증, 워크플로우 실행, 결과 직렬화.

**주요 파일**: `backend/src/api/app.py`

**핵심 컴포넌트**

| 클래스/함수 | 역할 |
|-------------|------|
| `GenerateRequest` | 입력 Pydantic 모델. `document_request`, `coverage_conditions` 등 5개 필드 |
| `GenerateResponse` | 출력 모델. `status`, `content`, `compliance_score_pct`, `violations_for_ui` 등 |
| `generate_clause()` | `POST /generate` 핸들러. `run_workflow()` 호출 |
| `generate_clause_stream()` | `POST /generate/stream` 핸들러. `StreamingResponse` 반환 |
| `log_requests` | HTTP 미들웨어. 요청 ID 부여 및 로깅 |

**상태 코드 정규화** (`workflow_service.py`)

| 내부 상태 (`nodes.py`) | API 응답 상태 |
|------------------------|--------------|
| `PASS` | `COMPLIANCE_PASSED` |
| `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` |
| 그 외 / 오류 | `ORCHESTRATOR_ERROR` |

---

## 4. LangGraph 워크플로우

**역할**: 다중 에이전트 오케스트레이션. supervisor가 허브로서 모든 라우팅을 결정.

**주요 파일**: `backend/src/graph/builder.py`, `backend/src/graph/nodes.py`

### 4.1 노드 구성 (7개)

| 노드 | 함수 | 역할 |
|------|------|------|
| `coordinator` | `coordinator_node()` | 요청 분석·유효성 검증 |
| `planner` | `planner_node()` | 작업 전략 수립 |
| `supervisor` | `supervisor_node()` | 규칙 기반 라우팅 허브. `next_step` 결정 + LLM 코멘트 생성 |
| `generation` | `generation_node()` | GenerationAgent로 약관 초안 생성 또는 재생성 |
| `compliance` | `compliance_node()` | ComplianceAgent로 3종 문서 병렬 검증 |
| `edit` | `edit_node()` | 위반 항목 수정 + 상품설명서·사업방법서 동시 생성 |
| `final_validation` | `final_validation_node()` | final_validation_agent로 최종 품질 검증 |

### 4.2 엣지 구성

```
START → coordinator → planner → supervisor
supervisor --(조건부)-→ generation | compliance | edit | final_validation | revise | END
generation    → supervisor
compliance    → supervisor
edit          → final_validation   (direct edge, supervisor 우회)
final_validation → supervisor
revise        → supervisor
```

### 4.3 supervisor 라우팅 규칙

| `last_role` | 조건 | `next_step` |
|-------------|------|------------|
| `planner` | `user_document` 없음 | `generation` |
| `planner` | `user_document` 있음 | `compliance` |
| `generation` | — | `compliance` |
| `compliance` | `status == PASS` | `edit` |
| `compliance` | `iteration >= 3` | `edit` |
| `compliance` | `status == FAIL` | `generation` |
| `compliance` | `post_edit_compliance_done == True` + PASS | `end` |
| `edit` | `post_edit_compliance_done == False` | `compliance` |
| `edit` | `post_edit_compliance_done == True` | `final_validation` |
| `final_validation` | — | `end` |

### 4.4 LLM 타임아웃

모든 `llm.ainvoke()` 호출은 `asyncio.wait_for(..., timeout=60.0)`으로 래핑됨.  
대상 노드: coordinator, planner, supervisor, edit.

### 4.5 A2A 메시지

각 노드 완료 시 `create_a2a_message()`로 표준 에이전트 간 메시지를 `a2a_messages` 리스트에 누적.  
실행 흐름에는 영향 없이 관찰성(Observability) 목적으로만 사용.

---

## 5. Generation Agent

**역할**: ChromaDB RAG 검색 + 회사별 프롬프트 구성 + LLM 호출로 약관·상품설명서·사업방법서 생성.

**주요 파일**: `generation_agent/agents/generation_agent.py`

**지원 회사 메타데이터**: 삼성화재, 현대해상, DB손해보험 (약관 구조, 조항 형식, 가입나이, 갱신 조건 등)

**핵심 메서드**

| 메서드 | 역할 |
|--------|------|
| `generate(request)` | 약관 초안 최초 생성 |
| `regenerate(request, feedback, iteration)` | 위반 피드백 포함 재생성 |
| `generate_product_description(clause, request)` | 상품설명서 + 사업방법서 동시 생성 |
| `_retrieve_context(request, doc_type)` | ChromaDB 벡터 검색 (회사+문서유형 필터 우선) |
| `_retrieve_legal_context(request)` | pgvector DB에서 관련 법률/규제 조회 |

**RAG 검색 전략**
1. 회사(`company`) + 문서유형(`document_type`) 필터로 k=5 검색
2. 결과 2개 미만 → 회사 필터만으로 폴백
3. 그래도 없음 → 전사 검색 폴백

**LLM 선택 로직**
- `OPENROUTER_API_KEY` + `model_override` 있음 → OpenRouter ChatOpenAI
- `UPSTAGE_API_KEY` 있음 → ChatUpstage(solar-pro) 폴백
- 둘 다 없음 → ValueError 발생

---

## 6. Compliance Agent

**역할**: 생성된 문서의 법규 준수 여부를 5종 탐지기로 검증하고 준수율·위반 목록 반환.

**주요 파일**: `compliance_agent/compliance_agent.py`, `compliance_agent/detection_engine/violation_detector.py`

**아키텍처**

```
ComplianceAgent
  └─ ViolationDetector (asyncio.gather 병렬 실행)
       ├─ OverstatementDetector   — 과장 표현 (Regex + Pattern)
       ├─ SubjectiveDetector      — 주관적 표현
       ├─ ContradictionDetector   — 내부 모순
       ├─ ForbiddenWordDetector   — 금지어
       └─ MissingReqDetector      — 필수기재 누락 (보험업감독규정)
```

**준수율 판정 기준**

| 조건 | 결과 | next_action |
|------|------|-------------|
| 위반 없음 | `COMPLIANCE_PASSED` | `READY_FOR_DELIVERY` |
| 준수율 ≥ 80% | `COMPLIANCE_PASSED` | `THRESHOLD_PASSED` |
| 위반 있음 | `VIOLATIONS_FOUND` | `REGENERATE` |
| 3회 반복 | `VIOLATIONS_FOUND` | `MANUAL_REVIEW_REQUIRED` |
| 동일 위반 루프 | `VIOLATIONS_FOUND` | `GENERATOR_FAILURE` |

**session_id 기반 IterationTracker**: 세션별 반복 횟수와 위반 이력을 관리하여 SOFT_LOOP·HARD_LOOP 감지.

---

## 7. Final Validation Agent

**역할**: edit 완료 후 3종 문서의 최종 품질 검증. compliance와 별개의 LLM 기반 검증.

**주요 파일**: `backend/src/agents/final_validation_agent.py`

**인터페이스**
```python
async def arun_final_validation(payload: dict, llm) -> dict:
    # payload: {final_content, product_description, business_method, violations, request}
    # returns: {passed: bool, summary: str, issues: list}
```

**연결 방식**: `final_validation_node`에서 supervisor의 LLM(`get_supervisor_llm()`)을 공유 사용.

---

## 8. RAG 시스템

**역할**: 실제 보험사 약관·법률 텍스트를 벡터 검색으로 제공하여 LLM 환각을 방지.

**벡터 저장소**: ChromaDB (로컬) — 삼성화재, 현대해상, DB손해보험 약관·상품설명서·사업방법서

**법률 DB**: PostgreSQL + pgvector — `unified_retrieval_chunk` 테이블  
쿼리 조건: `source_domain IN ('legal', 'insurance_cited_law')`, `is_active = TRUE`

**필터 키**: `company` (보험사명), `document_type` (약관/상품요약서/사업방법서)

---

## 9. LLM 팩토리

**역할**: 노드 유형별 LLM 인스턴스를 생성하고 retry·fallback 체인을 구성.

**주요 파일**: `backend/src/agents/llm.py`, `backend/src/agents/agents.py`

**LLM 구성**

```python
primary = (
    ChatOpenAI(model=..., base_url="https://openrouter.ai/api/v1", ...)
    .with_retry(stop_after_attempt=3)
)
return (
    primary
    .with_fallbacks([upstage_llm])  # Upstage Solar-Pro 폴백
)
```

**모델 매핑** (`_MODEL_MAP`)

| 유형 | 모델 |
|------|------|
| `basic` | `openai/gpt-oss-120b:free` |
| `reasoning` | `openai/gpt-oss-120b:free` |
| `supervisor` | `openai/gpt-oss-120b:free` |

---

## 10. Langfuse 모니터링

**역할**: LLM 호출 트레이싱, 세션 추적, 성능 관찰성 수집.

**주요 파일**: `backend/src/service/workflow_service.py`

**구성 방식**
- `Langfuse(public_key, secret_key, host)` 초기화
- `LangfuseHandler()` — LangChain 콜백으로 각 노드의 LLM 호출 자동 추적
- `langfuse.start_as_current_observation(as_type="span", name="insurance-policy-generation")`
- `propagate_attributes(session_id, tags, metadata)` — 세션/모델 메타데이터 추가
- 완료 후 `langfuse.flush()` 호출

**추적 정보**: `status`, `iteration`, 사용 모델명, `session_id`
