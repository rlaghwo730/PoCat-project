"""
ComplianceAgent 수동 테스트 스크립트.

실행:
    python demo.py

LLM(Rule 2, 3)은 Anthropic API 키가 있으면 실제 호출,
없으면 --no-llm 플래그로 건너뜀.

    python demo.py --no-llm
"""
from __future__ import annotations

import argparse
import json
import sys

from compliance_agent.compliance_agent import ComplianceAgent
from compliance_agent.models import DetectionInput

# ── 테스트 시나리오 ─────────────────────────────────────────────────────────────

# 시나리오 1: 위반이 잔뜩 있는 약관
DIRTY_CONTENT = """
제1조 (보장 내용)
본 상품은 실손 의료비를 전액보장합니다. 입원·통원 구분 없이 무한 보장이 적용됩니다.
반드시 보장되며 절대 보장이 가능한 업계 최초 상품입니다.

제2조 (지급 기준)
상당한 사유가 있다고 인정되는 경우 보험금을 지급합니다.
적절한 기간 내에 통상적인 방법으로 청구하시기 바랍니다.

제3조 (보험기간)
보험기간은 1년입니다.
"""

# 시나리오 2: 위반이 없는 깨끗한 약관
CLEAN_CONTENT = """
제1조 (보험금 지급 사유)
피보험자가 보험사고로 인하여 입원 치료를 받은 경우 보험금을 지급합니다.
자기부담금은 10,000원이며 보장 한도 내에서 실손 의료비를 지급합니다.
면책 사항에 해당하는 경우 보장하지 않습니다.

제2조 (보험료 납입)
보험료는 매월 납입합니다. 계약 해지 시 환급금이 지급됩니다.

제3조 (분쟁 조정)
분쟁조정은 금융감독원에 신청할 수 있습니다.

제4조 (보험기간)
보험기간은 1년이며 갱신 시 보험료가 변경될 수 있습니다.

제5조 (청구 절차)
보험금 청구 시 청구서류를 제출해야 합니다. 계약자는 알릴 의무가 있습니다.

제6조 (갱신 거절)
고지의무 위반 등 갱신 거절 사유에 해당하면 재가입이 제한될 수 있습니다.
"""

# 시나리오 3: FAIL_LOOP 확인용 — 두 번 연속 같은 위반이 나오는 경우
REPEATED_VIOLATION_CONTENT = "전액보장 상품입니다. 원금 보장이 됩니다."

# 시나리오 4: 잘못된 section_type → silent skip 방지 확인
INVALID_SECTION_CONTENT = "보험금 지급 사유가 있는 경우 지급합니다."


# ── 출력 헬퍼 ──────────────────────────────────────────────────────────────────

def _hr(title: str = "") -> None:
    width = 60
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print("─" * width)


def _print_report(report_dict: dict) -> None:
    status = report_dict["status"]
    iteration = report_dict["iteration"]
    violations = report_dict.get("violations", [])

    color = "\033[92m" if status == "COMPLIANCE_PASSED" else "\033[93m"
    reset = "\033[0m"
    print(f"{color}[{status}]{reset}  iteration={iteration}  위반={len(violations)}건")

    for v in violations:
        sev_color = "\033[91m" if v["severity"] in ("CRITICAL", "HIGH") else "\033[93m"
        print(f"  {sev_color}[{v['severity']}]{reset} {v['violation_id']}  {v['type']}")
        print(f"         원문: {v['original_text'][:60]}")
        print(f"         근거: {v['regulation']}")
        print(f"         사유: {v['reason'][:80]}")

    if "feedback_to_generator" in report_dict:
        fixes = report_dict["feedback_to_generator"]["priority_fixes"]
        print(f"\n  → 생성 에이전트 수정 지시 ({len(fixes)}건):")
        for f in fixes[:3]:  # 상위 3건만 표시
            print(f"    - [{f['violation_id']}] {f['instruction']}")
            print(f"      제약: {f['repair_constraints'][:80]}")

    if "final_validation" in report_dict:
        fv = report_dict["final_validation"]
        print(f"\n  신뢰도: {fv['confidence_score']}  checks: {fv['checks']}")
        print(f"  next_action: {report_dict.get('next_action')}")


# ── 시나리오 실행 ───────────────────────────────────────────────────────────────

def run_scenario_1(no_llm: bool) -> None:
    _hr("시나리오 1: 위반 다수 → OUTPUT A")
    agent = ComplianceAgent()
    if no_llm:
        _patch_llm(agent)

    data = DetectionInput(
        iteration=1,
        session_id="demo-session-1",
        section_type="약관",
        content=DIRTY_CONTENT,
        product_meta={"product_name": "테스트 실손보험", "deductible": 10000},
    )
    report = agent.validate(data)
    _print_report(report.to_dict())


