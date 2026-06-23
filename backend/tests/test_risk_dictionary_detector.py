from backend.src.tools import risk_dictionary_detector as detector


def test_exact_expression_detected(monkeypatch):
    detector._load_dictionary_rows.cache_clear()
    monkeypatch.setattr(
        detector,
        "_load_dictionary_rows",
        lambda: (
            {
                "risk_id": "RISK-001",
                "expression": "전액 보장",
                "risk_type": "MISLEADING_COVERAGE",
                "severity": "HIGH",
                "reason": "전면 보장으로 오인될 수 있음",
                "regulatory_basis": "보험업법",
                "recommended_action": "한도와 면책 조건을 함께 명시",
                "replacement_guideline": "약관상 조건에 따라 보장",
                "source": "test",
                "version": "1",
            },
        ),
    )

    result = detector.detect_compliance_risks("본 상품은 모든 치료비를 전액 보장합니다.")

    assert result["dictionary_findings"]
    assert result["dictionary_findings"][0]["matched_expression"] == "전액 보장"
    assert result["summary"]["high_count"] >= 1


def test_semantic_pattern_detected(monkeypatch):
    detector._load_dictionary_rows.cache_clear()
    monkeypatch.setattr(detector, "_load_dictionary_rows", lambda: ())

    result = detector.detect_compliance_risks("고객님은 치료비 부담 없이 이용하실 수 있습니다.")

    assert result["semantic_findings"]
    assert any(
        item["risk_type"] in {"MISSING_LIMIT", "MISLEADING_COVERAGE"}
        for item in result["semantic_findings"]
    )


def test_safe_expression_has_no_high_findings(monkeypatch):
    detector._load_dictionary_rows.cache_clear()
    monkeypatch.setattr(detector, "_load_dictionary_rows", lambda: ())

    result = detector.detect_compliance_risks(
        "본 상품은 약관에서 정한 보장 조건 및 한도 내에서 자기부담금을 공제한 후 보험금을 지급합니다."
    )

    assert result["summary"]["high_count"] == 0
    assert result["summary"]["critical_count"] == 0


def test_context_review_flag_for_negated_expression(monkeypatch):
    detector._load_dictionary_rows.cache_clear()
    monkeypatch.setattr(
        detector,
        "_load_dictionary_rows",
        lambda: (
            {
                "risk_id": "RISK-002",
                "expression": "모든 치료비",
                "risk_type": "MISLEADING_COVERAGE",
                "severity": "HIGH",
            },
        ),
    )

    result = detector.detect_compliance_risks(
        "본 상품은 모든 치료비를 보장하지 않으며 약관상 보장 제외 항목이 존재합니다."
    )

    assert result["dictionary_findings"]
    assert result["dictionary_findings"][0]["needs_context_review"] is True


def test_db_schema_aliases_are_mapped(monkeypatch):
    detector._load_dictionary_rows.cache_clear()
    monkeypatch.setattr(
        detector,
        "_load_dictionary_rows",
        lambda: (
            {
                "risk_expression_id": 27,
                "expression": "즉시 지급",
                "category": "GUARANTEED_PAYMENT",
                "severity": "CRITICAL",
                "regulation": "보험업법",
                "review_action": "지급 요건을 함께 명시",
                "source_file": "seed.csv",
            },
        ),
    )

    result = detector.detect_compliance_risks("보험금은 청구 즉시 지급됩니다.")
    finding = result["dictionary_findings"][0]

    assert finding["risk_id"] == "27"
    assert finding["risk_type"] == "GUARANTEED_PAYMENT"
    assert finding["regulatory_basis"] == "보험업법"
    assert finding["recommended_action"] == "지급 요건을 함께 명시"
    assert finding["source"] == "seed.csv"
