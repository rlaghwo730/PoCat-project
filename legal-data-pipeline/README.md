\## 팀원 사용 방법



본 프로젝트는 Neon PostgreSQL + pgvector 기반 공유 검색 DB에 연결되도록 구성되어 있습니다.



팀원은 별도의 로컬 DB 구축, Docker 실행, 데이터 적재, API 키 설정 없이 바로 검색 함수를 사용할 수 있습니다.



\### 1. 패키지 설치



```bash

pip install -r requirements.txt

```



\### 2. 검색 테스트



```bash

python src/integrated/agent\_retriever.py "전액 보장이라는 표현은 소비자에게 오인 가능성이 있는지 검토"

```



또는:



```bash

python src/integrated/agent\_retriever.py "실손의료보험 비급여 보장 한도와 자기부담금"

```



\### 3. Python 코드에서 사용



```python

from src.integrated.agent\_retriever import search\_for\_review



result = search\_for\_review(

&#x20;   query="전액 보장이라는 표현은 소비자에게 오인 가능성이 있는지 검토",

&#x20;   query\_type="misleading\_expression",

)



print(result\["policy\_evidence"])

print(result\["legal\_evidence"])

print(result\["external\_evidence"])

```



\### 4. 반환 구조



```python

{

&#x20;   "query": "...",

&#x20;   "query\_type": "...",

&#x20;   "policy\_evidence": \[...],

&#x20;   "legal\_evidence": \[...],

&#x20;   "external\_evidence": \[...],

&#x20;   "all\_evidence": \[...]

}

```



\### 5. source\_domain 설명



| source\_domain | 의미 | 활용 목적 |

|---|---|---|

| insurance\_policy | 보험사 실손보험 약관 조항 | 약관 문구 비교, 보장/면책/한도 확인 |

| insurance\_cited\_law | 보험 약관 내부 인용 법규 | 약관이 직접 인용한 법률 근거 확인 |

| legal | 법령/감독규정 조문 | 금소법, 보험업법, 감독규정 등 규제 근거 확인 |

| legal\_attachment | 별표/별지/첨부 기준 | 세부 기준표, 별표 근거 확인 |

| external\_reference | 외부 가이드라인/보도자료 | 금융광고, 손해사정 모범규준 등 보조 근거 확인 |



\### 6. 주요 DB 테이블



팀원이 직접 SQL을 사용할 경우 아래 테이블을 기준으로 조회하면 됩니다.



| 테이블/View | 설명 |

|---|---|

| agent\_retrieval\_view | Agent 조회용 통합 View |

| unified\_retrieval\_chunk | 법령·약관·외부자료 본문 및 citation/source\_url 저장 |

| unified\_chunk\_embedding | pgvector embedding 저장 테이블 |

| insurance\_text\_unit | 보험사 약관 구조화 데이터 |

| legal\_article | 법령/감독규정 조문 데이터 |

| legal\_attachment | 별표/첨부 기준 데이터 |



\### 7. pgvector 검색 SQL 예시



Agent 구현 팀에서 자체 retrieval 로직을 만들 경우 아래 SQL을 참고할 수 있습니다.



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



`%s::vector`에는 query embedding을 pgvector 문자열 형식으로 넣으면 됩니다.



예:



```text

\[0.0123,-0.0456,0.0789,...]

```

