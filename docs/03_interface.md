# 인터페이스 정의서

**시스템명**: PoCat API  
**버전**: 2.0.0  
**Base URL**: `http://localhost:8000`  
**작성일**: 2026-06-20  
**소스**: `backend/src/api/app.py`

---

## 1. 공통 사항

### 1.1 Content-Type
- Request: `application/json`
- Response: `application/json` (스트리밍 엔드포인트는 `text/event-stream`)

### 1.2 CORS
`allow_origins=["*"]` — 개발 환경에서 Streamlit 포함 모든 오리진 허용

### 1.3 공통 에러 응답

| HTTP 상태 코드 | 원인 | 응답 body |
|---------------|------|-----------|
| 400 | `basic_coverage_items` 미입력 | `{"detail": "coverage_conditions.basic_coverage_items 에 하나 이상의 항목이 필요합니다."}` |
| 500 | 워크플로우 내부 오류 | `{"detail": "<오류 메시지>"}` |

### 1.4 요청 로깅
모든 요청에 8자리 UUID 요청 ID 부여 (`[req_id] METHOD /path` 형식으로 로그 기록).

---

## 2. 엔드포인트 상세

---

### 2.1 POST /generate

**설명**: LangGraph 워크플로우를 실행하여 보험 약관, 상품설명서, 사업방법서를 생성하고 법규 검증 결과를 반환한다.

#### Request 스키마

```json
{
  "document_request": {
    "insurance_company": "삼성화재",
    "product_name": "무배당 다이렉트 실손의료비보험(2605.1)",
    "product_version": "2605.1",
    "document_type": "약관",
    "dividend_type": "무배당",
    "insurance_type": "기본형 실손의료비보험"
  },
  "product_design_conditions": {
    "policy_period": "1년 만기",
    "premium_payment_period": "전기납",
    "premium_payment_cycle": "월납",
    "renewal_type": "갱신형",
    "renewal_period": "1년",
    "max_renewal_count": 4,
    "reinstatement_cycle": "5년",
    "join_age_min": "0세",
    "join_age_max": "65세",
    "max_coverage_age": 100,
    "fetal_enrollment": "가능",
    "policy_loan": "가능"
  },
  "coverage_conditions": {
    "basic_coverage_items": ["상해급여실손", "질병급여실손"],
    "noncovered_rider_items": ["중증비급여", "비중증비급여"],
    "three_major_noncovered_items": ["도수치료", "주사료", "MRI"],
    "coverage_limit": {
      "급여": "5천만원",
      "비급여": "5천만원",
      "도수치료": "350만원",
      "주사료": "250만원",
      "MRI": "300만원"
    },
    "outpatient_limit": "20만원",
    "deductible_rule": {
      "일반_의료기관": "1만원과 보장대상의료비의 20% 중 큰 금액",
      "상급종합병원": "2만원과 보장대상의료비의 20% 중 큰 금액"
    }
  },
  "applicant_info": {},
  "user_document": null,
  "session_id": "",
  "model": null
}
```

**필드 설명**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `document_request` | object | ✅ | 문서 메타데이터 (보험회사, 상품명 등) |
| `product_design_conditions` | object | ✅ | 상품 설계 조건 (보험기간, 갱신 등) |
| `coverage_conditions` | object | ✅ | 보장 조건. `basic_coverage_items` 필수 |
| `applicant_info` | object | ❌ | 계약자 정보 (기본값 `{}`) |
| `user_document` | string \| null | ❌ | 사용자 작성 약관. 제공 시 generation 생략, 검증·수정 모드로 전환 |
| `session_id` | string | ❌ | 세션 ID. 빈 값이면 서버에서 UUIDv4 자동 생성 |
| `model` | string \| null | ❌ | OpenRouter 모델 ID 오버라이드 (예: `"anthropic/claude-3.5-sonnet"`) |

#### Response 스키마 (HTTP 200)

```json
{
  "status": "COMPLIANCE_PASSED",
  "content": "제1관(일반사항 및 용어의 정의)...",
  "iteration": 2,
  "compliance_score": 0.923,
  "compliance_score_pct": 92.3,
  "document_compliance_scores": {
    "terms": {
      "section_type": "약관",
      "status": "COMPLIANCE_PASSED",
      "compliance_score": 0.95,
      "compliance_score_pct": 95.0
    },
    "product_description": {
      "section_type": "상품설명서",
      "status": "COMPLIANCE_PASSED",
      "compliance_score": 0.90,
      "compliance_score_pct": 90.0
    },
    "business_method": {
      "section_type": "사업방법서",
      "status": "COMPLIANCE_PASSED",
      "compliance_score": 0.91,
      "compliance_score_pct": 91.0
    }
  },
  "compliance_next_action": "READY_FOR_DELIVERY",
  "violations_for_ui": [
    {
      "original_text": "최고의 보장을 제공합니다",
      "type": "OVERSTATEMENT",
      "legal_basis": "보험업법 제95조",
      "fix": "과장 표현 삭제 필요"
    }
  ],
  "suggestions": [],
  "product_description": "1. 보험상품의 특성 및 가입자격...",
  "business_method": "1. 보험의 종류: 장기손해보험...",
  "improvement_note": "2회 재생성 후 법규 준수 완료.",
  "db_warning": null,
  "model_used": null
}
```

