# 🏥 실손의료보험 약관 초안 작성 AI 에이전트

RAG + LangManus(LangGraph) 기반 실손의료보험 약관/상품설명서/사업방법서 자동 생성 시스템

## 📌 프로젝트 개요
보험사 담당자가 수동으로 작성하던 실손의료보험 약관 초안을 AI 에이전트가 자동으로 생성하는 시스템입니다.

- 기존 3사(삼성화재·DB손해보험·현대해상) 약관 데이터를 RAG로 참조하여 약관 초안 생성
- 법률/규제 자동 검토 후 위반 시 해당 부분만 부분 수정 (최대 3회)
- 약관 / 상품설명서 / 사업방법서 3가지 문서 동시 생성

## 👥 팀 구성 (PoCat 5팀)

| 역할 | 담당 |
|---|---|
| Generation Agent (약관 생성) | 가 |
| Compliance Agent (법률 검토) | 나 |
| Edit Agent (부분 수정) | 가 |
| Supervisor/Graph 구성 | 나 |
| DB 구축 (법률/규제 데이터) | 다 |

## 🛠 기술 스택

| 구분 | 기술 |
|---|---|
| LLM | OpenRouter (llama-3.1-8b:free / claude-3.5-sonnet / gpt-4o) |
| Fallback LLM | Upstage Solar (solar-pro) |
| 에이전트 프레임워크 | LangGraph (StateGraph) |
| RAG | ChromaDB + LangChain |
| 임베딩 | Upstage Solar Embedding |
| 벡터 DB | Neon PostgreSQL + pgvector |
| 백엔드 | FastAPI |
| 모니터링 | Langfuse |
| UI | Streamlit |
| 언어 | Python 3.11 |

## 🏗 시스템 아키텍처

```
frontend/app.py (Streamlit UI)
    ↓ HTTP POST /generate
backend/main.py (FastAPI)
    ↓
LangGraph StateGraph
    ↓
coordinator → planner → supervisor
                            ↓
                   generation (RAG + LLM으로 약관 생성)
                            ↓
                   compliance (법률/규제 검토)
                            ↓ 위반 시
                       edit (위반 항목 부분 수정)
                            ↓
                          END
```

## 🤖 에이전트 구성

| 에이전트 | LLM 타입 | 역할 |
|---|---|---|
| coordinator | basic | 요청 분석 및 라우팅 |
| planner | basic | 작업 전략 수립 |
| supervisor | supervisor (gpt-4o) | 에이전트 조율 · CONTINUE/STOP 판단 |
| generation | basic | RAG + DB 참조하여 약관 초안 생성 |
| compliance | basic | 5가지 위반 유형 탐지 |
| edit | basic | 위반 항목만 부분 수정 |

## 📊 데이터베이스 구성

### ChromaDB (로컬 벡터 스토어)
- 일반_약관_3사통합.json (621개 청크)
- 일반_사업방법서_3사통합.json (55개 청크)
- 일반_상품요약서_3사통합.json (131개 청크)
- 총 1,114개 청크 임베딩

### Neon PostgreSQL + pgvector (클라우드)
- 법률/규제 데이터, 보험 약관 원문, 관련 법령

## 🚀 실행 방법

### 1. 저장소 클론
```bash
git clone https://github.com/rlaghwo730/PoCat-project.git
cd PoCat-project
```

### 2. 가상환경 생성 및 패키지 설치
```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
pip install -r backend/requirements.txt
```

### 3. 환경변수 설정 (.env 파일)
```
OPENROUTER_API_KEY=your_key      # 필수 (LLM)
UPSTAGE_API_KEY=your_key         # 필수 (임베딩)
LANGFUSE_PUBLIC_KEY=your_key
LANGFUSE_SECRET_KEY=your_key
LANGFUSE_HOST=https://cloud.langfuse.com
DB_API_URL=your_postgresql_url
```

### 4. ChromaDB 임베딩 (최초 1회)
```bash
cd generation_agent
python rag/document_loader.py
cd ..
```

### 5. 백엔드 + 프론트엔드 실행
```bash
# 터미널 1 - 백엔드
python backend/main.py

# 터미널 2 - 프론트엔드
streamlit run frontend/app.py
```

## 📁 프로젝트 구조

```
PoCat-project/
├── frontend/
│   └── app.py                       # Streamlit UI
├── backend/
│   ├── main.py                      # FastAPI 서버 진입점
│   └── src/
│       ├── api/app.py               # POST /generate 엔드포인트
│       ├── graph/
│       │   ├── builder.py           # StateGraph 구성
│       │   ├── nodes.py             # 6개 노드 함수
│       │   └── types.py             # State 공유 메모리
│       ├── agents/
│       │   ├── agents.py            # 에이전트 생성
│       │   └── llm.py               # LLM 분기 (OpenRouter/Upstage)
│       ├── config/agents.py         # AGENT_LLM_MAP
│       ├── prompts/                 # 에이전트별 프롬프트 (6개 md)
│       ├── service/
│       │   └── workflow_service.py  # graph.ainvoke()
│       └── tools/
│           ├── rag_tool.py          # ChromaDB 검색
│           └── db_tool.py           # PostgreSQL 법률 조회
├── generation_agent/                # 약관 생성 에이전트 (재활용)
├── compliance_agent/                # 법률 검토 에이전트 (재활용)
└── data/
    └── legal-data-pipeline/         # 법령 API 연동
```
