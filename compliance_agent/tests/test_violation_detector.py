import asyncio
import time

from compliance_agent.detection_engine.violation_detector import ViolationDetector
from compliance_agent.models import Severity, Violation, ViolationType

from .conftest import make_input


def _violation(vid: str) -> Violation:
    return Violation(
        violation_id=vid,
        type=ViolationType.FORBIDDEN_WORD,
        severity=Severity.MEDIUM,
        original_text="테스트",
        regulation="테스트 규정",
        reason="테스트 위반",
    )


def test_한_탐지기_예외에도_나머지_결과를_보존(monkeypatch):
    detector = ViolationDetector()
    monkeypatch.setattr(detector, "_run_overstatement", lambda _data: [_violation("OK_001")])
    monkeypatch.setattr(
        detector,
        "_run_subjective",
        lambda _data: (_ for _ in ()).throw(RuntimeError("subjective down")),
    )
    monkeypatch.setattr(detector, "_run_contradiction", lambda _data: [])
    monkeypatch.setattr(detector, "_run_forbidden_word", lambda _data: [])
    monkeypatch.setattr(detector, "_run_missing_requirement", lambda _data: [])

    result = asyncio.run(detector.detect(make_input("테스트 약관")))
    ids = {v.violation_id for v in result.violations}

    assert "OK_001" in ids
    assert "VIO_SUB_DETECTOR_FAIL" in ids
    failure = next(v for v in result.violations if v.violation_id == "VIO_SUB_DETECTOR_FAIL")
    assert failure.manual_flag is True


def test_탐지기_제한시간_초과를_수동검토로_변환(monkeypatch):
    detector = ViolationDetector()
    monkeypatch.setenv("COMPLIANCE_DETECTOR_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(
        detector,
        "_run_overstatement",
        lambda _data: (time.sleep(0.05), [])[1],
    )
    monkeypatch.setattr(detector, "_run_subjective", lambda _data: [])
    monkeypatch.setattr(detector, "_run_contradiction", lambda _data: [])
    monkeypatch.setattr(detector, "_run_forbidden_word", lambda _data: [])
    monkeypatch.setattr(detector, "_run_missing_requirement", lambda _data: [])

    result = asyncio.run(detector.detect(make_input("테스트 약관")))

    failure = next(v for v in result.violations if v.violation_id == "VIO_OVR_DETECTOR_FAIL")
    assert "제한시간 초과" in failure.reason
    assert failure.manual_flag is True