**응답 필드 설명**

| 필드 | 타입 | 설명 |
|------|------|------|
| `status` | string | `COMPLIANCE_PASSED` \| `MANUAL_REVIEW_REQUIRED` \| `ORCHESTRATOR_ERROR` |
| `content` | string | 최종 약관 전문 (`final_content` 우선, 없으면 `draft_content`) |
| `iteration` | int | 완료된 생성 반복 횟수 |
| `compliance_score` | float(0~1) | 전체 3종 문서 가중 평균 준수율 |
| `compliance_score_pct` | float(0~100) | 준수율 % |
| `document_compliance_scores` | object | 문서별 준수율 상세 |
| `compliance_next_action` | string | `READY_FOR_DELIVERY` \| `THRESHOLD_PASSED` \| `REGENERATE` \| `MANUAL_REVIEW_REQUIRED` \| `GENERATOR_FAILURE` |
| `violations_for_ui` | array | 하이라이트용 위반 목록 |
| `suggestions` | array | 수동 검토 항목 (`COMPLIANCE_PASSED` 시 빈 배열) |
| `product_description` | string | 생성된 상품설명서 |
| `business_method` | string | 생성된 사업방법서 |
| `improvement_note` | string | 사람이 읽기 쉬운 진행 요약 메시지 |
| `db_warning` | string \| null | 법률 RAG DB 미연결 시 경고 메시지 |
| `model_used` | string \| null | 사용된 모델명 |

#### 에러 코드

| 코드 | 조건 |
|------|------|
| 400 | `basic_coverage_items` 없고 `user_document`도 없음 |
| 500 | 워크플로우 실행 중 예외 |

---

### 2.2 POST /generate/stream

**설명**: `/generate`와 동일한 워크플로우를 SSE(Server-Sent Events) 스트리밍으로 실행한다. 각 노드 완료 시 `progress` 이벤트, 전체 완료 시 `result` 이벤트를 방출한다.

**Response Content-Type**: `text/event-stream`  
**Response Headers**: `Cache-Control: no-cache`, `X-Accel-Buffering: no`

#### Request 스키마
`POST /generate`와 동일 (`GenerateRequest`)

#### SSE 이벤트 형식

모든 이벤트는 `data: {json}\n\n` 형식으로 전송된다.

**progress 이벤트** (각 노드 완료 시):
```json
{
  "type": "progress",
  "node": "compliance",
  "status": "FAIL",
  "iteration": 1,
  "compliance_score_pct": 72.3,
  "message": "검증 완료: FAIL / 준수율 72.3% (위반 5건)"
}
```

| 필드 | 설명 |
|------|------|
| `type` | 항상 `"progress"` |
| `node` | 완료된 노드명 (messages의 `role` 값) |
| `status` | 현재 workflow 상태 |
| `iteration` | 현재 반복 횟수 |
| `compliance_score_pct` | 현재 준수율 |
| `message` | 노드 완료 메시지 |

**result 이벤트** (전체 완료 시):
```json
{
  "type": "result",
  "status": "COMPLIANCE_PASSED",
  "content": "...",
  "iteration": 2,
  ...
}
```
`GenerateResponse` 전체 필드 + `"type": "result"` 포함.

**error 이벤트** (오류 발생 시):
```json
{
  "type": "error",
  "message": "워크플로우 실행 중 오류: ..."
}
```

**종료 마커**:
```
data: [DONE]

```

#### 에러 코드
`POST /generate`와 동일 (400, 500)

---

### 2.3 GET /health

**설명**: 서버 상태 확인. 로드 밸런서·모니터링 헬스체크용.

#### Request
없음 (Query Parameter 없음)

#### Response (HTTP 200)
```json
{
  "status": "ok",
  "version": "2.0.0"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `status` | string | 항상 `"ok"` (서버 정상) |
| `version` | string | API 버전 |

---

## 3. Pydantic 모델 상세

### ViolationUI
```python
class ViolationUI(BaseModel):
    original_text: str   # 위반된 원문 텍스트
    type:          str   # 위반 유형 (OVERSTATEMENT / SUBJECTIVE / ...)
    legal_basis:   str   # 근거 법령 (regulation 필드)
    fix:           str   # 수정 사유 (reason 필드)
```

### Suggestion
```python
class Suggestion(BaseModel):
    severity:               str   # HIGH / MEDIUM / LOW
    type:                   str   # 위반 유형
    action:                 str   # 수정 방향 (reason 필드)
    target_text:            str   # 위반 원문 (최대 100자)
    requires_manual_review: bool  # manual_flag 여부
```

### DocumentComplianceScore
```python
class DocumentComplianceScore(BaseModel):
    section_type:         str              # 약관 / 상품설명서 / 사업방법서
    status:               str              # COMPLIANCE_PASSED / VIOLATIONS_FOUND
    compliance_score:     float  # 0.0~1.0
    compliance_score_pct: float  # 0.0~100.0
```
