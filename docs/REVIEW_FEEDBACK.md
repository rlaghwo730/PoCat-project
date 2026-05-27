# 법률규제 검증 에이전트 재검토 피드백 (코드 기반 심층 분석)

검토 기준:
- `CLAUDE.md`, 구현 코드 `compliance_agent/` 전체
- `python -m pytest compliance_agent/tests -q` → **59 passed**
- 참조: 보험업감독업무시행세칙, 4세대 실손의료보험 표준약관

---

## 1. 전체 아키텍처 재검토

### 🟢 잘된 부분

1. **책임 분리가 명확하다.** `ComplianceAgent.validate()` 하나로 진입하고, 탐지/추적/종료/피드백/최종검증이 각 클래스에 위임되어 있다. 5인 팀 협업 구조에서 파일 충돌 없이 분업 가능하다.
2. **탐지 레이어 전략이 실무적이다.** Regex(Rule 1/4) → Pattern+LLM(Rule 2) → 구조분석+LLM(Rule 3) → DB+keyword(Rule 5) 순서로 비용 대비 정확도를 최적화한다.
3. **루프 종료 조건 3가지가 모두 구현되어 있다.** `PASS`, `FAIL_MAX`, `FAIL_LOOP`가 `TerminationLogic`에 집중되어 있어 확장이 쉽다.

### 🟡 개선 필요 부분

1. **`IterationTracker`가 인스턴스 수명에 묶여 있다.** `ComplianceAgent.__init__()`에서 생성되므로, API 서버가 요청마다 `ComplianceAgent()`를 새로 만들면 `FAIL_MAX`/`FAIL_LOOP`가 **절대 트리거되지 않는다.** `session_id` 또는 외부 상태 저장소 기반으로 바꿔야 한다.
2. **`IterationTracker.iteration`과 `DetectionInput.iteration`이 두 개의 진실이다.** 트래커는 `record()` 호출 횟수로 세고, 입력은 생성 에이전트가 전달하는 `iteration` 필드를 쓴다. 둘이 어긋나면 `FAIL_MAX` 판정이 틀린다.
3. **최종 산출물 저장 경로가 없다.** `READY_FOR_DELIVERY` 신호 이후 약관 원문, 검증 리포트, iteration 이력이 어디에 저장되는지 정의되어 있지 않다.

### 🔴 리스크

1. **`violation_id` 충돌 → FAIL_LOOP 오작동.** `OverstatementDetector`에서 `violation_id`는 **패턴 인덱스**(`VIO_OVR_001`)이지 매치 인덱스가 아니다. 같은 패턴이 텍스트에서 3번 매칭되면 3개 모두 `VIO_OVR_001`을 갖는다. `IterationTracker.repeated_violation_ids()`는 `violation_id` 집합으로 FAIL_LOOP를 판단하므로, 1회 반복 안에서도 `VIO_OVR_001`이 2개 나오면 즉시 FAIL_LOOP가 트리거된다 — **false positive FAIL_LOOP**.
2. **LLM 실패 정책이 Rule 2/3 간에 불일치한다.** Rule 2(SUBJECTIVE)는 `except → return True`(위반 처리), Rule 3(CONTRADICTION)은 `except → return None`(skip 처리). 보수적 원칙과 일관성이 충돌한다.

### 📋 권장사항

1. `violation_id`를 `f"{rule_prefix}_{pattern_idx:03d}_{match_seq:03d}"` 형식으로 바꿔 같은 패턴의 여러 매치가 서로 다른 ID를 갖도록 한다.
2. `ComplianceAgent`를 session-aware하게 만든다. 생성자에 `session_id`를 받거나, 외부에서 `IterationTracker` 인스턴스를 주입(DI)한다.
3. `DetectionInput.iteration`을 신뢰하고 `IterationTracker.iteration`을 제거하거나, 둘 중 하나를 단일 source of truth로 정한다.

---

## 2. I/O 계약 명세 검토

### ✅ 검증 완료된 부분

- `ComplianceReport.to_dict()`가 CLAUDE.md OUTPUT A/B를 완전히 커버한다.
- `violations`와 `priority_fixes`가 `violation_id`로 연결되어 피드백 추적이 된다.
- `VIOLATIONS_FOUND` / `COMPLIANCE_PASSED` 상태 구분이 명확하다.

### ⚠️ 조정 필요한 부분

