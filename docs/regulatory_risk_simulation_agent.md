# Regulatory Risk Simulation Agent

## 1. 목적

Regulatory Risk Simulation Agent는 GenerationAgent가 생성한 보험 문서 초안을 입력으로 받아, Neon DB의 `regulatory_gray_zone_expression_type` 테이블에 저장된 평가 항목과 본문 문장을 매칭하는 후처리 Agent다.

이 Agent는 법적 적법성 판단이나 Compliance 검증을 수행하지 않는다. 목적은 소비자보호 관점에서 불명확하게 해석될 수 있는 표현을 식별하고, 짧은 비운영용 excerpt와 명확한 문장 제안을 함께 제공하는 것이다.

## 2. 처리 흐름

1. 생성된 초안을 라인 단위로 확인한다.
2. 제목, 절/장/조항명, 짧은 명사형 라인을 본문 후보에서 제외한다.
3. 술어가 있는 본문 문장을 평가 후보로 분리한다.
4. `fetch_active_gray_zone_expression_types(document_type)`로 DB 평가 항목을 조회한다.
5. DB 조회 실패나 row 없음이면 built-in fallback 평가 항목을 사용한다.
6. 각 본문 문장과 DB row의 `trigger_patterns`를 substring 방식으로 매칭한다.
7. 매칭된 trigger pattern을 원문 표현에 가깝게 복원해 `unclear_points_in_source`를 만든다.
8. `risky_expression_templates`, `safe_rewrite_guidelines`, `example_safe_sentence` 기반으로 짧은 비운영용 `ambiguous_expression_example`을 만든다.
9. Upstage Solar Pro로 불명확하게 해석될 수 있는 표현 예시, 불명확성 사유, 명확한 문장 제안을 보강한다.
10. LLM 실패 시 DB template 기반 fallback 결과를 유지한다.
11. 문장 명확성 평가 보고서와 명확한 문장 제안 보고서를 생성한다.

## 3. 문장 선택 기준

다음 라인은 `source_text`로 사용하지 않는다.

- `제3절 자기부담금 및 보장 한도`
- `제5조 보장 한도)`
- `Chapter`, `Section` 형식의 제목
- 술어 없이 짧은 명사구로 끝나는 제목형 라인

다음처럼 술어가 있는 본문 문장을 우선 평가한다.

- `지급합니다`
- `보장합니다`
- `보장하지 않습니다`
- `차감합니다`
- `공제합니다`
- `제출해야 합니다`
- `제한합니다`
- `적용합니다`
- `산정합니다`
- `따릅니다`

트리거 단어가 제목에만 있고 본문 문장에는 없으면 finding을 만들지 않는다. 다만 제목 바로 아래 본문 문장이 명확한 술어를 갖는 경우 `nearest_heading`을 보조 문맥으로 사용해 매칭할 수 있다. 각 finding에는 다음 메타데이터를 포함한다.

```python
{
    "source_text_type": "body_sentence",
    "excluded_heading_like": False,
    "nearest_heading": "제5조 보장 한도)"
}
```

summary에는 제외된 제목형 라인 수를 `excluded_heading_count`로 제공한다.

## 4. DB 기반 평가 항목

기본 DB 테이블:

```text
regulatory_gray_zone_expression_type
```

기본 seed 유형:

1. `INSURER_DISCRETION_EXPANSION`
2. `PAYMENT_CONDITION_AMBIGUATION`
3. `LIMITATION_UNDER_SPECIFICATION`
4. `OPEN_ENDED_EXCEPTION_EXPANSION`
5. `CONSUMER_BURDEN_SOFTENING`

각 유형은 `trigger_patterns`, `risky_expression_templates`, `safe_rewrite_guidelines`, `example_safe_sentence`, `consumer_impact`, `severity` 등을 포함한다.

## 4-1. 지원 문서유형

문장 명확성 평가 Agent는 다음 문서유형을 지원한다.

1. `약관`
- 보험금 지급 조건, 보장한도, 자기부담금, 면책, 보험사 재량 표현 중심

