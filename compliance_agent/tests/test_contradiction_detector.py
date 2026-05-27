"""
Rule 3 – ContradictionDetector 테스트
LLM 호출은 mocker로 대체한다.
"""
import json
import pytest
from unittest.mock import MagicMock
from compliance_agent.detection_engine.contradiction_detector import (
    ContradictionDetector,
    _MAX_PAIRS,
)
from compliance_agent.models import ViolationType, Severity
from .conftest import make_input


def _mock_llm(mocker, is_contradiction: bool, subject: str = "입원 치료비"):
    response_text = json.dumps({
        "is_contradiction": is_contradiction,
        "subject": subject,
        "reason": "테스트 충돌 사유",
    })
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.return_value = mock_response
    mocker.patch(
        "compliance_agent.detection_engine.contradiction_detector.ChatOllama",
        return_value=mock_llm_instance,
    )
    return mock_llm_instance


# 보장 조항과 면책 조항이 각각 있는 텍스트 (각 조항 > 20자 유지)
CONTRADICTION_CONTENT = """
제1조 (보장 범위) 피보험자가 입원한 경우 입원 치료비를 보장하며 보험금을 지급합니다.
제2조 (면책 사항) 입원 치료비는 면책 대상으로 보장하지 않으며 지급하지 않습니다.
"""

# 보장 조항만 있는 텍스트 (후보 쌍 없음)
COVERAGE_ONLY_CONTENT = """
제1조 (보장 범위) 피보험자가 입원한 경우 입원 치료비를 보장하며 보험금을 지급합니다.
제2조 (보장 항목) 통원 치료비도 한도 내에서 보장하며 지급됩니다.
"""

# 면책 조항만 있는 텍스트 (보장·지급 키워드 없음 → coverage_idxs 빈 셋 → 후보 쌍 없음)
EXCLUSION_ONLY_CONTENT = """
제1조 (면책 사항) 다음 각 호에 해당하는 경우에는 면책으로 처리됩니다.
제2조 (제외 항목) 아래에 열거된 항목은 제외 대상으로 취급되며 해당 없습니다.
"""


class TestContradictionDetector:
    def test_충돌있으면_violation_반환(self, mocker):
        _mock_llm(mocker, is_contradiction=True)
        detector = ContradictionDetector()
        data = make_input(CONTRADICTION_CONTENT)
        violations = detector.detect(data)
        assert len(violations) >= 1
        assert violations[0].type == ViolationType.CONTRADICTION

    def test_충돌없으면_빈리스트(self, mocker):
        _mock_llm(mocker, is_contradiction=False)
        detector = ContradictionDetector()
        data = make_input(CONTRADICTION_CONTENT)
        violations = detector.detect(data)
        assert len(violations) == 0

    def test_보장조항만_있으면_llm_미호출(self, mocker):
        mock_llm_instance = _mock_llm(mocker, is_contradiction=True)
        detector = ContradictionDetector()
        data = make_input(COVERAGE_ONLY_CONTENT)
        detector.detect(data)
        mock_llm_instance.invoke.assert_not_called()

    def test_면책조항만_있으면_llm_미호출(self, mocker):
        mock_llm_instance = _mock_llm(mocker, is_contradiction=True)
        detector = ContradictionDetector()
        data = make_input(EXCLUSION_ONLY_CONTENT)
        detector.detect(data)
        mock_llm_instance.invoke.assert_not_called()

    def test_severity_CRITICAL(self, mocker):
        _mock_llm(mocker, is_contradiction=True)
        detector = ContradictionDetector()
        data = make_input(CONTRADICTION_CONTENT)
        violations = detector.detect(data)
        assert violations[0].severity == Severity.CRITICAL

    def test_violation_id_형식(self, mocker):
        _mock_llm(mocker, is_contradiction=True)
        detector = ContradictionDetector()
        data = make_input(CONTRADICTION_CONTENT)
        violations = detector.detect(data)
        assert violations[0].violation_id.startswith("VIO_CON_")

    def test_근거_규정_포함(self, mocker):
        _mock_llm(mocker, is_contradiction=True)
        detector = ContradictionDetector()
        data = make_input(CONTRADICTION_CONTENT)
        violations = detector.detect(data)
        assert "시행세칙" in violations[0].regulation

    def test_충돌_대상이_reason에_포함(self, mocker):
        _mock_llm(mocker, is_contradiction=True, subject="입원 치료비")
        detector = ContradictionDetector()
        data = make_input(CONTRADICTION_CONTENT)
        violations = detector.detect(data)
        assert "입원 치료비" in violations[0].reason

    def test_llm_오류시_meta_violation(self, mocker):
        """Rule 3은 LLM 실패 시 VIO_CON_LLM_FAIL meta-violation을 생성한다."""
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.side_effect = Exception("연결 오류")
        mocker.patch(
            "compliance_agent.detection_engine.contradiction_detector.ChatOllama",
            return_value=mock_llm_instance,
        )
        detector = ContradictionDetector()
        data = make_input(CONTRADICTION_CONTENT)
        violations = detector.detect(data)
        assert len(violations) == 1
        assert violations[0].violation_id == "VIO_CON_LLM_FAIL"
        assert violations[0].severity == Severity.LOW
        assert "LLM" in violations[0].reason

    def test_괄호번호_section_splitter(self, mocker):
        """(1) (2) 형식의 조항도 splitter가 인식해야 한다."""
        _mock_llm(mocker, is_contradiction=True)
        detector = ContradictionDetector()
        content = (
            "\n(1) 입원 치료비를 보장하며 보험금을 지급합니다.\n"
            "(2) 입원 치료비는 면책 대상으로 보장하지 않으며 지급하지 않습니다.\n"
        )
        data = make_input(content)
        violations = detector.detect(data)
        assert len(violations) >= 1

    def test_max_pairs_초과시_잘라냄(self, mocker):
        """조항 쌍이 MAX_PAIRS 초과 시 앞의 것만 처리한다."""
        mock_llm_instance = _mock_llm(mocker, is_contradiction=False)
        detector = ContradictionDetector()
        sections = []
        for i in range(10):
            sections.append(f"제{i*2+1}조 항목{i}를 보장합니다.")
            sections.append(f"제{i*2+2}조 항목{i}는 면책이며 보장하지 않습니다.")
        data = make_input("\n".join(sections))
        detector.detect(data)
        assert mock_llm_instance.invoke.call_count <= _MAX_PAIRS
