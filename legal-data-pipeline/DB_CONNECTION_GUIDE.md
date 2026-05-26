\# Neon PostgreSQL 공유 DB 연결 가이드



\## 1. 목적



팀원은 로컬 DB, Docker, 데이터 적재 과정을 실행하지 않고  

Neon PostgreSQL 공유 DB에 직접 연결해서 통합 법령·약관 데이터를 조회할 수 있습니다.



이 DB는 읽기 전용 계정으로 공유됩니다.



\---



\## 2. DB 접속 정보



```text

DB Type  : PostgreSQL

Host     : ep-red-smoke-aol741au.c-2.ap-southeast-1.aws.neon.tech

Port     : 5432

Database : neondb

User     : agent\_reader

Password : AgentRead\_2026\_Strong!

SSL mode : require

```



`agent\_reader`는 읽기 전용 계정입니다.



가능한 작업:



```text

SELECT 조회

```



불가능한 작업:



```text

INSERT

UPDATE

DELETE

CREATE TABLE

DROP TABLE

```



\---



\## 3. 필요한 패키지 설치



Python 코드에서 DB에 연결하려면 아래 패키지를 설치합니다.



```bash

pip install psycopg2-binary

```



\---



\## 4. Python 코드에서 DB 연결



프로젝트 코드 안에서 아래 함수를 사용하면 됩니다.



```python

import psycopg2





def get\_connection():

&#x20;   conn = psycopg2.connect(

&#x20;       host="ep-red-smoke-aol741au.c-2.ap-southeast-1.aws.neon.tech",

&#x20;       port=5432,

&#x20;       dbname="neondb",

&#x20;       user="agent\_reader",

&#x20;       password="AgentRead\_2026\_Strong!",

&#x20;       sslmode="require",

&#x20;   )

&#x20;   return conn

```



\---



\## 5. 연결 확인 코드



아래 코드를 실행해서 DB 연결 여부를 확인합니다.



```python

import psycopg2





conn = psycopg2.connect(

&#x20;   host="ep-red-smoke-aol741au.c-2.ap-southeast-1.aws.neon.tech",

&#x20;   port=5432,

&#x20;   dbname="neondb",

&#x20;   user="agent\_reader",

&#x20;   password="AgentRead\_2026\_Strong!",

&#x20;   sslmode="require",

)



cur = conn.cursor()



cur.execute("""

&#x20;   SELECT COUNT(\*)

&#x20;   FROM unified\_retrieval\_chunk

&#x20;   WHERE is\_active = TRUE;

""")



count = cur.fetchone()\[0]

print("active chunk count:", count)



cur.close()

conn.close()

```



정상 출력 기준:



```text

active chunk count: 4954

```



\---



\## 6. 주요 테이블



| 테이블/View | 설명 |

|---|---|

| `unified\_retrieval\_chunk` | 법령, 감독규정, 외부자료, 보험약관 본문과 출처 정보가 통합된 테이블 |

| `unified\_chunk\_embedding` | pgvector embedding 저장 테이블 |

| `agent\_retrieval\_view` | Agent 조회용 통합 View |

| `legal\_article` | 법령/감독규정 조문 원천 테이블 |

| `insurance\_text\_unit` | 보험약관 구조화 원천 테이블 |



\---



\## 7. 기본 조회 대상 테이블



Agent 구현 시 우선 아래 테이블을 조회하면 됩니다.



```text

unified\_retrieval\_chunk

```



주요 컬럼:



| 컬럼 | 설명 |

|---|---|

| `source\_domain` | 데이터 출처 유형 |

| `citation\_label` | Agent 응답에 표시할 근거 라벨 |

| `source\_url` | 원문 또는 출처 URL |

| `document\_name` | 문서명 |

| `document\_type` | 문서 유형 |

| `section` | 문서 내 구역 |

| `article\_no` | 조문 번호 |

| `title` | 조항 제목 |

| `content` | 본문 |

| `metadata\_json` | 추가 메타데이터 |

| `is\_active` | 활성 데이터 여부 |



\---



\## 8. source\_domain 구분



| source\_domain | 의미 |

|---|---|

| `insurance\_policy` | 보험사 실손보험 약관 조항 |

| `insurance\_cited\_law` | 보험 약관 내부 인용 법규 |

| `legal` | 법령/감독규정 조문 |

| `legal\_attachment` | 별표/별지/첨부 기준 |

| `external\_reference` | 외부 가이드라인/보도자료 |



\---



\## 9. 기본 조회 SQL



```sql

SELECT

&#x20;   source\_domain,

&#x20;   citation\_label,

&#x20;   source\_url,

&#x20;   document\_name,

&#x20;   article\_no,

&#x20;   title,

&#x20;   content

FROM unified\_retrieval\_chunk

WHERE is\_active = TRUE

LIMIT 10;

```



\---



\## 10. 약관 데이터 조회 SQL



```sql

SELECT

&#x20;   citation\_label,

&#x20;   source\_url,

&#x20;   document\_name,

&#x20;   section,

&#x20;   article\_no,

&#x20;   title,

&#x20;   content

FROM unified\_retrieval\_chunk

WHERE is\_active = TRUE

&#x20; AND source\_domain = 'insurance\_policy';

```



\---



\## 11. 법령/감독규정 데이터 조회 SQL



```sql

SELECT

&#x20;   citation\_label,

&#x20;   source\_url,

&#x20;   document\_name,

&#x20;   article\_no,

&#x20;   title,

&#x20;   content

FROM unified\_retrieval\_chunk

WHERE is\_active = TRUE

&#x20; AND source\_domain IN ('legal', 'legal\_attachment', 'insurance\_cited\_law');

```



\---



\## 12. pgvector 검색용 테이블



semantic search를 구현할 경우 아래 두 테이블을 조인해서 사용합니다.



```text

unified\_retrieval\_chunk

unified\_chunk\_embedding

```



pgvector 검색 SQL 구조:



```sql

SELECT

&#x20;   r.source\_domain,

&#x20;   r.citation\_label,

&#x20;   r.source\_url,

&#x20;   r.document\_name,

&#x20;   r.document\_type,

&#x20;   r.article\_no,

&#x20;   r.title,

&#x20;   r.content,

&#x20;   1 - (e.embedding <=> %s::vector) AS similarity

FROM unified\_chunk\_embedding e

JOIN unified\_retrieval\_chunk r

&#x20; ON e.unified\_chunk\_id = r.unified\_chunk\_id

WHERE r.is\_active = TRUE

&#x20; AND e.embedding\_model = %s

ORDER BY e.embedding <=> %s::vector

LIMIT %s;

```



`%s::vector`에는 Agent 코드에서 생성한 query embedding을 pgvector 문자열 형식으로 넣습니다.



예시 형식:



```text

\[0.0123,-0.0456,0.0789,...]

```



\---



\## 13. 정리



팀원은 로컬 DB나 Docker를 실행할 필요 없이  

위 Neon PostgreSQL 접속 정보로 직접 DB에 연결하면 됩니다.



Agent 구현 시에는 기본적으로 아래 두 테이블을 사용하면 됩니다.



```text

unified\_retrieval\_chunk

unified\_chunk\_embedding

```



`agent\_retriever.py`는 필수 사용 파일이 아니라 참고용 검색 함수입니다.

