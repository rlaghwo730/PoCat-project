# 🏥 실손의료보험 약관 초안 작성 AI 에이전트

> RAG + Multi-Agent 기반 실손의료보험 약관/상품설명서/사업방법서 자동 생성 시스템

---

## 📌 프로젝트 개요

보험사 담당자가 수동으로 작성하던 **실손의료보험 약관 초안**을 AI 에이전트가 자동으로 생성하는 시스템입니다.

- **기존 3사(삼성화재·DB손해보험·현대해상) 약관 데이터**를 RAG로 참조하여 새로운 약관 초안 생성
- **법률/규제 자동 검토** 후 위반 사항 발견 시 자동 재생성 (최대 3회)
- **약관 / 상품설명서 / 사업방법서** 3가지 문서 동시 생성

---

## 👥 팀 구성 (PoCat 5팀)

| 역할 | 담당 |
|---|---|
| Generation Agent (약관 생성/수정) | 가 |
| Compliance Agent (법률/규제 검토) | 나 |
| Orchestrator/Supervisor (에이전트 조율) | 나 |
| DB 구축 (법률/규제 데이터) | 다 |

---

## 🛠 기술 스택

| 구분 | 기술 |
|---|---|
| **LLM** | Ollama (qwen2.5:14b) |
| **RAG** | ChromaDB + LangChain |
| **임베딩** | Upstage Solar Embedding |
| **벡터 DB** | Neon PostgreSQL + pgvector |
| **에이전트 프레임워크** | LangChain + 커스텀 Orchestrator |
| **모니터링** | Langfuse |
| **UI** | Streamlit |
| **언어** | Python 3.11 |

---

## 🏗 시스템 아키텍처

```
사용자 입력 (Streamlit UI)
        ↓
Orchestrator (슈퍼바이저)
    ├── 1. 요청 검증 (request_handler)
    ├── 2. 작업 계획 수립 (planner)
    ├── 3. 작업 분배 (dispatcher)
    │       ├── GenerationAgent → 약관 초안 생성
    │       └── ComplianceAgent → 법률/규제 검토
    ├── 4. 결과 집계 (aggregator)
    └── 5. 최종 보고 (reporter)
        ↓
결과 출력 (약관 / 상품설명서 / 사업방법서)
```

---

## 📊 데이터베이스 구성

### ChromaDB (로컬 벡터 스토어)
- `일반_약관_3사통합.json` (621개 청크)
- `일반_사업방법서_3사통합.json` (55개 청크)
- `일반_상품요약서_3사통합.json` (131개 청크)
- 총 **1,114개 청크** 임베딩

### Neon PostgreSQL + pgvector (클라우드)
- 법률/규제 데이터 (`legal`, `insurance_cited_law`)
- 보험 약관 원문 (`insurance_policy`)
- 관련 법령 첨부 (`legal_attachment`)
- 외부 참고자료 (`external_reference`)

---

## ⚙️ 주요 기능

### 1. 약관 초안 생성
- 3사(삼성화재/DB손해보험/현대해상) 선택 → 보험사별 기본값 자동 설정
- 일반/유병력자 실손의료비보험 선택
- 기본 보장종목, 비급여 특약, 3대 비급여 선택
- 담보별 보장한도 설정

### 2. 법률/규제 자동 검토
- OVERSTATEMENT (과장 표현) 탐지
- SUBJECTIVE (주관적 표현) 탐지
- CONTRADICTION (모순) 탐지
- FORBIDDEN_WORD (금지어) 탐지
- MISSING_REQUIREMENT (필수 기재사항 누락) 탐지

### 3. 자동 재생성
- 위반 사항 발견 시 피드백 기반 자동 재생성 (최대 3회)
- 3회 후에도 미통과 시 수동 검토 안내

### 4. 모니터링
- Langfuse를 통한 LLM 호출 추적
- Orchestrator 실행 흐름 시각화

---

## 🚀 실행 방법

### 로컬 실행

```bash
# 1. 저장소 클론
git clone https://github.com/rlaghwo730/PoCat-project.git
cd PoCat-project

# 2. 가상환경 생성 및 활성화
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Mac/Linux

# 3. 패키지 설치
pip install -r requirements.txt
pip install -r generation_agent/requirements.txt
pip install anthropic psycopg2-binary langchain-ollama

# 4. Ollama 설치 및 모델 다운로드
# https://ollama.com/download 에서 설치 후
ollama pull qwen2.5:14b

# 5. 환경변수 설정 (.env 파일 생성)
UPSTAGE_API_KEY=your_key
LANGFUSE_PUBLIC_KEY=your_key
LANGFUSE_SECRET_KEY=your_key
LANGFUSE_HOST=https://cloud.langfuse.com
GENERATION_AGENT_DIR=./generation_agent
DB_API_URL=your_postgresql_url

# 6. ChromaDB 임베딩 (최초 1회)
cd generation_agent
python rag/document_loader.py
cd ..

# 7. 실행
streamlit run app.py
```

### Streamlit Cloud
- URL: https://pocat-project-dw7vwgxosskzwmy4akakvb.streamlit.app

---

## 📁 프로젝트 구조

```
PoCat-project/
├── app.py                          # 루트 UI (Orchestrator 기반)
├── orchestrator/                   # 슈퍼바이저
│   ├── orchestrator.py             # 메인 진입점
│   ├── adapters.py                 # 에이전트 간 데이터 변환
│   ├── core/
│   │   ├── request_handler.py      # 요청 검증
│   │   ├── planner.py              # 작업 계획
│   │   ├── dispatcher.py           # 작업 분배
│   │   ├── aggregator.py           # 결과 집계
│   │   └── reporter.py             # 최종 보고
│   └── data/
│       ├── ui_config.json          # UI 폼 설정
│       └── input_schema.json       # 기본값 스키마
├── generation_agent/               # 약관 생성 에이전트
│   ├── agents/generation_agent.py  # LLM 기반 약관 생성
│   ├── rag/document_loader.py      # ChromaDB 로더
│   └── data/                       # 3사 통합 JSON
├── compliance_agent/               # 법률 검토 에이전트
│   ├── compliance_agent.py
│   ├── detection_engine/           # 위반 탐지 엔진
│   ├── models/                     # 데이터 모델
│   └── iteration_controller/       # 반복 제어
└── requirements.txt
```
