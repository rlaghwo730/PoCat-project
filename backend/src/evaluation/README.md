# RAGAS 평가 파이프라인

RAG 시스템의 **검색(retrieval)·답변(generation) 품질**을 점수로 측정하는 독립 실행형 평가 도구입니다.
서비스 흐름(LangGraph)에 연결되는 에이전트가 아니라, **개발자가 따로 돌려보는 평가 스크립트**입니다.

> 기존 `final_validation_agent` 와 동일하게, 지금은 독립 모듈로 두고 나중에 기존 RAG 코드에
> 연결하기 쉽도록 설계했습니다. `builder.py` / `nodes.py` 는 건드리지 않았습니다.

---

## RAGAS 란?

RAGAS(Retrieval-Augmented Generation Assessment)는 RAG 시스템을 자동으로 채점해 주는 평가 프레임워크입니다.
질문에 대해 RAG가 내놓은 **답변**과 그 답변을 만들 때 **검색해 온 문서(context)**, 그리고 **기대 답변(정답)**을
비교해서, "검색을 잘했는지", "답변이 검색 내용에 충실한지" 등을 0~1 점수로 매겨 줍니다.

---

## 파일 구성

```text
backend/src/evaluation/
├─ ragas_evaluator.py        # 평가 메인 스크립트
├─ ragas_test_dataset.json   # 평가용 질문/정답 세트
├─ ragas_results.csv         # 질문별 점수 (실행 후 자동 생성/덮어쓰기)
└─ README.md                 # 이 문서
```

실행하면 추가로 `ragas_results.json`(요약 평균 + 레코드)도 생성됩니다.

---

## 평가가 돌아가는 4단계

```
[1] 테스트셋 로드            ragas_test_dataset.json → (question, ground_truth)
        │
[2] RAG 실행                 각 question → run_rag(question) → (answer, contexts)
        │
[3] RAGAS 평가               evaluate() → 4개 지표 점수 계산
        │
[4] 결과 저장                ragas_results.csv (질문별) + ragas_results.json (요약)
```

---

## 평가 지표 4종 설명

| 지표 | 무엇을 보는가 | 점수가 낮으면 의심할 곳 |
|------|---------------|------------------------|
| **faithfulness** (충실도) | 답변이 검색된 context에 **근거**했는지. 환각(hallucination)이 없는지. | 생성 LLM이 검색 내용을 무시하고 지어냄 → 프롬프트/모델 점검 |
| **answer_relevancy** (답변 적절성) | 답변이 **질문에 맞는** 내용인지. 동문서답이 아닌지. | 질문 의도를 못 잡음 → 프롬프트 점검 |
| **context_precision** (문맥 정밀도) | 검색해 온 문서 중 **관련 있는 것의 비율**. 쓸데없는 문서가 섞이지 않았는지. | 검색이 noise를 많이 가져옴 → top-k 축소, 임베딩/청킹 개선 |
| **context_recall** (문맥 재현율) | 정답에 필요한 근거 문서를 **충분히 검색**했는지. 빠뜨린 게 없는지. | 필요한 문서를 못 찾음 → top-k 확대, 청킹/인덱스 개선 |

기억하기 쉬운 구분:
- **검색 품질** → `context_precision`(군더더기 없나), `context_recall`(빠진 거 없나)
- **답변 품질** → `faithfulness`(검색에 충실한가), `answer_relevancy`(질문에 맞나)

> ⚠️ `faithfulness`, `answer_relevancy`, `context_*` 지표는 내부적으로 **LLM과 임베딩 모델을 호출**해
> 채점합니다. 따라서 평가 실행에는 LLM API 자격증명이 필요합니다(아래 참고).

---

## 사전 준비

### 1) 패키지 설치

```bash
pip install ragas datasets pandas
```

### 2) LLM/임베딩 자격증명 (환경변수)

RAGAS는 채점에 LLM을 사용하므로 키가 필요합니다.
**코드에는 키를 넣지 않습니다.** 터미널 환경변수로만 전달하세요.

```bash
export OPENAI_API_KEY="sk-..."     # 예: OpenAI 사용 시
```

> 다른 LLM(예: OpenRouter, Upstage 등)을 쓰려면 RAGAS의 `llm=`, `embeddings=` 인자에
> 커스텀 모델을 주입해야 합니다. 그 경우 `evaluate_records()` 의 `evaluate(...)` 호출에
> `llm=`, `embeddings=` 를 추가하세요. (RAGAS 문서 참고)

---

## 실행 방법

### 기본 실행

```bash
cd backend/src/evaluation
python ragas_evaluator.py
```

끝나면 `ragas_results.csv`(질문별 점수)와 `ragas_results.json`(평균 요약)이 생성되고,
터미널에 평균 점수가 출력됩니다.

### 옵션

