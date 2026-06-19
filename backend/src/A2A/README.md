# A2A(Agent-to-Agent) 보조 레이어 연결

기존 LangGraph 흐름을 **그대로 유지**하면서, 노드 간 전달 내용을 표준 A2A 메시지로
기록하는 **보조 레이어**를 추가했습니다. 라우팅을 대체하지 않으며, 관찰/로깅 목적입니다.

```
coordinator → planner → supervisor → generation → compliance → edit
```

위 흐름은 손대지 않았습니다. 각 노드가 끝날 때 "누가 누구에게 무엇을 넘겼는지"를
`state["a2a_messages"]` 에 한 줄씩 누적할 뿐입니다.

---

## 1. 파일을 어느 경로에 넣는가

### 새로 추가하는 파일 (3개)

```text
backend/src/a2a/
├─ __init__.py          # 패키지 노출 (create_a2a_message, append_a2a_message, A2AStatus)
├─ message_schema.py    # A2A 메시지 TypedDict + 상태 코드 상수
└─ utils.py             # create_a2a_message() / append_a2a_message() helper
```

### 수정하는 기존 파일 (2개)

```text
backend/src/graph/types.py    # State에 a2a_messages 필드 1줄 추가
backend/src/graph/nodes.py    # 각 노드 성공 return에 a2a_messages append (로직 변경 없음)
```

> `builder.py`, `workflow_service.py`, `agents.py`, `llm.py`, `config/agents.py` 는
> **수정하지 않았습니다.** (이유는 아래 4번 참고)

---

## 2. 새로 추가할 파일 전체 코드

`message_schema.py`, `utils.py`, `__init__.py` 전체 코드는 함께 제공된 파일을 그대로
해당 경로에 넣으면 됩니다. 핵심만 요약하면:

```python
# utils.py 의 핵심 두 함수
def create_a2a_message(sender, receiver, task, status, payload=None, metadata=None):
    # payload/metadata 기본값 빈 dict, metadata.timestamp 자동 주입
    ...

def append_a2a_message(state, message):
    # 기존 messages 패턴과 동일: '기존 리스트 + 새 메시지' 를 새로 만들어 반환
    return state.get("a2a_messages", []) + [message]
```

`create_a2a_message` 가 만드는 메시지 형태(요청하신 구조 그대로):

```python
{
    "sender": "generation",
    "receiver": "compliance",
    "task": "약관 초안 검토 요청",
    "status": "DRAFT_GENERATED",
    "payload": {"summary": "약관 초안 생성 완료"},
    "metadata": {"iteration": 1, "timestamp": "2026-...Z"},
}
```

---

## 3. 수정할 기존 파일의 변경 코드

### `types.py` — 변경 이유: State에 A2A 로그 필드가 있어야 노드가 거기에 누적할 수 있음

`State` TypedDict 맨 아래에 한 줄 추가했습니다.

```python
    a2a_messages: list[dict]   # A2A 메시지 목록 (관찰/로깅용)
```

> 리듀서(`Annotated[..., add]`)를 **쓰지 않은 이유**: 기존 `messages` 필드가 이미
> "노드가 전체 리스트를 통째로 반환해 덮어쓰는" 방식이라, `a2a_messages` 도 같은 방식을
> 따르면 일관적이고 `builder.py` 를 건드릴 필요가 없습니다.

### `nodes.py` — 변경 이유: 각 노드가 전달 내용을 A2A 메시지로 남기도록

먼저 import 한 줄을 추가했습니다.

```python
from ..a2a import create_a2a_message, append_a2a_message, A2AStatus
```

그리고 각 노드의 **성공 return dict 에만** `a2a_messages` 키를 추가했습니다.
기존 키(`messages`, `draft_content`, `status` 등)와 로직은 그대로입니다. 노드별 기록:

| 노드 | A2A sender → receiver | status |
|------|----------------------|--------|
| coordinator | coordinator → planner | REQUEST_VALIDATED |
| planner | planner → supervisor | PLAN_READY |
| supervisor | supervisor → (next_step) | ROUTING / WORKFLOW_END |
| generation | generation → compliance | DRAFT_GENERATED |
| compliance | compliance → supervisor | COMPLIANCE_PASSED / COMPLIANCE_FAILED |
| edit | edit → supervisor | EDIT_DONE |

예시 (generation_node 성공 return):

```python
a2a_msg = create_a2a_message(
    sender="generation", receiver="compliance",
    task="약관 초안 검토 요청",
    status=A2AStatus.DRAFT_GENERATED,
    payload={"summary": "약관 초안 생성 완료"},
    metadata={"iteration": new_iter},
)
return {
    "draft_content": result.get("content", ""),
    "iteration": new_iter,
    "messages": state["messages"] + [...],   # ← 기존 그대로
    "a2a_messages": append_a2a_message(state, a2a_msg),   # ← 추가된 한 줄
}
```

> **supervisor 는 허브**라 receiver가 매번 다릅니다. `next_step`(generation/compliance/edit/end)을
> 그대로 receiver로 쓰고, `end` 면 receiver="END", status=WORKFLOW_END 로 기록합니다.
>
> **compliance 는** PASS/FAIL 분기를 supervisor가 결정하므로, receiver="supervisor" 로 두고
> PASS/FAIL 을 status에 담았습니다.
>
> **에러(except) 경로에는 A2A 메시지를 넣지 않았습니다.** "정상 전달 흐름 기록"이 목적이고,
> 오류는 기존 `messages` 에 이미 남기 때문입니다. (원하면 except에도 ERROR 상태로 추가 가능)

