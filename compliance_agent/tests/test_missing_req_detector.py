import pytest
from compliance_agent.detection_engine.missing_req_detector import MissingReqDetector
from compliance_agent.models import ViolationType
from .conftest import make_input

FULL_CONTENT = """
제1조 (보험금 지급 사유)
피보험자가 보험사고로 입원 치료를 받은 경우 보험금을 지급합니다.

제2조 (자기부담금)
자기부담금은 10,000원입니다.

제3조 (면책 사항)
다음 항목은 보장하지 않습니다.

제4조 (보험료 납입)
보험료는 매월 납입합니다.

제5조 (계약 해지)
계약 해지 시 환급금이 지급됩니다.

제6조 (분쟁 조정)
분쟁조정은 금융감독원에 신청할 수 있습니다.

제7조 (보험기간)
보험기간은 1년입니다.

제8조 (청구 방법)
보험금 청구 시 청구서류를 제출해야 합니다.

제9조 (갱신)
계약 만료 시 갱신이 가능합니다.

제10조 (고지의무)
계약자는 알릴 의무가 있습니다.
"""


@pytest.fixture
def detector():
    return MissingReqDetector()


class TestMissingReqDetector:
    def test_필수항목_모두_있으면_위반없음(self, detector):
        data = make_input(FULL_CONTENT)
        violations = detector.detect(data)
        assert len(violations) == 0

    def test_보험금지급사유_누락_탐지(self, detector):
        data = make_input("자기부담금은 10,000원입니다. 보험기간은 1년입니다.")
        violations = detector.detect(data)
        ids = [v.violation_id for v in violations]
        assert "VIO_MRQ_REQ_001" in ids

    def test_자기부담금_누락_탐지(self, detector):
        data = make_input("보험금 지급 사유 발생 시 보험금을 지급합니다.")
        violations = detector.detect(data)
        ids = [v.violation_id for v in violations]
        assert "VIO_MRQ_REQ_002" in ids

    def test_violation_type_MISSING_REQUIREMENT(self, detector):
        data = make_input("내용 없음")
        violations = detector.detect(data)
        assert all(v.type == ViolationType.MISSING_REQUIREMENT for v in violations)

    def test_section_type_약관만_해당하는_항목(self, detector):
        # 보험료 납입(REQ_004)은 약관 전용
        data_약관 = make_input("내용 없음", section_type="약관")
        data_설명서 = make_input("내용 없음", section_type="상품설명서")
        ids_약관 = {v.violation_id for v in detector.detect(data_약관)}
        ids_설명서 = {v.violation_id for v in detector.detect(data_설명서)}
        assert "VIO_MRQ_REQ_004" in ids_약관
        assert "VIO_MRQ_REQ_004" not in ids_설명서

    def test_알수없는_section_type_에러_반환(self, detector):
        """유효하지 않은 section_type은 silent skip이 아니라 CRITICAL 위반을 반환해야 한다."""
        data = make_input("내용 없음", section_type="계약서")
        violations = detector.detect(data)
        assert len(violations) == 1
        assert violations[0].violation_id == "VIO_MRQ_INVALID_SECTION"
        assert violations[0].severity.value == "CRITICAL"
