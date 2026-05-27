import json
import pytest
from unittest.mock import MagicMock
from compliance_agent.detection_engine.overstatement_detector import OverstatementDetector
from compliance_agent.models import ViolationType
from .conftest import make_input


@pytest.fixture
def detector():
    return OverstatementDetector()


def _mock_caveat_llm(mocker, is_real_caveat: bool):
    """ChatOllama.invoke()의 caveat 검증 응답을 고정한다."""
    response_text = json.dumps({"is_real_caveat": is_real_caveat, "reason": "테스트"})
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.return_value = mock_response
    mocker.patch(
        "compliance_agent.detection_engine.overstatement_detector.ChatOllama",
        return_value=mock_llm_instance,
    )
    return mock_llm_instance


class TestOverstatementDetector:
    def test_전액보장_단독_위반(self, detector):
        data = make_input("입원 치료비를 전액보장합니다.")
        violations = detector.detect(data)
        assert len(violations) == 1
        assert violations[0].type == ViolationType.OVERSTATEMENT

    def test_전액보장_자기부담금_명시_통과(self, detector, mocker):
        _mock_caveat_llm(mocker, is_real_caveat=True)
        data = make_input("입원 치료비를 전액보장합니다. 단, 자기부담금 10,000원이 적용됩니다.")
        violations = detector.detect(data)
        assert len(violations) == 0

    def test_100퍼센트_보장_위반(self, detector):
        data = make_input("본 상품은 실손 의료비를 100% 보장해드립니다.")
        violations = detector.detect(data)
        assert any(v.type == ViolationType.OVERSTATEMENT for v in violations)

    def test_무한보장_위반(self, detector):
        data = make_input("무한 보장으로 걱정 없이 치료받으세요.")
        violations = detector.detect(data)
        assert len(violations) >= 1

    def test_위반_없는_정상_문구(self, detector):
        data = make_input("보장 한도 내에서 실손 의료비를 지급합니다.")
        violations = detector.detect(data)
        assert len(violations) == 0

    def test_위반_id_형식(self, detector):
        data = make_input("전액보장 상품입니다.")
        violations = detector.detect(data)
        assert violations[0].violation_id.startswith("VIO_OVR_")

    def test_근거_규정_포함(self, detector):
        data = make_input("전액보장 상품입니다.")
        violations = detector.detect(data)
        assert "시행세칙" in violations[0].regulation

    def test_복수_패턴_동시_탐지(self, detector):
        data = make_input("전액보장이며 무한 보장입니다.")
        violations = detector.detect(data)
        assert len(violations) >= 2

    def test_caveat가_다른조항에_있으면_위반_탐지(self, detector):
        """문장 단위 검사: 자기부담금이 다른 조항(2문장 이상 떨어진 곳)에 있으면 위반으로 본다."""
        content = (
            "제1조 본 상품은 실손 의료비를 전액보장합니다. "
            "보장 내용은 다음과 같습니다. "
            "통원 치료비도 보장됩니다. "
            "제2조 자기부담금은 10,000원입니다."
        )
        data = make_input(content)
        violations = detector.detect(data)
        assert len(violations) >= 1

    def test_caveat가_인접문장에_있으면_통과(self, detector, mocker):
        """현재 문장 + 인접 1문장에 caveat이 있고 LLM이 실제 caveat으로 판정하면 통과한다."""
        _mock_caveat_llm(mocker, is_real_caveat=True)
        data = make_input("실손 의료비를 전액보장합니다. 단, 자기부담금 10,000원이 적용됩니다.")
        violations = detector.detect(data)
        assert len(violations) == 0

    def test_caveat가_직전문장에_있으면_통과(self, detector, mocker):
        """직전 문장에 caveat이 있고 LLM이 실제 caveat으로 판정하면 통과한다."""
        _mock_caveat_llm(mocker, is_real_caveat=True)
        data = make_input("자기부담금 10,000원이 적용됩니다. 그 외 입원 치료비는 전액보장합니다.")
        violations = detector.detect(data)
        assert len(violations) == 0

    def test_끝까지보장_위반(self, detector):
        data = make_input("계약 기간 동안 끝까지 보장해 드립니다.")
        violations = detector.detect(data)
        assert len(violations) >= 1

    def test_100퍼센트_환급_위반(self, detector):
        data = make_input("해지 시 100% 환급해 드립니다.")
        violations = detector.detect(data)
        assert len(violations) >= 1

    def test_띄어쓰기변형_매칭(self, detector):
        """공백 변형: '전액보장' (붙여쓰기) 도 매칭되어야 한다."""
        data = make_input("입원비를 전액보장 합니다.")
        violations = detector.detect(data)
        assert len(violations) >= 1

    def test_caveat_llm이_false_판정시_위반(self, detector, mocker):
        """caveat 패턴은 있지만 LLM이 실제 caveat이 아니라고 판정 → 위반으로 처리."""
        _mock_caveat_llm(mocker, is_real_caveat=False)
        data = make_input("입원 치료비를 전액보장합니다. 단, 자기부담금 10,000원이 적용됩니다.")
        violations = detector.detect(data)
        assert len(violations) >= 1

    def test_caveat_llm_오류시_보수적으로_위반처리(self, mocker):
        """LLM 호출 실패 시 보수적으로 위반으로 처리한다 (CLAUDE.md 원칙)."""
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.side_effect = Exception("연결 오류")
        mocker.patch(
            "compliance_agent.detection_engine.overstatement_detector.ChatOllama",
            return_value=mock_llm_instance,
        )
        detector = OverstatementDetector()
        data = make_input("입원 치료비를 전액보장합니다. 단, 자기부담금 10,000원이 적용됩니다.")
        violations = detector.detect(data)
        assert len(violations) >= 1

    def test_caveat_없으면_llm_미호출(self, mocker):
        """과장 표현이 있어도 caveat이 없으면 LLM을 호출하지 않는다."""
        mock_llm_instance = _mock_caveat_llm(mocker, is_real_caveat=True)
        data = make_input("입원 치료비를 전액보장합니다.")
        violations = OverstatementDetector().detect(data)
        assert len(violations) >= 1
        mock_llm_instance.invoke.assert_not_called()
