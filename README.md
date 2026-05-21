# Compliance Agent

실손의료보험 약관 초안을 검토하는 법률규제 검증 에이전트입니다.

생성 에이전트가 만든 약관/상품설명서 초안을 입력받아 과장 표현, 주관적 표현, 모순, 금지어, 필수 기재사항 누락을 탐지하고, 위반이 있으면 수정 피드백을 반환합니다.

## 주요 기능

- 약관/상품설명서 위반 탐지
- 생성 에이전트용 수정 피드백 생성
- 반복 검토 중 최대 반복/반복 실패 감지
- 최종 통과 시 신뢰도와 검증 결과 반환
- 테스트용 데모 시나리오 제공

## 프로젝트 구조

```text
.
├─ compliance_agent/
│  ├─ compliance_agent.py
│  ├─ detection_engine/
│  ├─ final_validation/
│  ├─ iteration_controller/
│  ├─ models/
│  └─ tests/
├─ docs/
├─ backend/
├─ demo.py
├─ samsung_compliance_pipeline.py
├─ legal_review_detector.py
├─ consumer_protection_detector.py
└─ requirements.txt
```

## 설치

Python 3.9 이상을 권장합니다.

```bash
pip install -r requirements.txt
```

## 데모 실행

LLM 호출 없이 로컬 규칙 기반 검증만 실행하려면 다음 명령을 사용합니다.

```bash
python demo.py --no-llm
```

특정 시나리오만 실행할 수도 있습니다.

```bash
python demo.py --no-llm --scenario 1
```

시나리오 번호:

| 번호 | 내용 |
| --- | --- |
| 1 | 위반 다수 약관 검토 |
| 2 | 위반 없는 약관 통과 |
| 3 | 반복 위반으로 인한 실패 감지 |
| 4 | 잘못된 section_type 처리 |
| 5 | 위반 후 수정되어 통과되는 2회 반복 흐름 |

## 테스트

```bash
python -m pytest compliance_agent/tests
```

현재 기준 테스트 결과:

```text
99 passed
```

## 기본 사용 예시

```python
from compliance_agent.compliance_agent import ComplianceAgent
from compliance_agent.models import DetectionInput

agent = ComplianceAgent()

result = agent.validate(
    DetectionInput(
        iteration=1,
        section_type="약관",
        content="본 상품은 실손 의료비를 전액보장합니다.",
        session_id="sample-session",
        product_meta={
            "product_name": "실손의료보험",
            "policy_type": "medical_loss",
        },
    )
)

print(result.model_dump())
```

동일한 초안을 여러 번 반복 검토할 때는 같은 `ComplianceAgent` 인스턴스를 재사용하거나 `session_id`를 동일하게 유지해야 반복 실패 감지가 정상 동작합니다.

## Samsung 데이터셋 파이프라인

`samsung_compliance_pipeline.py`는 별도의 JSON 데이터셋 파일이 필요합니다.

기본 파일명:

```text
samsung_insurance_clause_dataset.json
```

실행 방법:

```bash
python samsung_compliance_pipeline.py path/to/samsung_insurance_clause_dataset.json
```

또는 환경변수로 경로를 지정할 수 있습니다.

```bash
set SAMSUNG_DATA_PATH=path/to/samsung_insurance_clause_dataset.json
python samsung_compliance_pipeline.py
```

데이터셋이 없으면 해당 파이프라인은 실행되지 않고 안내 메시지를 출력합니다.

## 공유 시 주의사항

다음 파일/폴더는 GitHub에 올리지 않습니다.

```text
__pycache__/
*.pyc
.pytest_cache/
.env
.venv/
.claude/settings.local.json
```

개인 API 키나 로컬 경로는 `.env` 또는 개인 설정 파일에만 두고 저장소에는 포함하지 않습니다.
