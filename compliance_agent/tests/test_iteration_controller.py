import pytest
from compliance_agent.iteration_controller.iteration_tracker import IterationTracker
from compliance_agent.iteration_controller.termination_logic import TerminationLogic, TerminationReason
from compliance_agent.iteration_controller.feedback_builder import FeedbackBuilder
from compliance_agent.models import Severity, Violation, ViolationType


def _make_violation(vid: str, vtype: ViolationType = ViolationType.OVERSTATEMENT) -> Violation:
    return Violation(
        violation_id=vid,
        type=vtype,
        severity=Severity.HIGH,
        original_text="테스트 텍스트",
        regulation="시행세칙 §00",
        reason="테스트 사유",
    )


class TestIterationTracker:
    def test_초기_iteration은_0(self):
        tracker = IterationTracker()
        assert tracker.iteration == 0

    def test_record_후_iteration_증가(self):
        tracker = IterationTracker()
        tracker.record([])
        assert tracker.iteration == 1

    def test_반복위반_없으면_빈셋(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001")])
        tracker.record([_make_violation("VIO_002")])
        assert tracker.repeated_violation_ids() == set()

    def test_동일위반_2회_이상_탐지(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001")])
        tracker.record([_make_violation("VIO_001")])
        assert "VIO_001" in tracker.repeated_violation_ids()

    def test_max_iteration_도달(self):
        tracker = IterationTracker()
        for _ in range(3):
            tracker.record([_make_violation("VIO_001")])
        assert tracker.is_max_iteration_reached()

    def test_max_iteration_미도달(self):
        tracker = IterationTracker()
        tracker.record([])
        assert not tracker.is_max_iteration_reached()

    def test_동일_run_내_중복_ID는_FAIL_LOOP_미발동(self):
        """같은 iteration run 안에 동일 ID가 2개 있어도 repeated_violation_ids에 포함되면 안 된다."""
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_OVR_001"), _make_violation("VIO_OVR_001")])
        assert tracker.repeated_violation_ids() == set()

    # ── violation_delta ────────────────────────────────────────────────────────
    def test_violation_delta_history_1이면_None(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001")])
        assert tracker.violation_delta() is None

    def test_violation_delta_감소(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001"), _make_violation("VIO_002")])  # 2개
        tracker.record([_make_violation("VIO_001")])                              # 1개
        assert tracker.violation_delta() == -1

    def test_violation_delta_정체(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001")])
        tracker.record([_make_violation("VIO_001")])
        assert tracker.violation_delta() == 0

    def test_violation_delta_증가(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001")])
        tracker.record([_make_violation("VIO_001"), _make_violation("VIO_002")])
        assert tracker.violation_delta() == 1

    # ── has_hard_loop ──────────────────────────────────────────────────────────
    def test_has_hard_loop_정체시_True(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001")])
        tracker.record([_make_violation("VIO_001")])
        assert tracker.has_hard_loop() is True

    def test_has_hard_loop_감소시_False(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001"), _make_violation("VIO_002")])
        tracker.record([_make_violation("VIO_001")])
        assert tracker.has_hard_loop() is False

    def test_has_hard_loop_history_1이면_False(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001")])
        assert tracker.has_hard_loop() is False

    # ── consecutive_violation_ids / has_soft_loop ──────────────────────────────
    def test_consecutive_3회_연속_탐지(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001"), _make_violation("VIO_002")])
        tracker.record([_make_violation("VIO_001"), _make_violation("VIO_003")])
        tracker.record([_make_violation("VIO_001")])
        # VIO_001만 3회 연속
        assert tracker.consecutive_violation_ids() == {"VIO_001"}

    def test_consecutive_2회만이면_미탐지(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001")])
        tracker.record([_make_violation("VIO_001")])
        assert tracker.consecutive_violation_ids() == set()

    def test_has_soft_loop_3회연속_True(self):
        tracker = IterationTracker()
        for _ in range(3):
            tracker.record([_make_violation("VIO_001")])
        assert tracker.has_soft_loop() is True

    def test_has_soft_loop_2회면_False(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001")])
        tracker.record([_make_violation("VIO_001")])
        assert tracker.has_soft_loop() is False


class TestTerminationLogic:
    def setup_method(self):
        self.logic = TerminationLogic()

    def test_위반없으면_PASS(self):
        tracker = IterationTracker()
        tracker.record([])
        assert self.logic.evaluate([], tracker, current_iteration=1) == TerminationReason.PASS

    def test_위반수_정체_HARD_LOOP(self):
        """직전 대비 위반 수 delta == 0 → HARD_LOOP."""
        tracker = IterationTracker()
        v = _make_violation("VIO_001")
        tracker.record([v])  # iter 1: 1개
        tracker.record([v])  # iter 2: 1개 → delta=0
        assert self.logic.evaluate([v], tracker, current_iteration=2) == TerminationReason.HARD_LOOP

    def test_위반수_증가_HARD_LOOP(self):
        """직전 대비 위반 수 증가 → HARD_LOOP."""
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001")])                                     # 1개
        tracker.record([_make_violation("VIO_001"), _make_violation("VIO_002")])         # 2개
        v = _make_violation("VIO_003")
        assert self.logic.evaluate([v], tracker, current_iteration=2) == TerminationReason.HARD_LOOP

    def test_최대반복_FAIL_MAX(self):
        """위반 수가 꾸준히 감소(delta < 0)하지만 iteration >= 3 → FAIL_MAX."""
        tracker = IterationTracker()
        tracker.record([_make_violation(f"V{i}") for i in range(3)])  # 3개
        tracker.record([_make_violation(f"V{i}") for i in range(2)])  # 2개 (개선)
        tracker.record([_make_violation("V0")])                        # 1개 (개선)
        v = _make_violation("V0")
        # delta = 1-2 = -1 → HARD_LOOP 미발동, iteration=3 >= MAX → FAIL_MAX
        assert self.logic.evaluate([v], tracker, current_iteration=3) == TerminationReason.FAIL_MAX

    def test_계속진행_CONTINUE(self):
        tracker = IterationTracker()
        tracker.record([_make_violation("VIO_001"), _make_violation("VIO_002")])  # 2개
        v = _make_violation("VIO_001")  # 1개
        # delta = 1-2 = -1 → HARD_LOOP 미발동, iteration=1 < MAX → CONTINUE
        # (tracker history 반영 후 evaluate 호출을 재현: 두 번째 record 없이 평가)
        tracker.record([v])
        assert self.logic.evaluate([v], tracker, current_iteration=1) == TerminationReason.CONTINUE


class TestFeedbackBuilder:
    def test_VIOLATIONS_FOUND_status(self):
        builder = FeedbackBuilder()
        v = _make_violation("VIO_001")
        report = builder.build([v], iteration=1)
        assert report.status == "VIOLATIONS_FOUND"

    def test_priority_fixes_생성(self):
        builder = FeedbackBuilder()
        violations = [
            _make_violation("VIO_001", ViolationType.OVERSTATEMENT),
            _make_violation("VIO_002", ViolationType.MISSING_REQUIREMENT),
        ]
        report = builder.build(violations, iteration=1)
        assert len(report.feedback_to_generator.priority_fixes) == 2

    def test_CRITICAL_먼저_정렬(self):
        builder = FeedbackBuilder()
        violations = [
            Violation("VIO_LOW", ViolationType.SUBJECTIVE, Severity.LOW, "t", "r", "r"),
            Violation("VIO_CRT", ViolationType.CONTRADICTION, Severity.CRITICAL, "t", "r", "r"),
        ]
        report = builder.build(violations, iteration=1)
        assert report.violations[0].severity == Severity.CRITICAL

    def test_priority_fixes_상위10개로_제한(self):
        """위반이 30개여도 priority_fixes는 10개 이하."""
        builder = FeedbackBuilder()
        violations = [
            Violation(
                violation_id=f"VIO_OVR_{i:03d}_001",
                type=ViolationType.OVERSTATEMENT,
                severity=Severity.HIGH,
                original_text=f"text{i}",
                regulation="r",
                reason="r",
            )
            for i in range(30)
        ]
        report = builder.build(violations, iteration=1)
        assert len(report.feedback_to_generator.priority_fixes) <= 10
        # 전체 violations 목록은 그대로 유지
        assert len(report.violations) == 30

    def test_priority_fixes_동일패턴_dedup(self):
        """같은 패턴의 다중 매치(VIO_OVR_001_001, _002, _003)는 priority_fix 1건으로 압축."""
        builder = FeedbackBuilder()
        violations = [
            Violation(
                violation_id=f"VIO_OVR_001_{seq:03d}",
                type=ViolationType.OVERSTATEMENT,
                severity=Severity.HIGH,
                original_text=f"text{seq}",
                regulation="r",
                reason="r",
            )
            for seq in range(1, 6)
        ]
        report = builder.build(violations, iteration=1)
        # 5개 매치가 1건의 priority_fix로 압축
        assert len(report.feedback_to_generator.priority_fixes) == 1

    def test_violation_summary_초과시_포함(self):
        """violation이 10개 초과(deferred 발생)하면 violation_summary가 첨부된다."""
        builder = FeedbackBuilder()
        violations = [
            Violation(
                violation_id=f"VIO_OVR_{i:03d}_001",
                type=ViolationType.OVERSTATEMENT,
                severity=Severity.HIGH,
                original_text=f"text{i}",
                regulation="r",
                reason="r",
            )
            for i in range(15)
        ]
        report = builder.build(violations, iteration=1)
        summary = report.feedback_to_generator.violation_summary
        assert summary is not None
        assert summary.total == 15
        assert summary.delivered == len(report.feedback_to_generator.priority_fixes)
        assert summary.deferred == summary.total - summary.delivered
        assert "OVERSTATEMENT" in summary.deferred_by_type

    def test_violation_summary_10개_이하시_None(self):
        """violation이 10개 이하(전량 전달)이면 violation_summary는 None."""
        builder = FeedbackBuilder()
        violations = [_make_violation(f"VIO_{i:03d}") for i in range(5)]
        report = builder.build(violations, iteration=1)
        assert report.feedback_to_generator.violation_summary is None