def run_scenario_2(no_llm: bool) -> None:
    _hr("시나리오 2: 위반 없음 → OUTPUT B (COMPLIANCE_PASSED)")
    agent = ComplianceAgent()
    if no_llm:
        _patch_llm(agent)

    data = DetectionInput(
        iteration=1,
        session_id="demo-session-2",
        section_type="약관",
        content=CLEAN_CONTENT,
        product_meta={"product_name": "테스트 실손보험", "deductible": 10000},
    )
    report = agent.validate(data)
    _print_report(report.to_dict())


def run_scenario_3(no_llm: bool) -> None:
    _hr("시나리오 3: FAIL_LOOP 감지 (같은 위반이 3회 반복)")
    agent = ComplianceAgent()
    if no_llm:
        _patch_llm(agent)

    for i in range(1, 4):
        data = DetectionInput(
            iteration=i,
            session_id="demo-session-3",
            section_type="약관",
            content=REPEATED_VIOLATION_CONTENT,
        )
        report = agent.validate(data)
        status = report.status
        next_action = report.next_action or ""
        print(f"  iteration {i}: {status}  next_action={next_action or '(계속)'}")
        if "FAIL" in next_action or status == "COMPLIANCE_PASSED":
            break

    print(f"\n  최종 결과: {report.next_action}")


def run_scenario_4() -> None:
    _hr("시나리오 4: 잘못된 section_type → CRITICAL 위반 반환 (silent skip 방지)")
    agent = ComplianceAgent()

    data = DetectionInput(
        iteration=1,
        session_id="demo-session-4",
        section_type="계약서",  # 유효하지 않은 값
        content=INVALID_SECTION_CONTENT,
    )
    report = agent.validate(data)
    violations = report.to_dict()["violations"]
    invalid_v = [v for v in violations if v["violation_id"] == "VIO_MRQ_INVALID_SECTION"]
    if invalid_v:
        print(f"  [OK] VIO_MRQ_INVALID_SECTION CRITICAL 위반 정상 반환")
        print(f"       사유: {invalid_v[0]['reason']}")
    else:
        print("  [FAIL] INVALID_SECTION 위반이 반환되지 않음")


def run_scenario_5(no_llm: bool) -> None:
    _hr("시나리오 5: 2-iteration 루프 시뮬레이션 (위반 → 수정 → PASS)")
    agent = ComplianceAgent()
    if no_llm:
        _patch_llm(agent)

    contents = [
        DIRTY_CONTENT,   # iteration 1: 위반 있음
        CLEAN_CONTENT,   # iteration 2: 수정 완료
    ]

    for i, content in enumerate(contents, start=1):
        print(f"\n  [iteration {i}]")
        data = DetectionInput(
            iteration=i,
            session_id="demo-session-5",
            section_type="약관",
            content=content,
        )
        report = agent.validate(data)
        d = report.to_dict()
        print(f"  status={d['status']}  위반={len(d['violations'])}건  "
              f"next_action={d.get('next_action', '(계속)')}")
        if d["status"] == "COMPLIANCE_PASSED":
            fv = d["final_validation"]
            print(f"  confidence_score={fv['confidence_score']}")


# ── LLM 패치 ──────────────────────────────────────────────────────────────────

def _patch_llm(agent: ComplianceAgent) -> None:
    """--no-llm 모드: Rule 2, 3 탐지기를 빈 리스트 반환으로 교체한다."""
    from compliance_agent.detection_engine import violation_detector as vd
    vd.ViolationDetector._run_subjective = lambda self, d: []
    vd.ViolationDetector._run_contradiction = lambda self, d: []
    print("  [INFO] LLM 탐지기(Rule 2, 3) 비활성화됨 (--no-llm)")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="ComplianceAgent 데모")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Rule 2(SUBJECTIVE), Rule 3(CONTRADICTION) LLM 호출 건너뜀",
    )
    parser.add_argument(
        "--scenario",
        type=int,
        choices=[1, 2, 3, 4, 5],
        help="실행할 시나리오 번호 (생략 시 전체 실행)",
    )
    args = parser.parse_args()

    scenarios = {
        1: lambda: run_scenario_1(args.no_llm),
        2: lambda: run_scenario_2(args.no_llm),
        3: lambda: run_scenario_3(args.no_llm),
        4: run_scenario_4,
        5: lambda: run_scenario_5(args.no_llm),
    }

    targets = [args.scenario] if args.scenario else list(scenarios.keys())
    for n in targets:
        scenarios[n]()

    _hr()
    print("완료")


if __name__ == "__main__":
    main()
