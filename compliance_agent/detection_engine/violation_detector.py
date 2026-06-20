"""
5개 규칙 탐지기를 통합 실행하는 오케스트레이터.
탐지 레이어 순서: Regex → Pattern Matching → LLM

각 detector 인스턴스는 ComplianceAgent 수명 동안 1회 생성·재사용한다
(LLM 클라이언트는 lazy 속성으로 첫 호출 시 생성).
"""
from __future__ import annotations

import asyncio
import logging
import os

from compliance_agent.models import (
    DetectionInput,
    DetectionResult,
    Severity,
    Violation,
    ViolationType,
)

from .contradiction_detector import ContradictionDetector
from .forbidden_word_detector import ForbiddenWordDetector
from .missing_req_detector import MissingReqDetector
from .overstatement_detector import OverstatementDetector
from .subjective_detector import SubjectiveDetector

logger = logging.getLogger(__name__)

_DEFAULT_DETECTOR_TIMEOUT_SECONDS = 60.0

_DETECTOR_META = (
    ("OVERSTATEMENT", ViolationType.OVERSTATEMENT, "VIO_OVR_DETECTOR_FAIL"),
    ("SUBJECTIVE", ViolationType.SUBJECTIVE, "VIO_SUB_DETECTOR_FAIL"),
    ("CONTRADICTION", ViolationType.CONTRADICTION, "VIO_CON_DETECTOR_FAIL"),
    ("FORBIDDEN_WORD", ViolationType.FORBIDDEN_WORD, "VIO_FBD_DETECTOR_FAIL"),
    ("MISSING_REQUIREMENT", ViolationType.MISSING_REQUIREMENT, "VIO_MRQ_DETECTOR_FAIL"),
)


class ViolationDetector:
    """각 Rule 탐지기를 asyncio.gather로 병렬 실행하고 결과를 취합한다."""

    def __init__(self) -> None:
        self._overstatement = OverstatementDetector()
        self._subjective = SubjectiveDetector()
        self._contradiction = ContradictionDetector()
        self._forbidden = ForbiddenWordDetector()
        self._missing_req = MissingReqDetector()

    async def detect(self, input_data: DetectionInput) -> DetectionResult:
        timeout = float(
            os.getenv("COMPLIANCE_DETECTOR_TIMEOUT_SECONDS", _DEFAULT_DETECTOR_TIMEOUT_SECONDS)
        )
        calls = (
            self._run_overstatement,
            self._run_subjective,
            self._run_contradiction,
            self._run_forbidden_word,
            self._run_missing_requirement,
        )
        detector_results = await asyncio.gather(
            *(
                asyncio.wait_for(
                    asyncio.to_thread(call, input_data),
                    timeout=timeout,
                )
                for call in calls
            ),
            return_exceptions=True,
        )

        result = DetectionResult()
        for meta, detector_result in zip(_DETECTOR_META, detector_results):
            name, violation_type, failure_id = meta
            if isinstance(detector_result, BaseException):
                is_timeout = isinstance(detector_result, asyncio.TimeoutError)
                failure_kind = f"{timeout:g}초 제한시간 초과" if is_timeout else "실행 오류"
                logger.error(
                    "Compliance detector %s failed: %s",
                    name,
                    detector_result,
                )
                result.violations.append(
                    Violation(
                        violation_id=failure_id,
                        type=violation_type,
                        severity=Severity.HIGH,
                        original_text="",
                        regulation="검증 시스템 운영 점검 필요",
                        reason=(
                            f"{name} 탐지기가 {failure_kind}로 완료되지 않았습니다. "
                            "나머지 탐지 결과는 보존했으며 해당 규칙은 수동 검토가 필요합니다."
                        ),
                        manual_flag=True,
                    )
                )
                continue
            result.violations.extend(detector_result)
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
