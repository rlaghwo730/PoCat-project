"""
5개 규칙 탐지기를 통합 실행하는 오케스트레이터.
탐지 레이어 순서: Regex → Pattern Matching → LLM

각 detector 인스턴스는 ComplianceAgent 수명 동안 1회 생성·재사용한다
(LLM 클라이언트는 lazy 속성으로 첫 호출 시 생성).
"""
from __future__ import annotations

from compliance_agent.models import DetectionInput, DetectionResult, Violation

from .contradiction_detector import ContradictionDetector
from .forbidden_word_detector import ForbiddenWordDetector
from .missing_req_detector import MissingReqDetector
from .overstatement_detector import OverstatementDetector
from .subjective_detector import SubjectiveDetector


class ViolationDetector:
    """각 Rule 탐지기를 순서대로 실행하고 결과를 취합한다."""

    def __init__(self) -> None:
        self._overstatement = OverstatementDetector()
        self._subjective = SubjectiveDetector()
        self._contradiction = ContradictionDetector()
        self._forbidden = ForbiddenWordDetector()
        self._missing_req = MissingReqDetector()

        # detect()에서 순회. 테스트가 _run_xxx 메서드를 monkeypatch 하므로 유지한다.
        self._detectors = [
            self._run_overstatement,
            self._run_subjective,
            self._run_contradiction,
            self._run_forbidden_word,
            self._run_missing_requirement,
        ]

    def detect(self, input_data: DetectionInput) -> DetectionResult:
        result = DetectionResult()
        for detector in self._detectors:
            result.violations.extend(detector(input_data))
        return result

    def _run_overstatement(self, data: DetectionInput) -> list[Violation]:
        return self._overstatement.detect(data)

    def _run_subjective(self, data: DetectionInput) -> list[Violation]:
        return self._subjective.detect(data)

    def _run_contradiction(self, data: DetectionInput) -> list[Violation]:
        return self._contradiction.detect(data)

    def _run_forbidden_word(self, data: DetectionInput) -> list[Violation]:
        return self._forbidden.detect(data)

    def _run_missing_requirement(self, data: DetectionInput) -> list[Violation]:
        return self._missing_req.detect(data)
