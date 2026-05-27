# Orchestrator

실손의료보험 약관 초안 작성을 총괄하는 오케스트레이터 에이전트입니다.

생성 에이전트(GenerationAgent)와 법률규제 검증 에이전트(ComplianceAgent)를 조율하여, 약관 초안 생성 → 법규 검증 → 재생성 루프를 실행하고 최종 결과를 반환합니다.

## 처리 흐름

1. **요청 이해** (`request_handler`) — 입력 요청 검증
2. **작업 계획** (`planner`) — 복잡도 판단 및 반복 한도 결정
3. **작업 분배** (`dispatcher`) — 생성 → 검증 → 재생성 루프 실행
4. **결과 종합** (`aggregator`) — 반복별 위반 추이 집계
5. **최종 보고** (`reporter`) — 통과/수동검토/오류 결과와 제안 생성

루프는 `COMPLIANCE_PASSED`(통과) 시 종료하며, 수렴 불가(HARD_LOOP)나 최대 반복 도달(FAIL_MAX) 시 조기 종료합니다. 최종 상태는 `COMPLIANCE_PASSED` / `MANUAL_REVIEW_REQUIRED` / `ORCHESTRATOR_ERROR` 중 하나입니다.

## 프로젝트 구조

```text
.
├─ app.py                        # Streamlit UI 진입점
├─ orchestrator/
│  ├─ orchestrator.py            # Orchestrator 클래스 (진입점)
│  ├─ adapters.py                # 두 에이전트 간 입출력 변환
│  ├─ core/
│  │  ├─ request_handler.py      # 1. 요청 이해
│  │  ├─ planner.py              # 2. 작업 계획
│  │  ├─ dispatcher.py           # 3. 작업 분배 (생성↔검증 루프)
│  │  ├─ aggregator.py           # 4. 결과 종합
│  │  ├─ reporter.py             # 5. 최종 보고
│  │  └─ observability.py        # Langfuse 트레이싱 연동
│  ├─ models/
│  │  ├─ execution_plan.py
│  │  └─ orchestrator_result.py
│  └─ tests/
├─ requirements.txt
└─ .gitignore
```

## 의존 모듈

오케스트레이터는 단독으로 동작하지 않으며, 아래 두 모듈이 import 경로에 있어야 합니다.

- `generation_agent` (브랜치: `feature/generation-agent`)
- `compliance_agent` (브랜치: `feature/compliance-agent`)

`generation_agent` 위치는 환경변수 `GENERATION_AGENT_DIR`로 지정합니다. 미지정 시 `~/Desktop/poact_agent_my/generation_agent`로 폴백합니다.

## 설치

Python 3.9 이상을 권장합니다.

```bash
pip install -r requirements.txt
```

각 의존 모듈(`generation_agent`, `compliance_agent`)의 `requirements.txt`도 함께 설치해야 합니다.

LLM은 [Ollama](https://ollama.com)를 사용합니다. 로컬에 Ollama가 실행 중이어야 하며 사용 모델을 미리 받아둡니다.

```bash
ollama pull llama3.2
```

## 실행

```bash
streamlit run app.py
```

## 환경 설정

`.streamlit/secrets.toml` 또는 환경변수로 다음 값을 지정합니다.

```toml
LANGFUSE_PUBLIC_KEY = "pk-lf-..."
LANGFUSE_SECRET_KEY = "sk-lf-..."
LANGFUSE_HOST = "https://us.cloud.langfuse.com"
```

| 변수 | 용도 |
| --- | --- |
| `GENERATION_AGENT_DIR` | generation_agent 모듈 경로 |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | Langfuse 트레이싱 |
| `DB_API_URL` | 법령규제 DB 연동 (compliance) |

Langfuse 키가 없어도 동작하며, 이 경우 트레이싱만 비활성화됩니다.

## 기본 사용 예시

```python
from orchestrator.orchestrator import Orchestrator

orch = Orchestrator()
result = orch.run(
    request=request,            # 약관 생성 요청 dict
    session_id="sample-session",
    status_callback=print,
)
print(result["status"], result["iteration"])
```

`session_id`는 동일 세션의 반복 검토를 추적하는 키이며, Langfuse 트레이스도 이 값으로 묶입니다.

## 테스트

```bash
python -m pytest orchestrator/tests
```

## 공유 시 주의사항

다음 파일/폴더는 GitHub에 올리지 않습니다.

```text
__pycache__/
*.pyc
.pytest_cache/
.env
.venv/
.streamlit/secrets.toml
.claude/
```

개인 API 키나 로컬 경로는 `.streamlit/secrets.toml` 또는 `.env`에만 두고 저장소에는 포함하지 않습니다.
