import pytest
from compliance_agent.detection_engine.forbidden_word_detector import (
    FORBIDDEN_WORD_DICT_ADDITIONS,
    ForbiddenWordDetector,
)
from compliance_agent.models import Severity, ViolationType
from .conftest import make_input


@pytest.fixture
def detector():
    return ForbiddenWordDetector()


class TestForbiddenWordDetector:
    def test_원금보장_위반(self, detector):
        data = make_input("이 상품은 원금 보장이 됩니다.")
        violations = detector.detect(data)
        assert any(v.violation_id.startswith("VIO_FBD_009") for v in violations)

    def test_원금보장_심각도_CRITICAL(self, detector):
        data = make_input("원금 보장 상품입니다.")
        violations = detector.detect(data)
        match = next(v for v in violations if "원금 보장" in v.reason)
        assert match.severity == Severity.CRITICAL

    def test_예금자보호_위반(self, detector):
        data = make_input("예금자보호 적용 대상입니다.")
        violations = detector.detect(data)
        assert any("예금자보호" in v.reason for v in violations)

    def test_업계최초_위반(self, detector):
        data = make_input("업계 최초 실손보험 상품입니다.")
        violations = detector.detect(data)
        assert any("업계 최초" in v.reason for v in violations)

    def test_금지어_없는_정상_문구(self, detector):
        data = make_input("보장 한도 내에서 실손 의료비를 지급합니다.")
        violations = detector.detect(data)
        assert len(violations) == 0

    def test_violation_type_FORBIDDEN_WORD(self, detector):
        data = make_input("절대 보장 상품입니다.")
        violations = detector.detect(data)
        assert all(v.type == ViolationType.FORBIDDEN_WORD for v in violations)

    def test_띄어쓰기_없어도_매칭(self, detector):
        """'원금 보장' entry는 '원금보장'(공백 없음)도 잡아야 한다."""
        data = make_input("원금보장 상품입니다.")
        violations = detector.detect(data)
        assert any("원금" in v.reason for v in violations)

    def test_띄어쓰기_여러개도_매칭(self, detector):
        """공백 2개 이상도 매칭."""
        data = make_input("원금  보장 상품입니다.")
        violations = detector.detect(data)
        assert any("원금" in v.reason for v in violations)

    def test_확장사전은_30개이상(self):
        assert len(FORBIDDEN_WORD_DICT_ADDITIONS) >= 30

    @pytest.mark.parametrize(
        "content, expected_word",
        [
            ("모든 질병 보장 상품입니다.", "모든 질병 보장"),
            ("고지의무 없음으로 간편하게 가입합니다.", "고지의무 없음"),
            ("평생 보험료 동일 상품입니다.", "평생 보험료 동일"),
            ("오늘만 가입 가능하니 서두르세요.", "오늘만 가입 가능"),
            ("가입하면 무조건 사은품을 드립니다.", "가입하면 무조건 사은품"),
            ("정부 인증 보험입니다.", "정부 인증 보험"),
            ("가입자 수 1위 상품입니다.", "가입자 수 1위"),
            ("확정 수익률을 제공합니다.", "확정 수익률"),
        ],
    )
    def test_확장카테고리별_대표표현탐지(self, detector, content, expected_word):
        violations = detector.detect(make_input(content))
        assert any(expected_word in v.reason for v in violations)

    def test_협회규정근거에는_확인필요표시(self):
        association_entries = [
            entry for entry in FORBIDDEN_WORD_DICT_ADDITIONS
            if "광고심의규정" in entry.regulation
        ]
        assert association_entries
        assert all("[확인필요]" in entry.regulation for entry in association_entries)
