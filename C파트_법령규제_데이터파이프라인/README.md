# C파트 법령·규제 데이터 파이프라인 공유본

## 1. 프로젝트 개요

본 공유본은 실손의료보험 약관·상품설명서 검토에 필요한 법령·규제 데이터를 수집하고, 이를 검색 가능한 형태로 구조화하기 위한 C 파트 산출물입니다.

주요 작업은 다음과 같습니다.

- 국가법령정보 API 기반 법령·행정규칙 수집
- 법령 본문 및 조문 단위 구조화
- 별표·서식 데이터 저장
- 외부 PDF/HWP 기준자료 파싱
- 검색 후보 데이터 구축
- Vector DB 저장용 데이터 구성
- Airflow 기반 주기적 수집·갱신 구조 구성

## 2. 폴더 구성

```text
C파트_법령규제_데이터파이프라인_공유본/
│
├─ README.md
├─ .env.example
├─ .gitignore
│
├─ 01_수집대상_인벤토리/
│   └─ legal_inventory.xlsx
│
├─ 02_외부기준자료/
│   ├─ EXT_0001_금융광고규제가이드라인.pdf
│   ├─ EXT_0002_손해사정_모범규준.pdf
│   └─ EXT_0003_손해사정_공정성제고_보도자료.hwp
│
├─ 03_수집_구조화_코드/
│   └─ src/
│
├─ 04_PostgreSQL_실행설정/
│   ├─ docker-compose.yml
│   └─ requirements.txt
│
└─ 05_Airflow_자동갱신설정/
    ├─ docker-compose-airflow.yml
    ├─ requirements-airflow.txt
    └─ dags/
```

## 3. 주요 산출물 설명

| 구분 | 위치 | 설명 |
|---|---|---|
| 수집 대상 인벤토리 | `01_수집대상_인벤토리/legal_inventory.xlsx` | 법령·규제·외부 기준자료 수집 대상 목록입니다. |
| 외부 기준자료 | `02_외부기준자료/` | 금융광고규제 가이드라인, 손해사정 관련 기준자료입니다. |
| 수집·구조화 코드 | `03_수집_구조화_코드/src/` | 법령 API 수집, 법령 본문 수집, 외부자료 파싱, 검색 후보 생성 코드입니다. |
| PostgreSQL 실행 설정 | `04_PostgreSQL_실행설정/` | PostgreSQL 실행 및 Python 패키지 설정 파일입니다. |
| Airflow 자동 갱신 설정 | `05_Airflow_자동갱신설정/` | 법령 데이터 자동 갱신을 위한 Airflow 설정 파일입니다. |

## 4. 주요 스크립트 설명

| 파일명 | 역할 |
|---|---|
| `collect_legal_api.py` | 국가법령정보 API를 통해 법령·행정규칙 메타데이터를 수집합니다. |
| `collect_legal_body.py` | 법령 본문을 수집하고 조문·별표·서식 단위로 저장합니다. |
| `parse_external_docs.py` | PDF/HWP 외부 기준자료를 파싱합니다. |
| `build_retrieval_registry.py` | 법령 조문, 별표·서식, 외부 기준자료를 검색 후보 데이터로 통합합니다. |
| `seed_risk_query_expansion.py` | 위험표현 확장검색 사전을 생성합니다. |
| `upsert_chroma_vectors.py` | 검색 후보 데이터를 Vector DB에 저장합니다. |
| `check_vector_status.py` | Vector DB 적재 상태를 확인합니다. |
| `query_chroma_vectors.py` | Vector DB 검색 테스트를 수행합니다. |

## 5. 실행 전 준비사항

실행 전 다음 항목이 필요합니다.

- Python 가상환경
- Docker Desktop
- PostgreSQL Docker 컨테이너
- 국가법령정보 API Key
- `.env` 파일 설정

`.env.example` 파일을 참고하여 실제 실행 환경에서는 `.env` 파일을 별도로 생성해야 합니다.

## 6. PostgreSQL 실행 개요

PostgreSQL 실행 설정 파일 위치는 다음과 같습니다.

```text
04_PostgreSQL_실행설정/docker-compose.yml
```

실행 예시는 다음과 같습니다.

```bash
docker compose up -d
```

기본 설정 예시는 다음과 같습니다.

| 항목 | 값 |
|---|---|
| DB 이름 | `silson_legal_db` |
| 사용자 | `silson` |
| 비밀번호 | `silson_pw` |
| Host Port | `5433` |
| Container Port | `5432` |

## 7. 데이터 수집 및 구조화 흐름

전체 처리 흐름은 다음과 같습니다.

```text
수집 대상 인벤토리 확인
→ 국가법령정보 API 수집
→ 법령 본문 수집
→ 조문·별표·서식 저장
→ 외부 기준자료 파싱
→ 검색 후보 데이터 생성
→ 위험표현 검색 사전 생성
→ Vector DB 적재
```

## 8. Airflow 자동 갱신 구조

Airflow 설정 위치는 다음과 같습니다.

```text
05_Airflow_자동갱신설정/
```

주요 DAG 파일은 다음과 같습니다.

```text
05_Airflow_자동갱신설정/dags/silson_legal_data_pipeline_dag.py
```

Airflow의 역할은 법령·규제 데이터를 주기적으로 수집하고 DB를 갱신하는 것입니다.

| 항목 | 내용 |
|---|---|
| 실행 주기 | 매주 월요일 03:00 |
| 실행 방식 | 자동 실행 및 수동 실행 가능 |
| 주요 작업 | 법령 API 수집, 본문 수집, 외부자료 파싱, 검색 후보 데이터 갱신 |

## 9. 현재 구축 결과 요약

| 항목 | 결과 |
|---|---:|
| 전체 수집 후보 | 58건 |
| API 수집 대상 | 42건 |
| 외부 기준자료 | 3건 |
| 법령·규정 문서 | 42건 |
| 조문 데이터 | 6,290건 |
| 별표·서식 데이터 | 559건 |
| 외부 기준자료 검색 단위 | 32건 |
| 총 검색 후보 데이터 | 4,639건 |

## 10. 공유 제외 대상

다음 항목은 보안 및 용량 문제로 공유 대상에서 제외했습니다.

```text
.venv/
.env
airflow/.env
airflow/logs/
data/vector_store/
__pycache__/
Docker volume 관련 파일
API Key
```

## 11. 참고사항

본 공유본에는 실제 API Key가 포함되어 있지 않습니다.

실행을 위해서는 `.env.example`을 참고하여 `.env` 파일을 별도로 생성해야 합니다.

Vector DB 저장소는 용량 문제로 공유 대상에서 제외했으며, 필요 시 `upsert_chroma_vectors.py`를 통해 재생성할 수 있습니다.
