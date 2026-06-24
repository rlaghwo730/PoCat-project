# 유스케이스 명세서

**시스템명**: PoCat — 실손의료보험 약관 자동 생성 시스템  
**버전**: 2.0.0  
**작성일**: 2026-06-20

---

## 1. 액터 정의

| 액터 | 설명 |
|------|------|
| **보험사 담당자** | 약관 생성 요청을 발행하고 결과를 검토하는 1차 사용자. Streamlit UI를 통해 상품 조건 입력 |
| **AI 에이전트 시스템** | LangGraph 워크플로우 상의 7개 노드(coordinator/planner/supervisor/generation/compliance/edit/final_validation). 각 노드가 독립적인 에이전트 역할을 수행 |
| **외부 LLM (OpenRouter)** | 노드별 모델 사용 — basic/reasoning: `meta-llama/llama-3.2-3b-instruct:free`, supervisor: `openai/gpt-oss-120b:free`, generation: `qwen/qwen3-235b-a22b:free`, edit: `qwen/qwen-2.5-72b-instruct:free`, compliance: `nousresearch/hermes-3-llama-3.1-405b:free`. Upstage Solar-Pro가 폴백(fallback)으로 등록됨 |
| **ChromaDB (RAG)** | 삼성화재·현대해상·DB손해보험 실제 약관·상품설명서·사업방법서 벡터 저장소 |
| **pgvector DB** | `unified_retrieval_chunk` 등 법률/보험업감독규정 텍스트 저장소 |
| **Langfuse** | LLM 호출 트레이싱 및 관찰성 수집 외부 서비스 |

---

## 2. 유스케이스 목록

| ID | 유스케이스명 | 주요 액터 |
|----|-------------|-----------|
| UC-01 | 약관 초안 생성 요청 | 보험사 담당자, AI 에이전트 시스템 |
| UC-02 | 법규 준수 검증 | AI 에이전트 시스템 |
| UC-03 | 약관 자동 재생성 | AI 에이전트 시스템, 외부 LLM |
| UC-04 | 3종 문서 생성 (약관+상품설명서+사업방법서) | AI 에이전트 시스템, 외부 LLM |
| UC-05 | 최종 산출물 검증 | AI 에이전트 시스템 |
| UC-06 | 스트리밍 진행상황 확인 | 보험사 담당자, AI 에이전트 시스템 |

---

## 3. 유스케이스 상세

### UC-01: 약관 초안 생성 요청

**목적**: 보험사 담당자가 상품 조건을 입력하면 시스템이 법규 준수 약관 초안을 자동 생성한다.

**사전 조건**
- `coverage_conditions.basic_coverage_items`에 하나 이상의 보장 종목이 포함되어 있어야 함
- `OPENROUTER_API_KEY` 또는 `UPSTAGE_API_KEY` 환경 변수 설정됨
- 또는 `user_document` 필드에 사용자 작성 약관 전문 제공 (검증·수정 모드)

**기본 흐름**
1. 담당자가 Streamlit UI에서 `document_request`, `product_design_conditions`, `coverage_conditions` 입력
2. Frontend가 `POST /generate` 또는 `POST /generate/stream` 호출
3. 서버가 `session_id` 자동 생성 (미제공 시)
4. `run_workflow()` 또는 `stream_workflow()`가 LangGraph 그래프를 실행
5. coordinator 노드가 요청을 분석·검증
6. planner 노드가 생성 전략을 수립
7. supervisor 노드가 다음 단계를 결정 → generation 노드 실행
8. generation 노드가 ChromaDB RAG + LLM으로 약관 초안 생성
9. 최종 결과(`GenerateResponse`)를 담당자에게 반환

**예외 흐름**
- E1: `basic_coverage_items` 미입력 → HTTP 400 반환
- E2: LLM API 키 없음 → `ORCHESTRATOR_ERROR` 반환
- E3: LLM ainvoke 60초 초과 → `asyncio.TimeoutError` → except 블록에서 오류 메시지 반환
- E4: `user_document` 제공 시 generation 단계 생략, compliance 직행

---

### UC-02: 법규 준수 검증

**목적**: 생성된 약관·상품설명서·사업방법서를 5종 탐지기로 법규 위반 여부를 검증한다.

**사전 조건**
- `draft_content` 또는 `final_content`, `product_description`, `business_method` 중 하나 이상 존재
- `ComplianceAgent` 인스턴스 초기화됨

**기본 흐름**
1. compliance 노드가 3종 문서를 `section_type`별로 독립 `DetectionInput` 구성
2. `asyncio.gather`로 3개 문서를 병렬 검증 (`validate_async` 호출)
3. 각 문서별 `ViolationDetector`가 5개 탐지기를 병렬 실행:
   - OVERSTATEMENT (과장 표현)
   - SUBJECTIVE (주관적 표현)
   - CONTRADICTION (내부 모순)
   - FORBIDDEN_WORD (금지어)
   - MISSING_REQUIREMENT (필수기재 누락)
