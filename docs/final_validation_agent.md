# Final Validation Agent

실손의료보험 **최종 산출물 검증 에이전트**입니다.
약관 / 상품설명서 / 사업방법서 3종 최종본을 입력받아 제출 가능 여부를 판정합니다.

기존 `generation → compliance → edit` 흐름 **뒤에 붙이는 최종 게이트**로 설계했으며,
현재는 LangGraph `builder.py` 에 연결하지 않은 **독립 모듈**입니다.

## 역할

검증은 5개 영역으로 이루어집니다.

1. **문서 완성도** — 약관·상품설명서·사업방법서 3종이 모두 생성되었는지
2. **규제 위반 잔존** — Compliance Agent가 지적한 위반 표현이 최종본에 남아 있지 않은지
3. **문서 간 일관성** — 보장 범위·면책 사항·보험금 지급 기준이 문서 간 충돌하지 않는지
4. **미완성 문구** — `TODO`, 예시, 임시 문구, `[수동검토필요]` 태그, 끊긴 문장이 없는지
5. **제출 형식** — 조항 번호·별표 참조 등 제출 문서로서의 형식을 갖췄는지

1·2·4번은 **규칙 기반(정규식·문자열 매칭)** 으로 LLM 없이도 동작하며,
3·5번처럼 맥락 판단이 필요한 항목은 LLM을 주입했을 때 추가로 검증합니다.

## 구성

| 파일 | 위치 | 설명 |
|------|------|------|
| `final_validation_agent.py` | `backend/src/agents/` | 검증 에이전트 본체 (규칙 기반 + LLM 하이브리드) |
| `final_validation.md` | `backend/src/prompts/` | LLM 검증용 시스템 프롬프트 |

## 입력 / 출력

**입력** (`State` 와 호환되는 dict):

```python
{
    "final_content": str,        # 약관 최종본 (없으면 draft_content 사용)
    "product_description": str,  # 상품설명서
    "business_method": str,      # 사업방법서
    "violations": list,          # compliance agent가 마지막에 보고한 위반 목록
}
```

**출력** (JSON):

```json
{
  "passed": true,
  "summary": "검증 요약",
  "issues": [
    {
      "document": "약관/상품설명서/사업방법서/공통",
      "issue_type": "누락/충돌/형식오류/규제잔존/근거부족/미완성문구",
      "description": "문제 설명",
      "severity": "high/medium/low",
      "suggestion": "수정 방향"
    }
  ]
}
```

`severity: high` 이슈가 하나라도 있으면 `passed: false` 로 판정합니다.

## 사용법

`.env` / API key 없이 규칙 기반으로 단독 실행할 수 있습니다.

```python
from final_validation_agent import run_final_validation

result = run_final_validation({
    "final_content": terms_text,
    "product_description": pd_text,
    "business_method": bm_text,
    "violations": compliance_violations,
})
print(result["passed"], result["summary"])
```

LLM을 함께 쓰려면 langchain Runnable을 주입합니다 (LLM 객체 생성은 호출 측 책임).

```python
result = run_final_validation(payload, llm=my_llm)         # 동기
result = await arun_final_validation(payload, llm=my_llm)   # 비동기
```

## LangGraph 연결 (추후)

`builder.py` 는 아직 수정하지 않았습니다. 연결 시 `nodes.py` 에 아래 형태로
`final_validation_node` 를 추가하고, **`edit → final_validation → END`** 로 라우팅하되
검증 실패(`passed: false`) 시 **`edit` 로 되돌려 재수정**하는 구조를 권장합니다.

```
... → edit → final_validation ─── passed=true ──→ END
                  ▲                   │
                  └──── passed=false ─┘   (위반/미완성 이슈 재수정)
```

재수정 루프가 무한히 돌지 않도록, 기존 `generation ↔ compliance` 와 동일하게
`iteration` 상한(예: 3회)에 도달하면 `END` 로 빠지면서 `status` 를
`MANUAL_REVIEW` 로 두는 것을 권장합니다.

```python
from ..agents.agents import get_supervisor_llm
from ..agents.final_validation_agent import arun_final_validation

async def final_validation_node(state, model_override=None):
    llm = get_supervisor_llm(model_override)
    result = await arun_final_validation({
        "final_content": state.get("final_content", ""),
        "product_description": state.get("product_description", ""),
        "business_method": state.get("business_method", ""),
        "violations": state.get("violations", []),
    }, llm=llm)
    return {
        "validation_result": result,
        "status": "PASS" if result["passed"] else "MANUAL_REVIEW",
        "messages": state["messages"] + [
            {"role": "final_validation", "content": result["summary"]}
        ],
    }


def route_final_validation(state):
    """passed=true 또는 iteration 상한 도달 시 종료, 아니면 edit 로 재수정."""
    result = state.get("validation_result", {})
    if result.get("passed") or state.get("iteration", 0) >= 3:
        return "end"
    return "edit"
```

`builder.py` 연결 예시:

```python
builder.add_node("final_validation", final_validation_node)
builder.add_edge("edit", "final_validation")
builder.add_conditional_edges(
    "final_validation",
    route_final_validation,
    {"edit": "edit", "end": END},
)
```

> 연결 시 `State` 에 `validation_result: dict` 필드를 추가해 전체 결과를 보존하는 것을 권장합니다.
