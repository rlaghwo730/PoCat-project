# 실손의료보험 약관 초안 작성 에이전트

RAG(Retrieval-Augmented Generation) 기반으로 실손의료보험 약관 초안을 자동 생성하는 AI 에이전트입니다.

## 주요 기능

- 기존 약관 PDF 문서를 벡터 DB(ChromaDB)에 인덱싱
- Upstage Solar 임베딩으로 의미 기반 검색
- Claude(Anthropic) LLM을 활용한 약관 초안 생성
- Streamlit 기반 웹 UI

## 프로젝트 구조

```
insurance_clause_agent/
├── agents/        # LLM 에이전트 로직
├── rag/           # 문서 로드, 청킹, 벡터 저장소
├── data/          # 원본 PDF 및 참고 문서 (git 제외)
├── utils/         # 공통 유틸리티
├── tests/         # 테스트 코드
├── app.py         # Streamlit 앱 진입점
├── requirements.txt
└── .env.example
```

## 설치 및 실행

```bash
# 1. 가상환경 생성 및 활성화
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # macOS/Linux

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경변수 설정
copy .env.example .env
# .env 파일에 API 키 입력

# 4. 앱 실행
streamlit run app.py
```

## 환경변수

| 키 | 설명 |
|---|---|
| `UPSTAGE_API_KEY` | Upstage Solar 임베딩 API 키 |
| `ANTHROPIC_API_KEY` | Anthropic Claude API 키 |