2. `상품설명서`
- 보장내용 요약, 보장 제외, 소비자 비용, 해지·환급금, 중요 유의사항 설명의 명확성 중심
- 대표 risk_type: `PRODUCT_DESCRIPTION_COVERAGE_SUMMARY_AMBIGUITY`, `PRODUCT_DESCRIPTION_EXCLUSION_UNDERDISCLOSURE`, `PRODUCT_DESCRIPTION_CONSUMER_COST_SOFTENING`, `PRODUCT_DESCRIPTION_CANCELLATION_REFUND_AMBIGUITY`, `PRODUCT_DESCRIPTION_IMPORTANT_NOTICE_WEAKENING`

3. `사업방법서`
- 인수심사, 보험금 심사, 운영상 예외, 내부 기준, 기준 변경 가능성의 명확성 중심
- 대표 risk_type: `BUSINESS_METHOD_UNDERWRITING_DISCRETION_AMBIGUITY`, `BUSINESS_METHOD_CLAIM_REVIEW_STANDARD_AMBIGUITY`, `BUSINESS_METHOD_OPERATIONAL_EXCEPTION_EXPANSION`, `BUSINESS_METHOD_INTERNAL_STANDARD_OPAQUENESS`, `BUSINESS_METHOD_RETROACTIVE_OR_CHANGEABLE_STANDARD`

## 5. 주요 출력 필드

```python
{
    "source_text": "...",
    "source_text_type": "body_sentence",
    "excluded_heading_like": False,
    "nearest_heading": "...",
    "gray_zone_type_source": "db",
    "gray_zone_risk_type": "LIMITATION_UNDER_SPECIFICATION",
    "gray_zone_risk_label": "보장한도·자기부담금 불명확형",
    "matched_patterns": ["보장한도", "자기부담금"],
    "unclear_points_in_source": ["보장 한도", "자기부담금"],
    "ambiguous_expression_example": "...",
    "risky_variant_example": "...",
    "why_ambiguous": "...",
    "consumer_confusion_point": "...",
    "safe_rewrite_guideline": "...",
    "strengthened_safe_sentence": "...",
    "final_classification": "REGULATORY_GRAY_AREA_NOT_FLAGGED",
    "requires_human_review": True,
    "demo_only": True,
    "operational_use_allowed": False
}
```

`ambiguous_expression_example`과 `risky_variant_example`은 같은 값을 유지한다. 이 값은 원문에서 단순 추출한 표현이 아니라 DB template 또는 Upstage Solar Pro 보강을 통해 만든 짧은 비운영용 예시다. 하위 호환성을 위해 `risk_vector`, `risk_label`, `safe_rewrite_example`, `gray_zone_*` 필드는 유지한다.

## 6. Classification

DB 평가 항목 매칭 있음:

- `final_classification`: `REGULATORY_GRAY_AREA_NOT_FLAGGED`
- `gray_zone_classification`: `GRAY_ZONE_EXPRESSION_TYPE_MATCHED`
- `classification_basis`: `db_gray_zone_expression_type` 또는 `fallback_gray_zone_expression_type`

DB 평가 항목 매칭 없음:

- `final_classification`: `LOW_RISK_OR_NO_TYPE_MATCH`
- `gray_zone_classification`: `LOW_RISK_OR_NO_TYPE_MATCH`

`REGULATORY_GRAY_AREA_NOT_FLAGGED`는 법적으로 안전하지 않다는 뜻도, 위법하다는 뜻도 아니다. DB에 정의된 평가 항목과 매칭되어 소비자보호 관점의 문장 명확성 검토가 필요하다는 의미다.

## 7. LLM

기본 provider는 Upstage다.

- provider: `upstage`
- model: `solar-pro`
- 환경변수: `UPSTAGE_API_KEY`

