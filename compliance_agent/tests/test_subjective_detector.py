"""
Rule 2 – SubjectiveDetector 테스트
LLM 호출은 mocker로 대체한다.
"""
import json
import pytest
from unittest.mock import MagicMock
from compliance_agent.detection_engine.subjective_detector import SubjectiveDetector
from compliance_agent.models import ViolationType, Severity
from .conftest import make_input


def _mock_llm(mocker, is_subjective: bool, reason: str = "테스트 사유"):
    """LangChain LLM invoke() 반환값을 고정한다."""
    response_text = json.dumps({"is_subjective": is_subjective, "reason": reason})
    mock_message = MagicMock()
    mock_message.content = response_text
    mock_client = MagicMock()
    mock_client.invoke.return_value = mock_message
    mocker.patch(
        "compliance_agent.detection_engine.subjective_detector.get_compliance_llm",
        return_value=mock_client,
    )
    return mock_client


class TestSubjectiveDetector:
    def test_사용자_선택모델을_llm_factory에_전달(self):
        response = MagicMock(content='{"is_subjective": false}')
        llm = MagicMock()
        llm.invoke.return_value = response
        factory = MagicMock(return_value=llm)
        detector = SubjectiveDetector(llm_factory=factory)
        data = make_input("상당한 사유가 있는 경우 처리합니다.")
        data.model_override = "openai/gpt-oss-20b:free"

        detector.detect(data)

        factory.assert_called_once_with("openai/gpt-oss-20b:free")

    def test_주관적표현_llm이_위반판정(self, mocker):
        _mock_llm(mocker, is_subjective=True)
        detector = SubjectiveDetector()
        data = make_input("상당한 사유가 있는 경우 보험금을 지급하지 않습니다.")
        violations = detector.detect(data)
        # "상당한 사유"는 복수 패턴에 매칭될 수 있으므로 >= 1 로 검증
        assert len(violations) >= 1
        assert all(v.type == ViolationType.SUBJECTIVE for v in violations)

    def test_주관적표현_llm이_통과판정(self, mocker):
        _mock_llm(mocker, is_subjective=False)
        detector = SubjectiveDetector()
        data = make_input("상당한 사유가 있는 경우 보험금을 지급하지 않습니다.")
        violations = detector.detect(data)
        assert len(violations) == 0

    def test_패턴없으면_llm_호출안함(self, mocker):
        mock_client = _mock_llm(mocker, is_subjective=True)
        detector = SubjectiveDetector()
        data = make_input("보험기간은 1년이며 자기부담금은 10,000원입니다.")
        detector.detect(data)
        mock_client.invoke.assert_not_called()

    def test_llm_오류시_보수적으로_위반처리(self, mocker):
        """LLM 호출 실패 → 불확실하면 위반 (CLAUDE.md 원칙)"""
        mock_client = MagicMock()
        mock_client.invoke.side_effect = Exception("API 오류")
        mocker.patch(
            "compliance_agent.detection_engine.subjective_detector.get_compliance_llm",
            return_value=mock_client,
        )
        detector = SubjectiveDetector()
        data = make_input("합리적인 범위 내에서 지급합니다.")
        violations = detector.detect(data)
        assert len(violations) >= 1
        assert violations[0].violation_id == "VIO_SUB_LLM_FAIL"
        assert violations[0].manual_flag is True

    def test_violation_id_형식(self, mocker):
        _mock_llm(mocker, is_subjective=True)
        detector = SubjectiveDetector()
        data = make_input("정당한 사유가 없는 경우 지급합니다.")
        violations = detector.detect(data)
        assert violations[0].violation_id.startswith("VIO_SUB_")

    def test_severity_MEDIUM(self, mocker):
        _mock_llm(mocker, is_subjective=True)
        detector = SubjectiveDetector()
        data = make_input("적절한 범위 내에서 보장합니다.")
        violations = detector.detect(data)
        assert violations[0].severity == Severity.MEDIUM

    def test_근거_규정_포함(self, mocker):
        _mock_llm(mocker, is_subjective=True)
        detector = SubjectiveDetector()
        data = make_input("충분한 사유가 인정되는 경우 지급합니다.")
        violations = detector.detect(data)
        assert "시행세칙" in violations[0].regulation

    def test_복수_패턴_각각_llm_호출(self, mocker):
        mock_client = _mock_llm(mocker, is_subjective=True)
        detector = SubjectiveDetector()
        data = make_input("상당한 사유와 합리적인 판단에 따라 처리합니다.")
        detector.detect(data)
        assert mock_client.invoke.call_count >= 2

    def test_llm_json_파싱_실패시_위반처리(self, mocker):
        mock_message = MagicMock()
        mock_message.content = "잘못된 응답 형식"
        mock_client = MagicMock()
        mock_client.invoke.return_value = mock_message
        mocker.patch(
            "compliance_agent.detection_engine.subjective_detector.get_compliance_llm",
            return_value=mock_client,
        )
        detector = SubjectiveDetector()
        data = make_input("불가피한 사유가 있는 경우 처리합니다.")
        violations = detector.detect(data)
        assert len(violations) >= 1

    def test_markdown_json_펜스_허용(self, mocker):
        """LLM이 ```json ... ``` 으로 감싸도 파싱해야 한다."""
        wrapped = '```json\n{"is_subjective": true, "reason": "모호함"}\n```'
        mock_message = MagicMock()
        mock_message.content = wrapped
        mock_client = MagicMock()
        mock_client.invoke.return_value = mock_message
        mocker.patch(
            "compliance_agent.detection_engine.subjective_detector.get_compliance_llm",
            return_value=mock_client,
        )
        detector = SubjectiveDetector()
        data = make_input("상당한 사유가 있으면 지급합니다.")
        violations = detector.detect(data)
        assert len(violations) >= 1
        assert violations[0].type == ViolationType.SUBJECTIVE

    def test_json_앞뒤_여분_텍스트_허용(self, mocker):
        """LLM이 JSON 앞뒤에 설명을 붙여도 추출해야 한다."""
        text = '답변입니다: {"is_subjective": false, "reason": "구체적임"} 이상입니다.'
        mock_message = MagicMock()
        mock_message.content = text
        mock_client = MagicMock()
        mock_client.invoke.return_value = mock_message
        mocker.patch(
            "compliance_agent.detection_engine.subjective_detector.get_compliance_llm",
            return_value=mock_client,
        )
        detector = SubjectiveDetector()
        data = make_input("상당한 사유가 있으면 지급합니다.")
        violations = detector.detect(data)
        assert len(violations) == 0  # is_subjective: false → 위반 아님

    def test_API_키_없어도_인스턴스_생성_가능(self, monkeypatch):
        """클라이언트는 lazy 초기화 — API 키 없는 환경에서도 생성자가 실패하면 안 된다."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
        # 생성 자체는 예외 없이 통과해야 함
        detector = SubjectiveDetector()
        assert detector is not None