---

## 4. 실제로 기존 흐름을 바꾸는 부분이 있는가 → **없습니다**

- **라우팅 변경 없음**: `route_supervisor`, `next_step` 결정 로직, `builder.py` 의
  edge/conditional edge 를 전혀 건드리지 않았습니다. 실행 순서·분기 조건 그대로입니다.
- **노드 로직 변경 없음**: LLM 호출, 검증 로직, 문서 생성 로직 모두 그대로입니다.
  각 노드 return dict 에 `a2a_messages` 키 하나만 더했습니다.
- **builder.py 수정 불필요**: `a2a_messages` 를 기존 `messages` 와 동일한
  "전체 리스트 반환" 방식으로 갱신하므로 리듀서 등록이 필요 없습니다.
- **workflow_service.py 수정 불필요**: `_initial_state()` 에 `a2a_messages` 가 없어도
  `append_a2a_message` 가 `state.get("a2a_messages", [])` 로 빈 리스트를 기본값 처리하므로
  첫 노드부터 안전하게 누적됩니다. (원하면 초기값 명시 추가 가능 — 아래 참고)

> ⚠️ **병렬 노드 도입 시 주의**: 현재는 한 번에 한 노드만 도는 순차 흐름이라 안전합니다.
> 나중에 fan-out(병렬) 노드를 추가하면 동시 갱신 시 한쪽이 덮어써질 수 있는데,
> 이는 기존 `messages` 필드도 동일하게 가진 한계입니다. 그때는 `types.py` 에서
> `a2a_messages: Annotated[list, operator.add]` 로 바꾸고 노드 return을
> `"a2a_messages": [a2a_msg]` (새 메시지만) 형태로 바꾸면 됩니다.

### (선택) workflow_service.py 에 초기값을 명시하고 싶다면

지금은 수정하지 않아도 동작하지만, 명시적으로 두고 싶으면 `_initial_state()` 의
return dict 에 아래 한 줄을 추가하면 됩니다. (필수 아님)

```python
        "a2a_messages": [],   # A2A 메시지 초기값 (선택 — 없어도 동작함)
```

---

## 5. 테스트 방법

### (a) 구문 검사

```bash
cd backend/src
python -c "import ast; [ast.parse(open(f).read()) for f in ['graph/nodes.py','graph/types.py','a2a/utils.py','a2a/message_schema.py']]; print('OK')"
```

### (b) A2A helper 단독 테스트 (외부 의존성 불필요)

```bash
cd backend
python -c "
from src.a2a import create_a2a_message, append_a2a_message, A2AStatus
msg = create_a2a_message('generation','compliance','약관 초안 검토 요청',
                         A2AStatus.DRAFT_GENERATED, payload={'summary':'생성 완료'},
                         metadata={'iteration':1})
assert 'timestamp' in msg['metadata']
state = {'a2a_messages': []}
state = {'a2a_messages': append_a2a_message(state, msg)}
assert len(state['a2a_messages']) == 1
print('A2A helper OK')
"
```

### (c) 전체 워크플로우 실행 후 메시지 확인

평소처럼 워크플로우를 실행한 뒤, 최종 state(또는 디버깅 로그)에서 `a2a_messages` 를
확인하면 노드 전달 흐름이 순서대로 쌓여 있어야 합니다. 예상 흐름:

```
coordinator>planner → planner>supervisor → supervisor>generation
→ generation>compliance → compliance>supervisor → supervisor>edit
→ edit>supervisor → supervisor>END
```

> `a2a_messages` 는 현재 `workflow_service.py` 의 API 응답(`_build_result`)에는
> 포함하지 않았습니다(요청대로 service 미수정). 응답에 노출하고 싶으면 추후
> `_build_result` 에 `"a2a_messages": result.get("a2a_messages", [])` 한 줄을 더하면 됩니다.

---

## 6. Git 커밋 메시지 추천

```text
feat(a2a): 노드 간 전달 내용을 A2A 메시지로 기록하는 보조 레이어 추가

- backend/src/a2a/ 패키지 신규 추가 (message_schema, utils)
  - create_a2a_message(): 표준 A2A 메시지 생성 (timestamp 자동 주입)
  - append_a2a_message(): 기존 messages 패턴과 동일한 누적 방식
- graph/types.py: State에 a2a_messages 필드 추가
- graph/nodes.py: 각 노드 성공 return에 a2a_messages append
  (라우팅/노드 로직 변경 없음, builder.py 미수정)

기존 LangGraph 흐름과 실행 결과는 그대로 유지되며,
관찰/로깅용 A2A 메시지만 부가적으로 누적됨.
```

작은 단위로 나누고 싶다면:

```text
feat(a2a): A2A 메시지 스키마와 helper 추가 (backend/src/a2a)
feat(graph): State에 a2a_messages 필드 추가
feat(graph): 각 노드에 A2A 메시지 기록 연결 (로직 변경 없음)
```