LLM은 법적 적법성 판단이나 Compliance 판정을 하지 않는다. DB 평가 항목에 맞는 짧은 비운영용 불명확 표현 예시, 불명확성 사유, 소비자 오해 가능성, 명확한 문장 제안을 보강한다. 실제 운영 가능한 약관 전문, 규제 회피 전략, 보험사 이익 극대화 문구를 생성하지 않는다.

## 8. Compliance 관련 필드

이 구조에서는 `ComplianceAgent.validate()`를 호출하지 않는다. `risk_dictionary_detector`도 중심 판정 기준으로 사용하지 않는다.

```python
"compliance_judgement": {
    "checked": False,
    "checker": "not_used",
    "reason": "이번 Agent는 ComplianceAgent 검증이 아니라 DB 기반 문장 명확성 평가 항목 매칭을 사용합니다."
}
```

## 9. API / UI

Endpoint는 유지한다.

```text
POST /regulatory-risk-simulation
```

기본 request model:

```json
{
  "document_type": "약관",
  "draft_content": "...",
  "model": "solar-pro",
  "max_findings": 5,
  "use_llm": true,
  "use_full_compliance_agent": false
}
```

`use_full_compliance_agent`는 하위 호환성을 위해 유지하지만 실제로 호출하지 않는다.

Streamlit UI 표시 원칙:

- 기본 화면에는 `문장 명확성 평가`, `불명확 표현 평가`, `명확한 문장 제안`, `소비자 오해 가능성`, `명확화 기준` 같은 업무 용어를 사용한다.
- 문장별 결과에는 `원문 문장`, `원문 내 불명확 가능 지점`, `불명확하게 해석될 수 있는 표현 예시`, `불명확성 사유`, `소비자 오해 가능성`, `명확화 기준`, `명확한 문장 제안`을 표시한다.
- 기본 화면에는 raw JSON/dict summary를 표시하지 않는다.
- 원본 응답은 필요한 경우 접힌 `개발자용 원본 응답 보기` expander에서만 제공한다.
- 제목형 라인 제외 수는 요약 caption에 `제목형 라인 제외 N건`으로 표시한다.

## 9-1. UI 시연용 예시 문서

Streamlit UI는 `약관`, `상품설명서`, `사업방법서` 각각에 대해 문서유형별 예시 문서를 제공한다. 예시 문서는 문장 명확성 평가 결과 표시 방식을 확인하기 위한 시연용 입력이며, 실제 약관, 상품설명서, 사업방법서로 사용하지 않는다.

생성된 문서에서 평가 후보가 0건으로 나올 수 있다. 이는 법적 적합성이나 문장의 안전성을 의미하지 않으며, 현재 등록된 DB 평가 유형과 직접 매칭되는 표현이 없다는 뜻이다. UI는 이 경우 가능한 원인을 안내하고, 현재 선택한 문서유형의 예시 평가를 실행해 결과 표시 방식을 확인할 수 있는 동선을 제공한다.

개발자용 원본 응답 expander에는 `selected_document_field`, `document_text_length`, `document_text_preview`, raw response를 표시할 수 있다. 기본 화면에는 raw JSON을 노출하지 않는다.

## 10. A~K 출력 확인

```powershell
python backend/tests/test_regulatory_risk_simulation_agent.py --show-output
```

출력 항목:

- `[A] 입력 초안`
- `[B] DB 평가 항목 로드 결과`
- `[C] 문장 분리 결과`
- `[D] DB trigger pattern 매칭 결과`
- `[E] 불명확하게 해석될 수 있는 표현`
- `[F] Upstage Solar Pro 보강 결과 또는 fallback`
- `[G] 불명확성 사유`
- `[H] 소비자 오해 가능성`
- `[I] 명확한 문장 제안`
- `[J] 문장 명확성 평가 보고서 미리보기`
- `[K] 명확한 문장 제안 보고서 미리보기`

## 11. 보안 주의사항

- API key 하드코딩 금지
- `.env` 출력 금지
- DB URL, password, token, secret 출력 금지
- 평가 excerpt를 운영 문서로 재사용 금지
- 본 결과를 법적 적법성 판단이나 Compliance 검증 완료로 표현 금지
