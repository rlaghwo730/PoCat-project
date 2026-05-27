"""
confidence_calculator 단위 테스트.
content_length 기반 신뢰도 상한 로직을 검증한다.
"""
import pytest
from unittest.mock import patch
from compliance_agent.final_validation.confidence_calculator import calculate
from compliance_agent.models import ViolationType


@pytest.fixture(autouse=True)
def mock_real_mode():
    """DB MOCK_MODE=False 로 고정해 content_length cap만 단독 검증."""
    with patch("compliance_agent.external_apis.db_client.MOCK_MODE", False):
        yield


class TestConfidenceCalculator:
    def test_위반없고_충분한_길이_score_1(self):
        score, _ = calculate([], content_length=600)
        assert score == 1.0

    def test_위반없고_짧은_텍스트_cap_085(self):
        score, _ = calculate([], content_length=300)
        assert score <= 0.85

    def test_위반없고_매우_짧은_텍스트_cap_070(self):
        score, _ = calculate([], content_length=100)
        assert score <= 0.70

    def test_위반없고_빈_텍스트_cap_070(self):
        score, _ = calculate([], content_length=0)
        assert score <= 0.70

    def test_위반있으면_penalty_적용(self):
        from compliance_agent.models import Violation, Severity
        v = Violation(
            violation_id="VIO_OVR_001_001",
            type=ViolationType.OVERSTATEMENT,
            severity=Severity.HIGH,
            original_text="전액보장",
            regulation="시행세칙",
            reason="과장 표현",
        )
        score, checks = calculate([v], content_length=600)
        assert score < 1.0
        assert checks["overstatement"] == "FAIL"
        assert checks["contradiction"] == "PASS"

    def test_checks_dict_모든_rule_포함(self):
        _, checks = calculate([], content_length=600)
        expected_keys = {"overstatement", "subjective", "contradiction", "forbidden_word", "missing_requirement"}
        assert expected_keys == set(checks.keys())

    def test_mock_mode에서_상한_085(self):
        with patch("compliance_agent.external_apis.db_client.MOCK_MODE", True):
            score, _ = calculate([], content_length=600)
        assert score <= 0.85