- **`section_type`이 자유 문자열이다.** `DetectionInput.section_type: str`이고 `MissingReqDetector`에서 `"약관"`, `"상품설명서"` 리터럴로 비교한다. 오타나 다른 값이 오면 모든 필수항목 검사가 조용히 skip된다. `Literal["약관", "상품설명서"]` 또는 Enum으로 강제해야 한다.
- **`product_meta`가 `dict[str, Any]`이고 검증이 없다.** 어떤 탐지기도 `product_meta`를 실제로 사용하지 않는다. 추후 Rule 1에서 `deductible` 값을 사용할 계획이라면 타입을 지금 잡아야 한다.
- **`suggested_text`가 placeholder이다.** `FeedbackBuilder`에서 `f"[{v.type.value}] {v.original_text[:60]}… → 수정 필요"` 형식은 생성 에이전트에게 아무런 수정 지침이 되지 않는다. 필드명을 `repair_constraints`나 `rewrite_guidance`로 바꾸고, 수정 방향 원칙만 담는 것이 협업 경계에도 맞다.
- **`confidence_score`가 항상 1.0이다.** `FinalCheck`는 `violations == []`일 때만 호출되고, `confidence_calculator.calculate([])`는 패널티 없이 `1.0`을 반환한다. "검증 완료"와 "검출 없음"은 다른 개념이다.

### 🔧 구현 시 주의사항

- 입력 오류는 검증 실패와 분리해야 한다. `ERROR_INVALID_SCHEMA`, `ERROR_UNSUPPORTED_SECTION_TYPE` 같은 상태를 `ComplianceReport.status`에 추가한다.
- 피드백 길이 제한이 필요하다. `priority_fixes`를 severity 상위 N개로 자르는 로직을 `FeedbackBuilder`에 추가한다.

---

## 3. 5개 Rule 실무 타당성 검토

### Rule 1: OVERSTATEMENT
- **타당성: 높음.** 10개 패턴과 caveat 탐지 로직이 실무 적용 가능하다.
- **보완 필요:** `_CONTEXT_WINDOW = 150`이 너무 넓을 수 있다. "전액보장" 이후 150자 안에 다른 조항의 자기부담금 언급이 오면 false negative가 된다. 문장 단위 window로 바꾸는 것을 고려한다. 추가 패턴 후보: "부담 없이", "청구하면 바로", "횟수 무제한", "비급여까지".
- **구현 난도: 낮음.**

### Rule 2: SUBJECTIVE
- **타당성: 중간.** 12개 패턴은 적절하지만 오탐 위험이 있다. `합리적인 이유 없이`처럼 부정 맥락이면 위반이 아닌데 LLM이 모호하게 판단할 수 있다.
- **보완 필요:** LLM 프롬프트에 "보험업법/표준약관에서 관용적으로 허용된 표현 목록"을 포함시켜 오탐을 줄인다. 현재 `temperature=0.1`은 적절하다.
- **구현 난도: 중간.** LLM 없이는 실행 불가하므로 통합 테스트가 mock 위주다.

### Rule 3: CONTRADICTION
- **타당성: 높음.** `_filter_candidate_pairs()`로 보장×면책 조합만 필터링하는 전략은 LLM 호출 수를 줄이는 실용적 접근이다.
- **보완 필요:** `_MAX_PAIRS = 30`이 실제 약관(30-50조항)에서 보장 5개 × 면책 5개 = 25쌍 정도라면 충분하다. 그러나 약관이 길어지면 조합 폭발이 발생한다. 조항 임베딩 기반 유사도 사전 필터를 추가하면 비용 절감 가능하다.
- **구현 난도: 높음.** LLM 실패 시 skip 정책이 Rule 2와 불일치하는 것을 먼저 정리한다.

### Rule 4: FORBIDDEN_WORD
- **타당성: 높음.** 14개 금지어 엔트리가 severity, 근거 조항, 이유까지 갖추고 있다.
- **보완 필요:** `re.escape(word)` 방식은 "무조건 지급"이 "무조건  지급"(공백 2개)이나 "무조건지급"을 못 잡는다. `\s*`를 삽입한 패턴으로 개선한다. 동의어 변형(원금보장→원금 보장→원금보전)도 고려한다.
- **구현 난도: 낮음.** 사전 품질이 전부다.

### Rule 5: MISSING_REQUIREMENT
- **타당성: 높음.** `section_type` 필터링으로 약관/상품설명서별 체크리스트를 분리한 것은 정확하다.
- **보완 필요:** keyword 존재 여부만 보므로 실제 요건 충족을 보장하지 않는다. "청구"가 한 번만 나와도 `REQ_008`이 PASS된다. 키워드 밀도 또는 섹션 구조 분석을 추가해야 한다. `section_type`이 `"약관"`이 아닌 다른 문자열로 오면 빈 목록이 반환되어 **모든 필수항목 검사가 silent skip**된다(앞서 언급한 버그와 연동).
- **구현 난도: 중간.** DB팀 API 계약이 확정되어야 mock을 교체할 수 있다.

### 📊 종합 평가
- **F1 Score 90% 도달 가능성:** Rule 1/4는 정밀도가 높아 90% 근처 가능. Rule 2/3는 LLM 의존도와 오탐 위험으로 현재 구현만으로는 어렵다. **라벨링 테스트셋 없이는 수치 검증 자체가 불가하다.**

