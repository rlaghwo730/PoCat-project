"""오케스트레이터 단위 테스트.

실제 LLM/DB 호출 없이 core 모듈 각각의 로직을 검증한다.
GenerationAgent, ComplianceAgent는 unittest.mock으로 대체한다.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from orchestrator.core import aggregator, planner, reporter, request_handler
from orchestrator.models.execution_plan import ExecutionPlan
from orchestrator.models.orchestrator_result import OrchestratorResult


# ──────────────────────────────────────────────────────────────────────────────
# 공통 픽스처
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_request():
    return {
        "document_request": {
            "document_type": "약관",
            "product_name": "실손의료보험",
            "insurance_company": "삼성화재",
            "product_version": "2024",
        },
        "product_design_conditions": {
            "policy_period": "1년",
            "renewal_type": "갱신형",
        },
        "coverage_conditions": {
            "basic_coverage_items": ["급여 상해", "급여 질병"],
            "noncovered_rider_items": ["비급여 상해"],
            "three_major_noncovered_items": ["도수치료"],
            "coverage_limit": "5천만원",
            "deductible_rule": "급여 20%, 비급여 30%",
        },
        "applicant_info": {
            "applicant_type": "본인",
            "birth_date": "1990-01-01",
            "gender": "남성",
            "occupation": "회사원",
        },
    }


@pytest.fixture
def high_complexity_request(valid_request):
    req = dict(valid_request)
    req["coverage_conditions"] = dict(valid_request["coverage_conditions"])
    req["coverage_conditions"]["noncovered_rider_items"] = ["비급여 상해", "비급여 질병"]
    req["coverage_conditions"]["three_major_noncovered_items"] = [
        "도수치료", "체외충격파", "증식치료"
    ]
    return req


# ──────────────────────────────────────────────────────────────────────────────
# 1. request_handler
# ──────────────────────────────────────────────────────────────────────────────

class TestRequestHandler:
    def test_valid_request_passes(self, valid_request):
        request_handler.validate(valid_request)  # 예외 없이 통과

    def test_missing_section_raises(self, valid_request):
        del valid_request["document_request"]
        with pytest.raises(ValueError, match="document_request"):
            request_handler.validate(valid_request)

    def test_missing_field_raises(self, valid_request):
        valid_request["document_request"]["product_name"] = ""
        with pytest.raises(ValueError, match="product_name"):
            request_handler.validate(valid_request)

    def test_missing_coverage_limit_raises(self, valid_request):
        valid_request["coverage_conditions"]["coverage_limit"] = ""
        with pytest.raises(ValueError, match="coverage_limit"):
            request_handler.validate(valid_request)

    def test_parse_document_type(self, valid_request):
        assert request_handler.parse_document_type(valid_request) == "약관"

    def test_parse_product_name(self, valid_request):
        assert request_handler.parse_product_name(valid_request) == "실손의료보험"


# ──────────────────────────────────────────────────────────────────────────────
# 2. planner
# ──────────────────────────────────────────────────────────────────────────────

class TestPlanner:
    def test_normal_complexity(self, valid_request):
        plan = planner.build_plan(valid_request)
        assert plan.complexity == "NORMAL"
        assert plan.document_type == "약관"
        assert plan.max_iterations == 3

    def test_high_complexity(self, high_complexity_request):
        plan = planner.build_plan(high_complexity_request)
        assert plan.complexity == "HIGH"
        assert "CONTRADICTION" in plan.priority_checks

    def test_plan_to_dict(self, valid_request):
        plan = planner.build_plan(valid_request)
        d = plan.to_dict()
        assert "document_type" in d
        assert "complexity" in d
        assert "priority_checks" in d


# ──────────────────────────────────────────────────────────────────────────────
# 4. aggregator
# ──────────────────────────────────────────────────────────────────────────────

class TestAggregator:
    def test_empty_history(self):
        result = aggregator.aggregate([])
        assert result == {}

    def test_single_iteration(self):
        history = [{"iteration": 1, "status": "COMPLIANCE_PASSED", "violation_count": 0, "violation_types": []}]
        result = aggregator.aggregate(history)
        assert result["iterations_run"] == 1
        assert result["total_improvement"] is None

    def test_improvement_calculated(self):
        history = [
            {"iteration": 1, "status": "VIOLATIONS_FOUND", "violation_count": 5, "violation_types": []},
            {"iteration": 2, "status": "VIOLATIONS_FOUND", "violation_count": 2, "violation_types": []},
            {"iteration": 3, "status": "COMPLIANCE_PASSED", "violation_count": 0, "violation_types": []},
        ]
        result = aggregator.aggregate(history)
        assert result["total_improvement"] == 5
        assert result["improvement_rate_pct"] == 100.0
        assert result["iterations_run"] == 3

    def test_no_improvement(self):
        history = [
            {"iteration": 1, "status": "VIOLATIONS_FOUND", "violation_count": 3, "violation_types": []},
            {"iteration": 2, "status": "VIOLATIONS_FOUND", "violation_count": 3, "violation_types": []},
        ]
        result = aggregator.aggregate(history)
        assert result["total_improvement"] == 0
        assert result["improvement_rate_pct"] == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# 5. reporter
# ──────────────────────────────────────────────────────────────────────────────

class TestReporter:
    def _make_plan(self):
        return ExecutionPlan(
            document_type="약관",
            product_name="실손의료보험",
            max_iterations=3,
            complexity="NORMAL",
        )

    def test_passed_report(self):
        plan = self._make_plan()
        result = reporter.build_final_report("COMPLIANCE_PASSED", None, plan, {}, 2)
        assert result["next_action"] == "PUBLISH_READY"
        assert "2회" in result["summary"]
        assert result["suggestions"] == []

    def test_manual_review_report(self):
        mock_report = MagicMock()
        mock_violation = MagicMock()
        mock_violation.violation_id = "V001"
        mock_violation.type.value = "OVERSTATEMENT"
        mock_violation.severity.value = "HIGH"
        mock_violation.reason = "과장 표현 제거 필요"
        mock_violation.original_text = "완벽하게 보장"
        mock_violation.manual_flag = False
        mock_report.violations = [mock_violation]

        plan = self._make_plan()
        result = reporter.build_final_report(
            "MANUAL_REVIEW_REQUIRED", mock_report, plan, {}, 3
        )
        assert result["next_action"] == "MANUAL_REVIEW_REQUIRED"
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["violation_id"] == "V001"

    def test_improvement_note_positive(self):
        aggregated = {"total_improvement": 3, "improvement_rate_pct": 60.0}
        plan = self._make_plan()
        result = reporter.build_final_report("COMPLIANCE_PASSED", None, plan, aggregated, 2)
        assert "3건 감소" in result["improvement_note"]

    def test_improvement_note_no_change(self):
        aggregated = {"total_improvement": 0, "improvement_rate_pct": 0.0}
        plan = self._make_plan()
        result = reporter.build_final_report("MANUAL_REVIEW_REQUIRED", MagicMock(violations=[]), plan, aggregated, 3)
        assert "변화가 없" in result["improvement_note"]


# ──────────────────────────────────────────────────────────────────────────────
# 데이터 파이프라인 연동 — request_handler.check_environment
# ──────────────────────────────────────────────────────────────────────────────

class TestCheckEnvironment:
    def test_mock_mode_when_no_env(self, monkeypatch):
        monkeypatch.delenv("DB_API_URL", raising=False)
        result = request_handler.check_environment()
        assert result["db_mode"] == "MOCK"
        assert result["db_api_url"] is None

    def test_live_mode_when_env_set(self, monkeypatch):
        monkeypatch.setenv("DB_API_URL", "http://localhost:8000")
        result = request_handler.check_environment()
        assert result["db_mode"] == "LIVE"
        assert result["db_api_url"] == "http://localhost:8000"


class TestPlannerDbMode:
    def test_plan_includes_db_mode_mock(self, valid_request, monkeypatch):
        monkeypatch.delenv("DB_API_URL", raising=False)
        plan = planner.build_plan(valid_request)
        assert plan.db_mode == "MOCK"
        assert plan.to_dict()["db_mode"] == "MOCK"

    def test_plan_includes_db_mode_live(self, valid_request, monkeypatch):
        monkeypatch.setenv("DB_API_URL", "http://localhost:8000")
        plan = planner.build_plan(valid_request)
        assert plan.db_mode == "LIVE"


class TestReporterDbWarning:
    def _make_plan(self, db_mode: str):
        return ExecutionPlan(
            document_type="약관",
            product_name="실손의료보험",
            max_iterations=3,
            complexity="NORMAL",
            db_mode=db_mode,
        )

    def test_db_warning_present_in_mock_mode(self):
        plan = self._make_plan("MOCK")
        result = reporter.build_final_report("COMPLIANCE_PASSED", None, plan, {}, 1)
        assert result["db_warning"] is not None
        assert "MOCK" in result["db_warning"]

    def test_no_db_warning_in_live_mode(self):
        plan = self._make_plan("LIVE")
        result = reporter.build_final_report("COMPLIANCE_PASSED", None, plan, {}, 1)
        assert result["db_warning"] is None


# ──────────────────────────────────────────────────────────────────────────────
# OrchestratorResult
# ──────────────────────────────────────────────────────────────────────────────

class TestOrchestratorResult:
    def test_to_dict_has_all_keys(self):
        result = OrchestratorResult(
            status="COMPLIANCE_PASSED",
            content="약관 내용",
            iteration=1,
        )
        d = result.to_dict()
        expected_keys = [
            "status", "content", "iteration", "violations_for_ui",
            "report", "error", "summary", "next_action",
            "improvement_note", "suggestions", "db_warning", "plan", "aggregated",
        ]
        for key in expected_keys:
            assert key in d, f"'{key}' 키가 반환 dict에 없습니다."
