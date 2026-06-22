"""Standalone checks for DB-backed Regulatory Risk Simulation Agent.

Run manually with:
    python backend/tests/test_regulatory_risk_simulation_agent.py
    python backend/tests/test_regulatory_risk_simulation_agent.py --show-output

The default checks intentionally avoid real API keys and real LLM calls.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.tools import regulatory_risk_simulation_agent as agent


def _force_fallback_types():
    return agent.DEFAULT_GRAY_ZONE_TYPES, "fallback"


def _assert_common(result: dict) -> None:
    assert "findings" in result
    summary = result["summary"]
    assert summary["demo_only"] is True
    assert summary["operational_use_allowed"] is False
    assert summary["gray_zone_type_count"] >= 5
    assert summary["gray_zone_type_source"] in {"db", "fallback"}
    assert summary["llm_provider"] == "upstage"
    assert summary["llm_model"] == "solar-pro"
    assert "excluded_heading_count" in summary
    assert "[문장 명확성 평가 보고서]" in result["regulatory_risk_simulation_report"]
    assert "[명확한 문장 제안 보고서]" in result["safe_alternative_report"]
    assert "회색지대 표현 유형 시뮬레이션" not in result["regulatory_risk_simulation_report"]
    for finding in result["findings"]:
        assert finding["demo_only"] is True
        assert finding["operational_use_allowed"] is False
        assert finding["gray_zone_risk_type"]
        assert finding["gray_zone_risk_label"]
        assert finding["matched_patterns"]
        assert "unclear_points_in_source" in finding
        assert isinstance(finding["unclear_points_in_source"], list)
        assert finding["unclear_points_in_source"]
        assert finding["ambiguous_expression_example"]
        assert finding["risky_variant_example"] == finding["ambiguous_expression_example"]
        assert finding["strengthened_safe_sentence"]
        assert finding["safe_rewrite_example"] == finding["strengthened_safe_sentence"]
        assert finding["why_ambiguous"]
        assert finding["consumer_confusion_point"]
        assert finding["gray_zone_classification"] == agent.GRAY_MATCHED
        assert finding["classification_basis"] in {
            "db_gray_zone_expression_type",
            "fallback_gray_zone_expression_type",
        }
        assert finding["source_text_type"] == "body_sentence"
        assert finding["excluded_heading_like"] is False
        assert "nearest_heading" in finding
        assert finding["final_classification"] == agent.FINAL_GRAY
        assert finding["requires_human_review"] is True
        assert finding["compliance_judgement"]["checked"] is False
        assert finding["compliance_judgement"]["checker"] == "not_used"
        assert finding["full_compliance_judgement"]["checked"] is False


def test_load_gray_zone_expression_types_fallback() -> None:
    rows, source = agent.load_gray_zone_expression_types("약관")
    assert source in {"db", "fallback"}
    assert len(rows) >= 5
    assert "INSURER_DISCRETION_EXPANSION" in {row.get("risk_type") for row in rows}


def test_insurer_discretion_expansion() -> None:
    result = agent.simulate_regulatory_risks(
        "회사가 필요하다고 인정하는 경우 추가 자료를 요청할 수 있습니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    assert result["findings"][0]["gray_zone_risk_type"] == "INSURER_DISCRETION_EXPANSION"


def test_payment_condition_ambiguation() -> None:
    result = agent.simulate_regulatory_risks(
        "보험금은 필요한 서류와 합리적 확인이 완료된 뒤 지급됩니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    assert result["findings"][0]["gray_zone_risk_type"] == "PAYMENT_CONDITION_AMBIGUATION"


def test_limitation_under_specification() -> None:
    result = agent.simulate_regulatory_risks(
        "치료비는 보장한도와 자기부담금 기준에 따라 일부 보장됩니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    vectors = {item["gray_zone_risk_type"] for item in result["findings"]}
    assert "LIMITATION_UNDER_SPECIFICATION" in vectors


def test_open_ended_exception_expansion() -> None:
    result = agent.simulate_regulatory_risks(
        "이에 준하는 사유 또는 기타 회사가 정하는 사유가 있으면 보장이 제한됩니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    assert result["findings"][0]["gray_zone_risk_type"] == "OPEN_ENDED_EXCEPTION_EXPANSION"


def test_safe_sentence_no_type_match() -> None:
    result = agent.simulate_regulatory_risks(
        "보험금 지급 사유와 제출 서류는 약관의 별도 조항에 명시된 기준을 따릅니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    assert result["summary"]["total_count"] == 0
    assert result["findings"] == []
    assert result["summary"]["classifications"][agent.FINAL_SAFE] == 1


def test_heading_lines_are_excluded_from_source_text() -> None:
    result = agent.simulate_regulatory_risks(
        "제3절 자기부담금 및 보장 한도\n"
        "제5조 보장 한도)\n"
        "보험금은 연간 보장한도 및 자기부담금 공제 후 지급합니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    sources = [finding["source_text"] for finding in result["findings"]]
    assert not any(source == "제3절 자기부담금 및 보장 한도" for source in sources)
    assert not any(source == "제5조 보장 한도)" for source in sources)
    assert any("보험금은 연간 보장한도" in source for source in sources)
    assert result["summary"]["excluded_heading_count"] >= 2
    assert any(finding["nearest_heading"] == "제5조 보장 한도)" for finding in result["findings"])


def test_heading_only_does_not_create_finding() -> None:
    result = agent.simulate_regulatory_risks(
        "제5조 보장 한도)",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    assert result["summary"]["total_count"] == 0
    assert result["findings"] == []
    assert result["summary"]["excluded_heading_count"] >= 1


def test_article_prefixed_body_sentence_is_kept() -> None:
    result = agent.simulate_regulatory_risks(
        "제5조에 따라 보험금은 연간 보장한도 및 자기부담금 공제 후 지급합니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    assert result["findings"]
    assert "제5조에 따라 보험금은" in result["findings"][0]["source_text"]


def test_spaced_terms_are_normalized_for_matching() -> None:
    result = agent.simulate_regulatory_risks(
        "보험금은 연간 보장 한도 및 자기 부담금 공제 후 지급합니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    assert result["findings"]
    assert result["findings"][0]["gray_zone_risk_type"] == "LIMITATION_UNDER_SPECIFICATION"
    assert "보장 한도" in result["findings"][0]["source_text"]


def test_ambiguous_expression_example_fields_exist() -> None:
    result = agent.simulate_regulatory_risks(
        "보험금은 연간 보장 한도 및 자기 부담금 공제 후 지급합니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    finding = result["findings"][0]
    assert finding["ambiguous_expression_example"]
    assert finding["risky_variant_example"]
    assert finding["risky_variant_example"] == finding["ambiguous_expression_example"]


def test_unclear_points_are_extracted_from_source() -> None:
    result = agent.simulate_regulatory_risks(
        "보험금은 연간 보장 한도 및 자기 부담금 공제 후 지급합니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    points = result["findings"][0]["unclear_points_in_source"]
    joined = " ".join(points)
    assert any(keyword in joined for keyword in ("보장", "한도", "자기", "부담금", "공제"))


def test_ui_api_compatibility_fields_exist() -> None:
    result = agent.simulate_regulatory_risks(
        "회사가 필요하다고 인정하는 경우 보험금을 지급합니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    finding = result["findings"][0]
    for key in (
        "source_text",
        "gray_zone_risk_type",
        "why_ambiguous",
        "consumer_confusion_point",
        "strengthened_safe_sentence",
        "ambiguous_expression_example",
    ):
        assert finding[key]


def test_reports_include_ambiguous_example_sections() -> None:
    result = agent.simulate_regulatory_risks(
        "보험금은 연간 보장 한도 및 자기 부담금 공제 후 지급합니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    assert "[불명확하게 해석될 수 있는 표현 예시]" in result["regulatory_risk_simulation_report"]
    assert "[명확한 문장 제안]" in result["regulatory_risk_simulation_report"]
    assert "명확한 문장 제안" in result["safe_alternative_report"]


def test_heading_exclusion_keeps_spaced_body_sentence() -> None:
    result = agent.simulate_regulatory_risks(
        "제5조 자기부담금 및 보장 한도\n"
        "① 보장 한도)\n"
        "보험금은 연간 보장 한도 및 자기 부담금 공제 후 지급합니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    sources = [finding["source_text"] for finding in result["findings"]]
    assert "제5조 자기부담금 및 보장 한도" not in sources
    assert "① 보장 한도)" not in sources
    assert any("보험금은 연간 보장 한도" in source for source in sources)
    assert result["summary"]["excluded_heading_count"] >= 2
    assert result["summary"]["candidate_sentence_count"] >= 1
    assert result["summary"]["matched_candidate_count"] >= 1


def test_heading_context_can_match_next_body_sentence() -> None:
    result = agent.simulate_regulatory_risks(
        "제5조 보장 한도)\n"
        "보험금은 약관에서 정한 기준에 따라 지급합니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    assert result["findings"]
    finding = result["findings"][0]
    assert finding["source_text"] == "보험금은 약관에서 정한 기준에 따라 지급합니다."
    assert finding["nearest_heading"] == "제5조 보장 한도)"
    assert finding["matched_from_heading_context"] is True


def test_product_description_document_type_matches_product_rows() -> None:
    result = agent.simulate_regulatory_risks(
        "보장 내용\n"
        "이 상품은 다양한 의료비를 폭넓게 보장받을 수 있습니다.\n"
        "일부 항목은 보장하지 않을 수 있으니 가입 전 확인이 필요합니다.",
        document_type="상품설명서",
        use_llm=False,
    )
    _assert_common(result)
    assert result["summary"]["document_type"] == "상품설명서"
    assert result["summary"]["gray_zone_type_count"] >= 5
    assert result["findings"]
    assert any(
        risk_type.startswith("PRODUCT_DESCRIPTION_")
        for risk_type in result["summary"]["matched_risk_types"]
    )


def test_business_method_document_type_matches_business_rows() -> None:
    result = agent.simulate_regulatory_risks(
        "계약 인수\n"
        "회사가 필요하다고 판단하는 경우 가입이 제한될 수 있습니다.\n"
        "심사 결과에 따라 조건부 인수가 적용될 수 있습니다.",
        document_type="사업방법서",
        use_llm=False,
    )
    _assert_common(result)
    assert result["summary"]["document_type"] == "사업방법서"
    assert result["summary"]["gray_zone_type_count"] >= 5
    assert result["findings"]
    assert any(
        risk_type.startswith("BUSINESS_METHOD_")
        for risk_type in result["summary"]["matched_risk_types"]
    )


def test_ui_clause_sample_matches_multiple_findings() -> None:
    result = agent.simulate_regulatory_risks(
        "제5조 보험금 지급\n"
        "회사가 필요하다고 인정하는 경우 보험금을 지급합니다.\n"
        "보험금 지급 사유에 해당하고 필요한 서류 제출 및 심사 절차를 거친 경우 보험금을 지급합니다.\n"
        "보험금은 연간 보장 한도 및 자기 부담금 공제 후 지급합니다.",
        document_type="약관",
        use_llm=False,
    )
    _assert_common(result)
    assert result["summary"]["total_count"] >= 2


def test_ui_product_description_sample_matches_multiple_findings() -> None:
    result = agent.simulate_regulatory_risks(
        "보장 내용\n"
        "이 상품은 다양한 의료비를 폭넓게 보장받을 수 있는 상품입니다.\n"
        "일부 항목은 보장하지 않을 수 있으니 가입 전 확인이 필요합니다.\n"
        "보험료 부담을 줄일 수 있으며 일정 비용만 부담하면 보장이 가능합니다.\n"
        "계약을 중도해지하는 경우 환급금은 달라질 수 있습니다.",
        document_type="상품설명서",
        use_llm=False,
    )
    _assert_common(result)
    assert result["summary"]["total_count"] >= 3
    assert any(
        risk_type.startswith("PRODUCT_DESCRIPTION_")
        for risk_type in result["summary"]["matched_risk_types"]
    )


def test_ui_business_method_sample_matches_multiple_findings() -> None:
    result = agent.simulate_regulatory_risks(
        "계약 인수\n"
        "회사가 필요하다고 판단하는 경우 가입이 제한될 수 있습니다.\n"
        "심사 결과에 따라 조건부 인수가 적용될 수 있습니다.\n"
        "추가 확인이 필요한 경우 보험금 지급이 제한될 수 있습니다.\n"
        "회사의 내부 기준에 따라 지급 여부를 결정할 수 있습니다.\n"
        "필요 시 기준을 변경할 수 있습니다.",
        document_type="사업방법서",
        use_llm=False,
    )
    _assert_common(result)
    assert result["summary"]["total_count"] >= 3
    assert any(
        risk_type.startswith("BUSINESS_METHOD_")
        for risk_type in result["summary"]["matched_risk_types"]
    )


def test_llm_failure_uses_db_template_fallback() -> None:
    original = agent._llm_enhance_finding

    def failing_enhancer(*args, **kwargs):
        raise RuntimeError("simulated upstage failure")

    try:
        agent._llm_enhance_finding = failing_enhancer
        result = agent.simulate_regulatory_risks(
            "회사의 판단에 따라 필요한 서류를 추가로 요청할 수 있습니다.",
            document_type="약관",
            use_llm=True,
        )
    finally:
        agent._llm_enhance_finding = original

    _assert_common(result)
    assert result["findings"]
    assert result["summary"]["fallback_used"] is True
    assert result["summary"]["llm_used"] is False
    assert result["findings"][0]["llm_judgement"]["fallback_used"] is True


def test_ambiguous_excerpt_safety_postprocessing() -> None:
    result = agent.simulate_regulatory_risks(
        "회사가 필요하다고 인정하는 경우 추가 자료를 요청할 수 있습니다.",
        document_type="약관",
        use_llm=False,
    )
    finding = result["findings"][0]
    assert len(finding["ambiguous_expression_example"]) <= agent.MAX_AMBIGUOUS_EXPRESSION_CHARS
    assert "제1조" not in finding["ambiguous_expression_example"]


def run_all() -> None:
    tests = [
        test_load_gray_zone_expression_types_fallback,
        test_insurer_discretion_expansion,
        test_payment_condition_ambiguation,
        test_limitation_under_specification,
        test_open_ended_exception_expansion,
        test_safe_sentence_no_type_match,
        test_heading_lines_are_excluded_from_source_text,
        test_heading_only_does_not_create_finding,
        test_article_prefixed_body_sentence_is_kept,
        test_spaced_terms_are_normalized_for_matching,
        test_ambiguous_expression_example_fields_exist,
        test_unclear_points_are_extracted_from_source,
        test_ui_api_compatibility_fields_exist,
        test_reports_include_ambiguous_example_sections,
        test_heading_exclusion_keeps_spaced_body_sentence,
        test_heading_context_can_match_next_body_sentence,
        test_product_description_document_type_matches_product_rows,
        test_business_method_document_type_matches_business_rows,
        test_ui_clause_sample_matches_multiple_findings,
        test_ui_product_description_sample_matches_multiple_findings,
        test_ui_business_method_sample_matches_multiple_findings,
        test_llm_failure_uses_db_template_fallback,
        test_ambiguous_excerpt_safety_postprocessing,
    ]
    for test in tests:
        test()
    print("regulatory_risk_simulation_agent DB-backed standalone checks passed")


def show_output() -> None:
    sample = agent._sample_text()
    result = agent.simulate_regulatory_risks(
        sample,
        document_type="약관",
        request_context={"product_name": "실손의료보험", "purpose": "local_show_output"},
        max_findings=5,
        use_llm=False,
        model_override=agent.DEFAULT_MODEL,
    )
    print(agent.build_az_output(result, sample))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-output", action="store_true")
    args = parser.parse_args()
    run_all()
    if args.show_output:
        print()
        show_output()