---

## 4. 개발 난도 & 일정 평가

### Phase 3: Detection Engine (현재 완료)
- **난도:** 높음 → 골격 구현은 완료, 품질 고도화 필요
- **예상 잔여 시간:** 1-2주 (violation_id 버그 수정, LLM 오탐 튜닝, 패턴 보완)
- **위험도:** 높음 (LLM 호출 비용, 오탐율 미측정)

### Phase 4: Iteration Controller (현재 완료)
- **난도:** 중간
- **예상 잔여 시간:** 2-3일 (session-aware 리팩토링)
- **위험도:** 중간 — `ComplianceAgent`를 어떻게 배포하느냐에 따라 FAIL_MAX/FAIL_LOOP가 아예 작동 안 할 수 있다.

### Phase 5: DB/RAG Integration
- **난도:** 중간-높음
- **예상 시간:** 1주
- **위험도:** 높음 — API 스키마 미확정이 전체 일정의 실질 병목이다.

### Phase 6: Final Validation
- **난도:** 중간
- **예상 시간:** 3-4일
- **위험도:** 중간 — confidence_score가 항상 1.0인 문제를 먼저 해결해야 의미 있는 지표가 된다.

### Phase 7: 현직자 검증/고도화
- **난도:** 높음
- **예상 시간:** 최소 1-2주
- **위험도:** 높음 — 현직자 일정이 전체 일정의 외부 의존성이다.

### 🚨 일정상 리스크
- 6주 MVP는 "시연 가능한 데모" 기준에서 가능하다. 보험사 운영 수준은 어렵다.
- violation_id 버그, IterationTracker 세션 관리, confidence_score 의미화는 **현재 테스트가 통과해도 운영 시 문제**가 된다.

### 💡 권장 조정안
1순위: violation_id 고유성 버그 수정  
2순위: IterationTracker session 관리 방식 확정  
3순위: Rule 1/4/5 결정론적 엔진 안정화 후 Rule 2/3 LLM 정책 일관화

---

## 5. 팀 협업 관점 재검토

### ✅ 협업 구조에서 잘된 부분
- 생성/검증/DB 경계가 코드 레벨에서도 지켜지고 있다. `FeedbackBuilder`가 `suggested_text` placeholder만 넣고 실제 수정안을 만들지 않는 것이 협업 경계에 부합한다.
- `db_client.py`가 `MOCK_MODE` 플래그로 DB팀 API 없이도 개발 진행 가능하다.

### ⚠️ 명확히 해야 할 부분
- `suggested_text` 필드를 검증 에이전트가 채우면 생성 에이전트가 이 값을 그냥 쓸 가능성이 있다. 필드명 변경 또는 "이 값은 예시이며 생성 에이전트가 재작성해야 함" 명시가 필요하다.
- `ComplianceAgent` 인스턴스 수명을 누가 관리하는지 정해야 한다. 생성 에이전트가 루프를 돌 때마다 새 인스턴스를 만들면 FAIL_MAX가 작동하지 않는다.

### 🤝 다른 팀과 합의해야 할 사항
- DB팀 RAG API: 최소 응답 필드 `requirement_id`, `title`, `keywords`, `section_types`, `source_regulation`, `effective_date`, `evidence_text`
- 생성 에이전트: `DetectionInput.iteration`을 몇 번째 재생성 시도 값으로 채울지 (1-indexed, 0-indexed, 생성 에이전트 내부 카운터 기준인지)
- 오류 처리 ownership: RAG 장애, LLM 장애, JSON 스키마 오류 시 사용자에게 누가 어떤 메시지를 보내는지

### 📞 팀 킥오프 미팅 체크리스트
1. `ComplianceAgent` 인스턴스 수명 / session 관리 방식 확정
2. `DetectionInput.iteration` 값 기준 확정 (생성 에이전트가 몇 번째 시도인지)
3. DB팀 RAG API request/response 스키마 확정
4. `section_type` enum 값 확정 (`"약관"` vs `"TERMS"` vs 기타)
5. `suggested_text` 필드 ownership 확정 (검증팀 제거 vs 생성팀에게 가이드라인으로 제공)
6. FAIL_MAX/FAIL_LOOP 이후 사용자 경험 확정
7. 성능 평가 데이터셋 제공자 및 라벨링 기준 확정

---

## 6. 종합 최종 검토

