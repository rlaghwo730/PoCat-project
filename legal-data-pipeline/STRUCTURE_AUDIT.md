# legal-data-pipeline Structure Audit (Phase 1)

Last updated: 2026-05-28

## 1. 운영 유지 대상 (핵심 실행 경로)

- `src/load_inventory.py`
- `src/collect_legal_api.py`
- `src/collect_legal_body.py`
- `src/parse_external_docs.py`
- `src/build_retrieval_registry.py`
- `src/integrated/build_unified_retrieval_chunk.py`
- `src/integrated/backfill_source_urls.py`
- `src/integrated/upsert_pgvector_embeddings.py`
- `src/check_vector_status.py`
- `.github/workflows/refresh-neon-db.yml`

## 2. 정리 후보 (운영 워크플로우 미사용)

- 레거시 ChromaDB 스크립트:
  - `src/upsert_chroma_vectors.py`
  - `src/query_chroma_vectors.py`
- 실험/디버그성 스크립트:
  - `src/collect_legal_body_sample.py`
  - `src/debug_admrul_split.py`
  - `src/inspect_admrul_body.py`
  - `src/inspect_inventory_excel.py`
  - `src/diagnose_legal_documents.py`
- 보조/탐색성 스크립트:
  - `src/search_retrieval_registry.py`
  - `src/search_expanded_registry.py`
  - `src/create_review_finding_from_query.py`
  - `src/seed_risk_query_expansion.py`

## 3. 이번 라운드 반영 사항 (동작 무영향)

- `.gitignore` 보강:
  - `.venv/`
  - `airflow/logs/`
  - `*.sql`
  - `*.dump`
- 루트 잡파일 정리:
  - `python` (0B) 삭제
  - `notepad` (0B) 삭제
  - `py_files.txt` 삭제
- GitHub Actions timeout 정합화:
  - `timeout-minutes: 60` -> `timeout-minutes: 180`

## 4. 명시적 유지 정책

- `DB_CONNECTION_GUIDE.md`의 `agent_reader` 실제 비밀번호 표기는 사용자 요청에 따라 유지한다.
- 현재 Neon PostgreSQL + pgvector 운영 구조를 유지한다.
- 핵심 파이프라인 실행 순서/엔트리포인트 경로는 변경하지 않는다.

## 5. 다음 단계 (안전 리팩토링 제안)

1. `src/` 하위에 `collectors/`, `parsers/`, `builders/`, `utils/` 디렉터리를 먼저 생성한다.
2. 모듈 이동은 한 번에 하지 않고, 파일 1~2개씩 이동 + 기존 경로 래퍼(stub) 유지 방식으로 진행한다.
3. 각 이동 후 workflow 경로 기준으로 import/실행 검증을 수행한다.


## 6. Phase 2 (무중단 구조 재배치)

- 이동 대상:
  - `src/collect_legal_api.py` -> `src/collectors/collect_legal_api.py`
  - `src/collect_legal_body.py` -> `src/collectors/collect_legal_body.py`
  - `src/parse_external_docs.py` -> `src/parsers/parse_external_docs.py`
  - `src/build_retrieval_registry.py` -> `src/builders/build_retrieval_registry.py`
- 호환성 유지:
  - 기존 4개 경로 파일은 래퍼(stub)로 유지하여 workflow 경로 변경 없이 기존 호출을 그대로 지원
- 패키지 스캐폴딩:
  - `src/collectors/__init__.py`
  - `src/parsers/__init__.py`
  - `src/builders/__init__.py`

## 7. Phase 3 (Legacy Chroma 분리, 호환 유지)

- 이동 대상:
  - `src/upsert_chroma_vectors.py` -> `src/legacy/chroma/upsert_chroma_vectors.py`
  - `src/query_chroma_vectors.py` -> `src/legacy/chroma/query_chroma_vectors.py`
- 호환성 유지:
  - 기존 경로(`src/upsert_chroma_vectors.py`, `src/query_chroma_vectors.py`)는 래퍼(stub)로 유지
  - 기존 실행 커맨드와 import 경로를 깨지 않도록 유지
- 패키지 스캐폴딩:
  - `src/legacy/__init__.py`
  - `src/legacy/chroma/__init__.py`

## 8. Phase 4 (Tools 정리, 호환 유지)

- 신규 디렉터리:
  - `src/tools/`
- 이동 대상(진단/탐색/디버그):
  - `check_active_sources.py`
  - `check_external_docs.py`
  - `check_inventory.py`
  - `check_legal_body.py`
  - `check_legal_documents.py`
  - `check_review_findings.py`
  - `check_tables.py`
  - `debug_admrul_split.py`
  - `diagnose_legal_documents.py`
  - `inspect_admrul_body.py`
  - `inspect_inventory_excel.py`
  - `search_retrieval_registry.py`
  - `search_expanded_registry.py`
- 호환성 유지:
  - 기존 경로 파일은 `runpy.run_module("tools.<module>", run_name="__main__")` 래퍼로 유지
  - 기존 `python src/<file>.py` 호출 방식 유지

## 9. Phase 5 (Requirements 정리, 실행 영향 없음)

- 기존 `requirements.txt`는 그대로 유지 (기존 설치/CI 동작 보존)
- 보조 파일 추가:
  - `requirements-core.txt` (pgvector 운영 코어 기준)
  - `requirements-legacy-chroma.txt` (legacy Chroma 실행 시 선택 설치)
- import 호환 보강:
  - `create_review_finding_from_query.py`의 `from search_expanded_registry import ...`가 유지되도록, 래퍼는 `__main__` 실행 경로와 import 경로를 분기해 동작
