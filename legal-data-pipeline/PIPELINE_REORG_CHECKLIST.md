# Pipeline Reorg Checklist (Safe Mode)

Last updated: 2026-05-28

## 1) 원칙

- 기존 데이터 파이프라인 workflow 동작을 깨지 않는다.
- 핵심 운영 스크립트 경로(`python src/...`)는 호환 유지한다.
- 큰 일괄 변경 대신 소규모 단계 변경으로 진행한다.

## 2) 완료된 구조 정리

- `src/collectors/` 생성 및 수집 스크립트 본체 이동
- `src/parsers/` 생성 및 파싱 스크립트 본체 이동
- `src/builders/` 생성 및 빌드 스크립트 본체 이동
- `src/tools/` 생성 및 점검/디버그 스크립트 이동
- `src/legacy/chroma/` 생성 및 Chroma 레거시 이동

## 3) 호환성 유지 방식

- 기존 `src/*.py` 파일은 래퍼(stub)로 유지
- `__main__` 실행 시: `runpy.run_module(..., run_name=\"__main__\")`
- import 시: `from tools.<module> import *` 등 재노출

이 방식으로 기존 명령/참조를 유지:

```cmd
python src/collect_legal_api.py
python src/collect_legal_body.py
python src/parse_external_docs.py
python src/build_retrieval_registry.py
```

## 4) 운영 설정/보안 관련 반영

- `.gitignore` 강화:
  - `.venv/`
  - `airflow/logs/`
  - `*.sql`
  - `*.dump`
- workflow timeout 정합화:
  - `.github/workflows/refresh-neon-db.yml`
  - `timeout-minutes: 180`
- `DB_CONNECTION_GUIDE.md`의 `agent_reader` 실제 비밀번호 표기는 사용자 요청에 따라 유지

## 5) requirements 정리

- 기존 동작 유지: `requirements.txt` 유지
- 운영 코어 참고: `requirements-core.txt`
- 레거시 참고: `requirements-legacy-chroma.txt`

## 6) 다음 안전 단계

- 필요 시 `requirements.txt`에서 `chromadb` 제거를 검토하되, 제거 전 레거시 사용 여부를 팀 내부에서 확정
- `scan_imports.py`와 같은 임시 스크립트는 최종 확인 후 정리