### 📊 종합 평가 (1-10점)
- **실무 가능성:** 6/10 — 내부 보조 검토 도구로 가능성 있음. 자동 승인 도구로는 audit log, 규정 근거 버전, 현직자 승인 체계가 부족.
- **기술 타당성:** 7/10 — 아키텍처 구조는 합리적. violation_id 버그, IterationTracker 세션 관리, confidence_score 의미화가 해결되어야 신뢰할 수 있음.
- **팀 협업:** 7/10 — 역할 분리는 좋음. 인스턴스 수명, iteration 기준, API 스키마 세부 합의 필요.
- **성공 가능성:** 6/10 — 6주 데모 MVP는 가능. F1 90%, Precision 95%는 라벨 데이터 없이 달성 어렵고, 현재 버그가 먼저 해결되어야 측정 자체가 의미 있음.

### 🟢 강점 (5가지)
1. 에이전트 책임 분리가 코드 레벨에서도 지켜지고 있다.
2. Regex/사전/LLM 혼합 전략이 비용과 정확도 균형을 실용적으로 잡는다.
3. 루프 종료 3가지 조건이 구현되어 있다.
4. 테스트 59개가 모두 통과하고 각 모듈을 독립적으로 커버한다.
5. `MOCK_MODE`로 DB팀 API 없이도 개발/테스트가 가능하다.

### 🔴 개선 필요 (5가지)
1. **violation_id 중복 버그** — 패턴 인덱스 기반 ID가 FAIL_LOOP를 오작동시킨다.
2. **IterationTracker 세션 관리** — 인스턴스 수명과 루프 종료 조건이 분리되어야 한다.
3. **section_type 자유 문자열** — 오타 시 필수항목 검사 전체가 silent skip된다.
4. **confidence_score가 항상 1.0** — "위반 없음"과 "충분히 검증됨"의 구분이 없다.
5. **LLM 실패 정책 불일치** — Rule 2(위반 처리) vs Rule 3(skip)의 정책을 통일해야 한다.

### 🚨 반드시 해결해야 할 리스크
1. **violation_id 충돌 → FAIL_LOOP 오작동**  
   → `f"{rule_prefix}_{pattern_idx:03d}_{match_seq:03d}"` 형식으로 변경하고, FAIL_LOOP는 `(rule_type, normalized_text_fingerprint)` 기반으로 판단한다.
2. **ComplianceAgent 인스턴스 수명 미정의 → FAIL_MAX 작동 불가**  
   → `session_id` 기반으로 `IterationTracker`를 외부에서 주입하거나, API 계층에서 세션을 관리한다.
3. **section_type silent skip → 필수항목 검사 무력화**  
   → Enum 또는 `Literal` 타입으로 강제하고, 알 수 없는 값 입력 시 `ERROR_UNSUPPORTED_SECTION_TYPE`을 반환한다.

### ✨ 최종 권장사항
- **우선순위 1:** violation_id 고유성 수정 (버그 → 테스트 실패로 바꾸어 안전망 확보)
- **우선순위 2:** section_type Enum 강제 + IterationTracker DI 리팩토링
- **우선순위 3:** 라벨링 테스트셋과 현직자 리뷰 기준 확보 후 F1/Precision 목표 재산정

### 📋 팀 킥오프 미팅 합의 사항 Top 5
1. `ComplianceAgent` 인스턴스 수명 / session 관리 방식
2. `DetectionInput.iteration` 값 기준 (생성 에이전트 기준 vs 트래커 기준)
3. DB팀 RAG API 스키마와 장애 fallback 정책
4. 금지어/주관표현 사전 owner와 버전 관리 방식
5. 성능 평가 데이터셋 제공 주체와 라벨링 기준

### 💬 현직자에게 꼭 물어봐야 할 질문 Top 3
1. 4세대 실손 약관 심사에서 가장 자주 지적되는 표현과 필수항목 누락 유형은 무엇인가?
2. 보험사 내부 금지어 기준이 금감원 공개 기준과 다를 때 우선순위는?
3. 자동 검증 결과를 준법감시 담당자가 신뢰하려면 어떤 근거 정보가 최소한 필요한가?

---

## 코드 기반 버그 요약 (신규 발견)

| 버그 | 위치 | 영향 | 우선순위 |
|------|------|------|----------|
| violation_id 패턴 인덱스 기반 중복 | `overstatement_detector.py:59` | FAIL_LOOP false positive | 🔴 CRITICAL |
| IterationTracker 인스턴스 수명 미정의 | `compliance_agent.py:28` | FAIL_MAX 미작동 가능 | 🔴 CRITICAL |
| section_type 자유 문자열 → silent skip | `missing_req_detector.py:107` | 필수항목 검사 무력화 | 🔴 CRITICAL |
| confidence_score 항상 1.0 | `confidence_calculator.py:18` | 신뢰도 지표 무의미 | 🟡 HIGH |
| LLM 실패 정책 Rule 2 vs 3 불일치 | `subjective_detector.py:133` vs `contradiction_detector.py:132` | 탐지 일관성 저하 | 🟡 HIGH |
| suggested_text가 placeholder | `feedback_builder.py:43` | 생성 에이전트 혼동 가능 | 🟡 HIGH |
