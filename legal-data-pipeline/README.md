## 팀원 사용 방법

본 프로젝트는 Neon PostgreSQL + pgvector 기반 공유 검색 DB에 연결되도록 구성되어 있다.

팀원은 별도의 로컬 DB 구축, Docker 실행, 데이터 적재 없이 `agent_reader` 계정으로 공유 DB를 조회할 수 있다.

---

### 1. 패키지 설치

```bash
pip install -r requirements.txt
```

---

### 2. DB 연결 테스트

```bash
python src/check_vector_status.py
```

정상 기준은 다음과 같다.

```text
active chunks = embeddings = active joined embeddings
orphan embeddings = 0
```

---

### 3. 검색 함수 테스트

```bash
python src/integrated/agent_retriever.py "전액 보장이라는 표현은 소비자에게 오인 가능성이 있는지 검토"
```

또는:

```bash
python src/integrated/agent_retriever.py "실손의료보험 비급여 보장 한도와 자기부담금"
```

---

### 4. Python 코드에서 사용

```python
from src.integrated.agent_retriever import search_for_review

result = search_for_review(
    query="전액 보장이라는 표현은 소비자에게 오인 가능성이 있는지 검토",
    query_type="misleading_expression",
)

print(result["policy_evidence"])
print(result["legal_evidence"])
print(result["external_evidence"])
```

---

### 5. 반환 구조

```python
{
    "query": "...",
    "query_type": "...",
    "policy_evidence": [...],
    "legal_evidence": [...],
    "external_evidence": [...],
    "all_evidence": [...]
}
```

---

### 6. source_domain 설명

| source_domain | 의미 | 활용 목적 |
|---|---|---|
| insurance_policy | 보험사 실손보험 약관 조항 | 약관 문구 비교, 보장·면책·한도 확인 |
| insurance_cited_law | 보험 약관 내부 인용 법규 | 약관이 직접 인용한 법률 근거 확인 |
| legal | 법령 및 감독규정 조문 | 금소법, 보험업법, 감독규정 등 규제 근거 확인 |
| legal_attachment | 별표, 별지, 첨부 기준 | 세부 기준표 및 별표 근거 확인 |
| external_reference | 외부 가이드라인 및 참고자료 | 금융광고, 손해사정 모범규준 등 보조 근거 확인 |

---

### 7. 주요 DB 테이블

| 테이블/View | 설명 |
|---|---|
| agent_retrieval_view | Agent 조회용 통합 View |
| unified_retrieval_chunk | 법령·약관·외부자료 본문 및 citation/source_url 저장 |
| unified_chunk_embedding | pgvector embedding 저장 테이블 |
| insurance_text_unit | 보험사 약관 구조화 데이터 |
| legal_article | 법령 및 감독규정 조문 데이터 |
| legal_attachment | 별표 및 첨부 기준 데이터 |

---

### 8. pgvector 검색 SQL 예시

Agent 구현 팀에서 자체 retrieval 로직을 만들 경우 아래 SQL을 참고할 수 있다.

```sql
SELECT
    r.source_domain,
    r.citation_label,
    r.source_url,
    r.document_name,
    r.document_type,
    r.article_no,
    r.title,
    r.content,
    1 - (e.embedding <=> %s::vector) AS similarity
FROM unified_chunk_embedding e
JOIN unified_retrieval_chunk r
  ON e.unified_chunk_id = r.unified_chunk_id
WHERE r.is_active = TRUE
  AND e.embedding_model = %s
ORDER BY e.embedding <=> %s::vector
LIMIT %s;
```

`%s::vector`에는 query embedding을 pgvector 문자열 형식으로 넣는다.

예시:

```text
[0.0123,-0.0456,0.0789,...]
```

---

### 9. 권한 안내

팀원용 계정인 `agent_reader`는 read-only 계정이다.

가능한 작업:

- SELECT
- 검색 데이터 조회
- source_domain별 데이터 확인
- citation_label 및 source_url 확인

불가능한 작업:

- INSERT
- UPDATE
- DELETE
- CREATE TABLE
- DROP TABLE

DB 접속 정보는 `DB_CONNECTION_GUIDE.md`를 참고한다.