4. 각 탐지기는 60초 타임아웃(`asyncio.wait_for`) 적용
5. `compliance_score` 산출 (콘텐츠 길이 가중 평균)
6. `TerminationLogic`으로 PASS / PASS_THRESHOLD / FAIL_MAX / HARD_LOOP 판정
7. `compliance_next_action` 결정 후 supervisor로 반환

**예외 흐름**
- E1: 개별 탐지기 실패 → `return_exceptions=True`로 예외 포획, `manual_flag=True` 위반으로 대체
- E2: 준수율 ≥ 80% → `THRESHOLD_PASSED`로 조기 종료
- E3: 3회 이상 반복 → `MANUAL_REVIEW_REQUIRED` 상태로 종료
- E4: 동일 위반이 3회 연속 등장 → `SOFT_LOOP` 감지, `manual_flag=True` 설정

---

### UC-03: 약관 자동 재생성

**목적**: 법규 위반이 발견되면 피드백을 반영해 약관을 재생성한다.

**사전 조건**
- compliance 결과 `status == "FAIL"` 이고 `next_action == "REGENERATE"`
- `iteration < 3`

**기본 흐름**
1. supervisor 노드가 `last_role == "compliance"`, `status == "FAIL"` → `next_step = "generation"` 결정
2. generation 노드가 이전 iteration의 위반 목록(`violations[:5]`)에서 `priority_fixes` 구성
3. `GenerationAgent.regenerate()`에 위반 피드백 + iteration 번호 전달
4. LLM이 재생성 섹션을 포함한 프롬프트로 약관 재작성
5. 새 초안을 `draft_content`에 저장, `iteration += 1`
6. compliance 노드로 재진입

**예외 흐름**
- E1: `iteration >= 3` → edit 노드로 진행 (재생성 중단)
- E2: 동일 위반 반복 → HARD_LOOP 감지 → `GENERATOR_FAILURE` next_action → END

---

### UC-04: 3종 문서 생성 (약관+상품설명서+사업방법서)

**목적**: 법규 검증 통과 후 약관 위반 항목을 수정하고 상품설명서·사업방법서를 동시 생성한다.

**사전 조건**
- supervisor가 `next_step = "edit"` 결정 (`status == "PASS"` 또는 `iteration >= 3`)
- `draft_content` 존재

**기본 흐름**
1. edit 노드가 `violations`를 순회해 `_build_fix_prompt()` 구성
2. LLM(edit 전용)이 약관 위반 항목만 최소 수정 → `final_content` 저장
3. `GenerationAgent.generate_product_description(final_content, request)` 호출:
   - 상품설명서: ChromaDB 검색 + 회사별 형식 지침 + LLM 생성
   - 사업방법서: ChromaDB 검색 + 회사별 21/16/18개 항목 지침 + LLM 생성
4. 결과를 `product_description`, `business_method`에 저장
5. edit 노드 완료 → `final_validation` 노드로 직행 (direct edge)

**예외 흐름**
- E1: violations 없음 → `final_content = draft_content` (수정 없이 통과)
- E2: LLM 실패 → `product_description = ""`, `business_method = ""`로 반환

---

### UC-05: 최종 산출물 검증

**목적**: 3종 문서 생성 완료 후 `final_validation_agent`로 최종 품질 검증을 수행한다.

**사전 조건**
- edit 노드 완료 (`final_content`, `product_description`, `business_method` 존재)
- `final_validation_agent.arun_final_validation` 임포트 가능

**기본 흐름**
1. `final_validation` 노드가 `arun_final_validation()` 호출
2. 3종 문서 + 기존 위반 목록 + 요청 정보를 인자로 전달
3. `passed`, `summary`, `issues` 결과 수신
4. `passed == True` → `status = "PASS"` 반환
5. supervisor 노드로 귀환 → `last_role == "final_validation"` → END 라우팅

**예외 흐름**
- E1: `arun_final_validation` import 실패 → except 블록 → `status = "MANUAL_REVIEW_REQUIRED"` 반환
- E2: 내부 오류 → 오류 메시지를 messages에 추가 후 `MANUAL_REVIEW_REQUIRED` 반환

---

### UC-06: 스트리밍 진행상황 확인

**목적**: 담당자가 `POST /generate/stream`으로 요청 시 각 노드 완료마다 SSE 이벤트를 수신한다.

**사전 조건**
- 클라이언트가 SSE(`text/event-stream`) 지원
- Langfuse 연결 (없어도 동작 가능)

**기본 흐름**
1. `stream_workflow()`가 `graph.astream(..., stream_mode="values")` 실행
2. 각 노드 완료 시 state 스냅샷 수신
3. `progress` 이벤트 emit: `{type, node, status, iteration, compliance_score_pct, message}`
4. 전체 완료 후 `result` 이벤트 emit: 전체 `GenerateResponse` 데이터
5. `data: [DONE]\n\n` 전송으로 스트림 종료

**예외 흐름**
- E1: 워크플로우 오류 → `{type: "error", message: ...}` emit 후 `[DONE]`
- E2: `final_state == None` → 결과 없음 오류 emit 후 `[DONE]`
- E3: 응답 헤더 `Cache-Control: no-cache`, `X-Accel-Buffering: no` 설정으로 버퍼링 방지
