"""
ComplianceAgent 통합 테스트.
LLM 의존 탐지기(Rule 2, 3)는 monkeypatch로 빈 리스트를 반환하도록 대체한다.
"""
import pytest
from compliance_agent.compliance_agent import ComplianceAgent
from .conftest import make_input

CLEAN_CONTENT = """
제1조 (보험금 지급 사유)
피보험자가 보험사고로 입원 치료를 받은 경우 보험금을 지급합니다.
자기부담금은 10,000원이며 보장 한도 내에서 지급합니다.
면책 사항에 해당하는 경우 보장하지 않습니다.
보험료는 매월 납입합니다. 계약 해지 시 환급금이 지급됩니다.
분쟁조정은 금융감독원에 신청할 수 있습니다.
보험기간은 1년입니다. 청구서류를 제출하여 보험금을 청구합니다.
갱신 시 보험료가 변경될 수 있습니다. 계약자는 알릴 의무가 있습니다.
"""

VIOLATION_CONTENT = "전액보장 상품입니다. 원금 보장이 됩니다."


@pytest.fixture(autouse=True)
def patch_llm_detectors(monkeypatch):
    """LLM 탐지기를 빈 리스트 반환으로 대체해 네트워크 없이 테스트한다."""
    from compliance_agent.detection_engine import violation_detector as vd

    original_subjective = vd.ViolationDetector._run_subjective
    original_contradiction = vd.ViolationDetector._run_contradiction

    monkeypatch.setattr(vd.ViolationDetector, "_run_subjective", lambda self, d: [])
    monkeypatch.setattr(vd.ViolationDetector, "_run_contradiction", lambda self, d: [])
    yield
    monkeypatch.setattr(vd.ViolationDetector, "_run_subjective", original_subjective)
    monkeypatch.setattr(vd.ViolationDetector, "_run_contradiction", original_contradiction)


class TestComplianceAgent:
    def test_위반없으면_COMPLIANCE_PASSED(self):
        agent = ComplianceAgent()
        data = make_input(CLEAN_CONTENT)
        report = agent.validate(data)
        assert report.status == "COMPLIANCE_PASSED"

    def test_위반없으면_final_validation_포함(self):
        agent = ComplianceAgent()
        report = agent.validate(make_input(CLEAN_CONTENT))
        assert report.final_validation is not None
        assert report.final_validation.passed is True

    def test_위반없으면_next_action_READY(self):
        agent = ComplianceAgent()
        report = agent.validate(make_input(CLEAN_CONTENT))
        assert report.next_action == "READY_FOR_DELIVERY"

    def test_위반있으면_VIOLATIONS_FOUND(self):
        agent = ComplianceAgent()
        report = agent.validate(make_input(VIOLATION_CONTENT))
        assert report.status == "VIOLATIONS_FOUND"

    def test_위반있으면_feedback_포함(self):
        agent = ComplianceAgent()
        report = agent.validate(make_input(VIOLATION_CONTENT))
        assert report.feedback_to_generator is not None
        assert len(report.feedback_to_generator.priority_fixes) > 0

    def test_to_dict_직렬화_가능(self):
        agent = ComplianceAgent()
        report = agent.validate(make_input(CLEAN_CONTENT))
        result = report.to_dict()
        assert result["status"] == "COMPLIANCE_PASSED"
        assert "final_validation" in result

    def test_FAIL_MAX_경고(self, monkeypatch):
        from compliance_agent.iteration_controller.iteration_tracker import IterationTracker
        # HARD_LOOP·FAIL_LOOP 미발동 조건 강제 → FAIL_MAX 경로만 단독 검증
        monkeypatch.setattr(IterationTracker, "has_loop_failure", lambda self: False)
        monkeypatch.setattr(IterationTracker, "has_hard_loop", lambda self: False)
        agent = ComplianceAgent()
        data = make_input(VIOLATION_CONTENT)
        for i in range(1, 4):
            data.iteration = i
            report = agent.validate(data)
        assert report.next_action == "MANUAL_REVIEW_REQUIRED"

    def test_confidence_score_범위(self):
        agent = ComplianceAgent()
        report = agent.validate(make_input(CLEAN_CONTENT))
        score = report.final_validation.confidence_score
        assert 0.0 <= score <= 1.0
