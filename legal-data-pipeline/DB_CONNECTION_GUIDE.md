# DB Connection Guide

## 1. 목적

본 문서는 팀원이 실손의료보험 약관 검토 AI Agent 개발 과정에서 공유 DB에 직접 연결하여 법령·약관·외부 참고자료 기반 검색 데이터를 조회하기 위한 가이드이다.

현재 DB 구조는 Neon PostgreSQL + pgvector 기반이다.

ChromaDB는 현재 운영 구조에서 사용하지 않는다.

---

## 2. DB 접속 정보

```text
DB Type  : PostgreSQL
Host     : ep-red-smoke-aol741au.c-2.ap-southeast-1.aws.neon.tech
Port     : 5432
Database : neondb
User     : agent_reader
Password : AgentRead_2026_Strong!
SSL mode : require
```

`agent_reader`는 팀원 조회용 read-only 계정이다.

---

## 3. 패키지 설치

```bash
pip install psycopg2-binary
```

프로젝트 전체 requirements를 설치하는 경우에는 아래 명령을 사용한다.

```bash
pip install -r requirements.txt
```

---

## 4. Python DB 연결 테스트

```python
import psycopg2

conn = psycopg2.connect(
    host="ep-red-smoke-aol741au.c-2.ap-southeast-1.aws.neon.tech",
    port=5432,
    dbname="neondb",
    user="agent_reader",
    password="AgentRead_2026_Strong!",
    sslmode="require",
)

cur = conn.cursor()
cur.execute("SELECT current_user, current_database();")
print(cur.fetchone())

cur.close()
conn.close()
```

정상 출력 예시는 다음과 같다.

```text
('agent_reader', 'neondb')
```

---

## 5. 주요 조회 테이블

| 테이블/View | 설명 |
|---|---|
| agent_retrieval_view | Agent 조회용 통합 View |
| unified_retrieval_chunk | 법령·약관·외부자료 본문 및 citation/source_url 저장 |
| unified_chunk_embedding | pgvector embedding 저장 테이블 |
| insurance_text_unit | 보험사 약관 구조화 데이터 |
| legal_article | 법령 및 감독규정 조문 데이터 |
| legal_attachment | 별표 및 첨부 기준 데이터 |

---

## 6. source_domain 설명

| source_domain | 의미 | 활용 목적 |
|---|---|---|
| insurance_policy | 보험사 실손보험 약관 조항 | 약관 문구 비교, 보장·면책·한도 확인 |
| insurance_cited_law | 보험 약관 내부 인용 법규 | 약관이 직접 인용한 법률 근거 확인 |
| legal | 법령 및 감독규정 조문 | 금소법, 보험업법, 감독규정 등 규제 근거 확인 |
| legal_attachment | 별표, 별지, 첨부 기준 | 세부 기준표 및 별표 근거 확인 |
| external_reference | 외부 가이드라인 및 참고자료 | 금융광고, 손해사정 모범규준 등 보조 근거 확인 |

---

## 7. 통합 chunk 조회 예시

```sql
SELECT
    source_domain,
    citation_label,
    source_url,
    title,
    LEFT(content, 300) AS content_preview
FROM unified_retrieval_chunk
WHERE is_active = TRUE
LIMIT 10;
```

---

## 8. source_domain별 데이터 수 확인

```sql
SELECT
    source_domain,
    COUNT(*) AS chunk_count
FROM unified_retrieval_chunk
WHERE is_active = TRUE
GROUP BY source_domain
ORDER BY source_domain;
```

정상 출력 예시는 다음과 같다.

```text
external_reference
insurance_cited_law
insurance_policy
legal
legal_attachment
```

---

## 9. pgvector embedding 정합성 확인

```sql
SELECT COUNT(*)
FROM unified_retrieval_chunk
WHERE is_active = TRUE;
```

```sql
SELECT COUNT(*)
FROM unified_chunk_embedding;
```

```sql
SELECT COUNT(*)
FROM unified_chunk_embedding e
JOIN unified_retrieval_chunk r
  ON e.unified_chunk_id = r.unified_chunk_id
WHERE r.is_active = TRUE;
```

정상 기준은 다음과 같다.

```text
active chunks = embeddings = active joined embeddings
```

---

## 10. pgvector 검색 SQL 예시

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

예시는 다음과 같다.

```text
[0.0123,-0.0456,0.0789,...]
```

---

## 11. Python에서 샘플 데이터 조회

```python
import psycopg2

conn = psycopg2.connect(
    host="ep-red-smoke-aol741au.c-2.ap-southeast-1.aws.neon.tech",
    port=5432,
    dbname="neondb",
    user="agent_reader",
    password="AgentRead_2026_Strong!",
    sslmode="require",
)

cur = conn.cursor()

cur.execute("""
    SELECT
        source_domain,
        citation_label,
        source_url,
        LEFT(content, 200)
    FROM unified_retrieval_chunk
    WHERE is_active = TRUE
    LIMIT 5;
""")

for row in cur.fetchall():
    print(row)

cur.close()
conn.close()
```

---

## 12. 권한 안내

`agent_reader`는 read-only 계정이다.

가능한 작업은 다음과 같다.

- SELECT
- 통합 chunk 조회
- source_domain별 데이터 확인
- citation_label 및 source_url 확인
- AI Agent 개발용 검색 데이터 조회

불가능한 작업은 다음과 같다.

- INSERT
- UPDATE
- DELETE
- CREATE TABLE
- DROP TABLE

DB owner 계정은 자동화 및 관리 작업에만 사용한다.

---

## 13. 사용 시 주의사항

팀원은 `agent_reader` 계정만 사용한다.

owner 계정 정보는 공유하지 않는다.

GitHub Secrets 값은 공유하지 않는다.

`.env` 파일은 GitHub에 업로드하지 않는다.

AI Agent 개발 시 기본 조회 대상은 다음 두 테이블이다.

- unified_retrieval_chunk
- unified_chunk_embedding

검색 함수 기반 사용은 README.md의 팀원 사용 방법을 참고한다.