```bash
# 다른 테스트셋/출력 경로 지정
python ragas_evaluator.py \
  --dataset ragas_test_dataset.json \
  --out-csv ragas_results.csv \
  --out-json ragas_results.json

# RAGAS 설치/키 없이 RAG 입력 구조만 점검 (평가 생략)
python ragas_evaluator.py --dry-run
```

`--dry-run` 은 `run_rag()` 결과로 만든 평가 레코드 구조만 JSON으로 덤프합니다.
RAG 연결을 먼저 확인하고 싶을 때 유용합니다.

---

## 핵심: `run_rag()` 를 실제 RAG에 연결하기

현재 `ragas_evaluator.py` 의 `run_rag(question)` 은 **모의(mock) 구현**입니다.
실제 평가를 하려면 이 함수를 기존 RAG 호출 코드로 교체하세요. 반환 형식만 지키면 됩니다.

```python
def run_rag(question: str) -> dict:
    # ... 기존 retriever / RAG agent 호출 ...
    return {
        "answer": "...",                     # 생성된 답변 (str)
        "contexts": ["청크1", "청크2", ...],  # 검색된 문서 (list[str])
    }
```

**연결 예시 ① — retriever + LLM 직접 호출**

```python
from backend.src.rag.retriever import get_retriever
from backend.src.agents.agents import get_generation_llm

def run_rag(question: str) -> dict:
    retriever = get_retriever()
    docs = retriever.invoke(question)
    contexts = [d.page_content for d in docs]
    llm = get_generation_llm()
    answer = llm.invoke(f"문맥:\n{contexts}\n\n질문: {question}").content
    return {"answer": answer, "contexts": contexts}
```

**연결 예시 ② — 이미 RAG 체인/에이전트가 있는 경우**

```python
from backend.src.rag.chain import rag_chain

def run_rag(question: str) -> dict:
    result = rag_chain.invoke({"question": question})
    return {
        "answer": result["answer"],
        "contexts": [d.page_content for d in result["source_documents"]],
    }
```

> `contexts` 는 반드시 **문자열 리스트**여야 합니다. Document 객체가 오면 `.page_content` 로 변환하세요.
> (스크립트 안에서도 한 번 더 안전 변환을 하지만, 가능한 한 호출부에서 맞춰 주는 것이 좋습니다.)

---

## 테스트셋 만들기

`ragas_test_dataset.json` 은 아래 형태의 JSON 배열입니다.

```json
[
  {
    "question": "테스트 질문",
    "ground_truth": "기대 답변"
  }
]
```

- `question`: RAG에 입력할 질문 (필수)
- `ground_truth`: 사람이 작성한 기대 답변. `context_recall` 등 정답 기반 지표에 사용됩니다.

질문은 실제 서비스에서 자주 들어올 법한 것으로, 정답은 약관/표준 문서에 근거해 정확하게 작성하는 것이 좋습니다.
제공된 기본 테스트셋은 실손의료보험 도메인 질문 8개로 구성되어 있습니다.

---

## 결과 해석

- **CSV (`ragas_results.csv`)**: 질문 한 줄마다 4개 지표 점수가 들어갑니다. 어떤 질문에서
  점수가 떨어지는지 개별 확인할 때 봅니다.
- **JSON (`ragas_results.json`)**: 전체 평균(`summary`)과 평가에 쓰인 레코드가 들어갑니다.
  실행 간 평균 점수 추세를 비교할 때 편합니다.

점수는 0~1 사이이며 높을수록 좋습니다. 절대 기준보다는, **개선 작업 전후의 점수 변화**를
비교하는 용도로 쓰는 것이 실용적입니다.

---

## 자주 나는 import 에러 (버전 차이)

RAGAS는 버전에 따라 import 경로와 입력 형식이 자주 바뀝니다. 에러가 나면 아래를 확인하세요.

- **지표 import 실패** → `ragas_evaluator.py` 의 `_load_metrics()` 주석 참고.
  소문자 함수형(`faithfulness`)과 클래스형(`Faithfulness()`) 중 설치 버전에 맞는 쪽으로 바꾸세요.
- **입력 데이터 형식 에러** → `_to_ragas_dataset()` 이 신버전(`EvaluationDataset`)과
  구버전(`datasets.Dataset`)을 자동으로 시도합니다. 그래도 안 되면 설치된 RAGAS 버전 문서를 확인하세요.
- 설치 버전 확인: `pip show ragas`

---

## 나중에 LangGraph에 연결한다면 (선택)

이 모듈은 평가용이라 서비스 흐름에 꼭 넣을 필요는 없습니다. 다만 정기 품질 점검을
자동화하고 싶다면, `run_pipeline(...)` 을 별도 스케줄러나 CI 단계에서 호출하는 방식을 권장합니다.
LangGraph 노드로 넣기보다 **오프라인 배치 평가**로 두는 편이 일반적입니다.
