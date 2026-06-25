import asyncio
from types import SimpleNamespace

from backend.src.graph import nodes
from backend.src.service.workflow_service import _build_result, _initial_state
from compliance_agent.models import ComplianceReport


def _state(**overrides):
    state = {
        "messages": [],
        "request": {
            "session_id": "test-session",
            "document_request": {"product_name": "테스트보험"},
            "coverage_conditions": {
                "coverage_limit": {"급여": "5천만원"},
                "deductible_rule": {"급여": "20%"},
            },
        },
        "draft_content": "",
        "final_content": "약관 본문" * 10,
        "product_description": "상품설명서" * 5,
        "business_method": "사업방법서" * 2,
        "violations": [],
        "iteration": 1,
        "status": "",
        "next_step": "",
        "langfuse_callbacks": [],
        "post_edit_compliance_done": False,
        "compliance_next_action": "",
        "compliance_score": 0.0,
        "compliance_score_pct": 0.0,
        "document_compliance_scores": {},
    }
    state.update(overrides)
    return state


def test_compliance_node_문서별점수와종합백분율(monkeypatch):
    seen_inputs = []
    scores = {"약관": 0.9, "상품설명서": 0.8, "사업방법서": 1.0}

    class FakeAgent:
        async def validate_async(self, item):
            seen_inputs.append(item)
            return ComplianceReport(
                status="COMPLIANCE_PASSED",
                iteration=item.iteration,
                compliance_score=scores[item.section_type],
                next_action="READY_FOR_DELIVERY",
            )

    monkeypatch.setattr(nodes, "_get_compliance_agent", lambda: FakeAgent())
    callback = object()
    result = asyncio.run(nodes.compliance_node(
        _state(langfuse_callbacks=[callback]),
        model_override="openai/gpt-oss-20b:free",
    ))

    assert result["status"] == "PASS"
    assert result["compliance_score_pct"] > 0
    assert set(result["document_compliance_scores"]) == {
        "terms", "product_description", "business_method"
    }
    business = next(i for i in seen_inputs if i.section_type == "사업방법서")
    assert business.coverage_context is None
    assert all(
        item.model_override == "openai/gpt-oss-20b:free" for item in seen_inputs
    )
    assert all(item.langfuse_callbacks == [callback] for item in seen_inputs)


def test_compliance_node_문서일부실패시_나머지결과와수동검토를_보존(monkeypatch):
    class FakeAgent:
        async def validate_async(self, item):
            if item.section_type == "상품설명서":
                raise RuntimeError("product description validation failed")
            return ComplianceReport(
                status="COMPLIANCE_PASSED",
                iteration=item.iteration,
                compliance_score=1.0,
                next_action="READY_FOR_DELIVERY",
            )

    monkeypatch.setattr(nodes, "_get_compliance_agent", lambda: FakeAgent())

    result = asyncio.run(nodes.compliance_node(_state()))

    assert result["status"] == "FAIL"
    assert result["compliance_next_action"] == "MANUAL_REVIEW_REQUIRED"
    assert result["document_compliance_scores"]["terms"]["status"] == "COMPLIANCE_PASSED"
    assert result["document_compliance_scores"]["business_method"]["status"] == "COMPLIANCE_PASSED"
    assert result["document_compliance_scores"]["product_description"]["status"] == "ERROR"
    assert any(
        v["violation_id"] == "product_description:VIO_DOC_VALIDATION_FAIL"
        and v["manual_flag"] is True
        for v in result["violations"]
    )


def test_initial_state에_langfuse_callback을_보존():
    callback = object()
    state = _initial_state({"document_request": {}}, [callback])
    assert state["langfuse_callbacks"] == [callback]


def test_supervisor_최종검증실패는수동검토종료(monkeypatch):
    class FakeLLM:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content="수동 검토 필요")

    monkeypatch.setattr(nodes, "get_supervisor_llm", lambda _model=None: FakeLLM())
    state = _state(
        messages=[{"role": "compliance", "content": "검증 실패"}],
        status="FAIL",
        post_edit_compliance_done=True,
        compliance_next_action="REGENERATE",
    )
    result = asyncio.run(nodes.supervisor_node(state))
    assert result["next_step"] == "final_validation"
    assert result["status"] == "MANUAL_REVIEW_REQUIRED"


def test_api_result에_준수율백분율이유지됨():
    result = _build_result(
        _state(
            status="PASS",
            compliance_score=0.8734,
            compliance_score_pct=87.3,
            document_compliance_scores={
                "terms": {
                    "section_type": "약관",
                    "status": "COMPLIANCE_PASSED",
                    "compliance_score": 0.8734,
                    "compliance_score_pct": 87.3,
                }
            },
        ),
        db_warning=None,
    )
    assert result["compliance_score"] == 0.8734
    assert result["compliance_score_pct"] == 87.3
    assert result["document_compliance_scores"]["terms"]["compliance_score_pct"] == 87.3
