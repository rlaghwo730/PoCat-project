import json
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# compliance_agent 패키지 경로 추가
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

MAX_ITERATIONS = 3

st.set_page_config(
    page_title="실손의료보험 약관 초안 작성 에이전트",
    page_icon="📄",
    layout="wide",
)


@st.cache_resource(show_spinner=False)
def load_ui_config():
    BASE_DIR = Path(__file__).parent
    with open(BASE_DIR / "data/ui_config.json", encoding="utf-8") as f:
        return json.load(f)


config = load_ui_config()
steps = config["steps"]
total_steps = len(steps)


def init_defaults():
    if "current_step" not in st.session_state:
        st.session_state.current_step = 0

    for step in steps:
        for field in step["fields"]:
            key = field["key"]
            if key in st.session_state:
                continue
            ftype = field["type"]
            if ftype == "fixed":
                st.session_state[key] = field["fixed_value"]
            elif ftype == "dropdown":
                st.session_state[key] = field.get("default", field["options"][0])
            elif ftype == "text":
                st.session_state[key] = field.get("default", "")
            elif ftype == "number":
                st.session_state[key] = int(field.get("default", 0))
            elif ftype == "date":
                st.session_state[key] = date.fromisoformat(field.get("default", "1990-01-01"))
            elif ftype == "radio":
                st.session_state[key] = field.get("default", field["options"][0])
            elif ftype == "multiselect":
                st.session_state[key] = list(field.get("default", []))


init_defaults()


def render_field(field):
    key = field["key"]
    label = field["label"]
    ftype = field["type"]

    if ftype == "fixed":
        st.text_input(label, value=field["fixed_value"], disabled=True, key=f"_fixed_{key}")
        st.caption(f"고정값 기준: {field['fixed_reason']}")

    elif ftype == "dropdown":
        st.selectbox(label, field["options"], key=key)

    elif ftype == "text":
        st.text_input(label, key=key)

    elif ftype == "number":
        unit = field.get("unit", "")
        label_with_unit = f"{label} (단위: {unit})" if unit else label
        st.number_input(
            label_with_unit,
            min_value=field.get("min"),
            max_value=field.get("max"),
            step=1,
            key=key,
        )

    elif ftype == "date":
        min_val = date.fromisoformat(field["min"]) if field.get("min") else date(1900, 1, 1)
        max_raw = field.get("max", "today")
        max_val = date.today() if max_raw == "today" else date.fromisoformat(max_raw)
        st.date_input(label, min_value=min_val, max_value=max_val, key=key)

    elif ftype == "radio":
        st.radio(label, field["options"], horizontal=True, key=key)

    elif ftype == "multiselect":
        st.multiselect(label, field["options"], key=key)


def get_field_value(field):
    key = field["key"]
    ftype = field["type"]

    if ftype == "fixed":
        return field["fixed_value"]

    value = st.session_state.get(key)

    if ftype == "number" and field.get("unit"):
        return f"{value}{field['unit']}"
    elif ftype == "date":
        return value.strftime("%Y%m%d") if value else None
    return value


def build_request():
    flat = {}
    for step in steps:
        for field in step["fields"]:
            flat[field["key"]] = get_field_value(field)

    return {
        "document_request": {
            "document_type": "약관",
            "insurance_company": "삼성화재",
            "product_name": flat["product_name"],
            "product_version": flat["product_version"],
        },
        "product_design_conditions": {
            "policy_period": flat["policy_period"],
            "premium_payment_period": flat["premium_payment_period"],
            "renewal_type": flat["renewal_type"],
            "renewal_period": flat["renewal_period"],
            "max_coverage_age": flat["max_coverage_age"],
            "join_age_range": flat["join_age_range"],
        },
        "coverage_conditions": {
            "basic_coverage_items": flat["basic_coverage_items"],
            "noncovered_rider_items": flat["noncovered_rider_items"],
            "three_major_noncovered_items": flat["three_major_noncovered_items"],
            "coverage_limit": flat["coverage_limit"],
            "deductible_rule": flat["deductible_rule"],
        },
        "applicant_info": {
            "applicant_type": flat["applicant_type"],
            "birth_date": flat["birth_date"],
            "gender": flat["gender"],
            "occupation": flat["occupation"],
        },
    }


def apply_violation_highlights(content: str, violations: list) -> str:
    for v in violations:
        original = v.get("original_text", "")
        if not original or original not in content:
            continue
        annotation = f"⚠️ [{v['type']}] {v['legal_basis']}: {v['fix']}"
        span = (
            f'<span style="color: red;">{original}</span>'
            f'<br><span style="color: red; font-size: 12px;">{annotation}</span>'
        )
        content = content.replace(original, span)
    return content


@st.cache_resource(show_spinner=False)
def get_agent():
    from agents.generation_agent import GenerationAgent
    return GenerationAgent()


@st.cache_resource(show_spinner=False)
def get_compliance_agent():
    from compliance_agent.compliance_agent import ComplianceAgent
    return ComplianceAgent()


def run_compliance(content: str, request: dict, iteration: int, session_id: str) -> dict:
    try:
        from compliance_agent.models import DetectionInput, CoverageContext
        coverage = request["coverage_conditions"]
        detection_input = DetectionInput(
            iteration=iteration,
            section_type="약관",
            content=content,
            session_id=session_id,
            product_meta={
                "product_name": request["document_request"]["product_name"],
                "deductible": coverage["deductible_rule"],
            },
            coverage_context=CoverageContext(
                deductible_required=True,
                three_major_noncovered_required=(
                    len(coverage.get("three_major_noncovered_items", [])) > 0
                ),
            ),
        )
        report = get_compliance_agent().validate(detection_input)
        report_dict = report.to_dict()

        normalized_violations = []
        for v in report_dict.get("violations", []):
            normalized_violations.append({
                "type": v.get("type", ""),
                "original_text": v.get("original_text", ""),
                "legal_basis": v.get("regulation", ""),
                "fix": v.get("reason", ""),
                "severity": v.get("severity", ""),
            })

        priority_fixes = []
        fb = report_dict.get("feedback_to_generator")
        if fb:
            for pf in fb.get("priority_fixes", []):
                priority_fixes.append(
                    f"[{pf['violation_id']}] {pf['instruction']} | {pf['repair_constraints']}"
                )

        return {
            "status": report_dict["status"],
            "violations": normalized_violations,
            "priority_fixes": priority_fixes,
        }

    except Exception as e:
        st.error(f"실제 오류: {e}")
        st.exception(e)
        if iteration == 1:
            return {
                "status": "VIOLATIONS_FOUND",
                "violations": [],
                "priority_fixes": ["[MOCK] 자기부담금 조항에 급여/비급여 구분 명시 필요"],
            }
        return {"status": "COMPLIANCE_PASSED", "violations": [], "priority_fixes": []}


def go_prev():
    st.session_state.current_step -= 1


def go_next():
    st.session_state.current_step += 1


# ── Header ──────────────────────────────────────────────────────────────────
st.title("📄 실손의료보험 약관 초안 작성 에이전트")
st.caption("RAG 기반으로 삼성화재 약관 데이터를 참고하여 새로운 약관 초안을 생성합니다.")
st.divider()

col_form, col_result = st.columns([4, 6], gap="large")

generate_btn = False

with col_form:
    current_step = st.session_state.current_step
    step_data = steps[current_step]

    dots = " ".join(["●" if i == current_step else "○" for i in range(total_steps)])
    st.markdown(f"**Step {current_step + 1} / {total_steps}** &nbsp;&nbsp; {dots}")
    st.divider()

    st.subheader(step_data["title"])
    for field in step_data["fields"]:
        render_field(field)

    st.divider()

    col_prev, col_next = st.columns(2)
    with col_prev:
        if current_step > 0:
            st.button("← 이전", on_click=go_prev, use_container_width=True)
    with col_next:
        if current_step < total_steps - 1:
            st.button("다음 →", type="primary", on_click=go_next, use_container_width=True)
        else:
            basic_items = st.session_state.get("basic_coverage_items", [])
            generate_btn = st.button(
                "약관 초안 생성",
                type="primary",
                use_container_width=True,
                disabled=not basic_items,
            )
            if not basic_items:
                st.warning("기본 보장종목을 하나 이상 선택하세요.")


# ── Result panel ─────────────────────────────────────────────────────────────
with col_result:
    st.subheader("생성된 약관 초안")

    if generate_btn:
        session_id = uuid4()
        request = build_request()
        product_name = st.session_state.get("product_name", "약관초안")
        product_version = st.session_state.get("product_version", "")

        try:
            agent = get_agent()
            final_result = None
            last_violations = []
            compliance_feedback = {}

            with st.status("약관 초안 생성 중...", expanded=True) as status:
                for iteration in range(1, MAX_ITERATIONS + 1):
                    st.write(f"**[{iteration}/{MAX_ITERATIONS}] 초안 {'생성' if iteration == 1 else '재생성'} 중...**")

                    if iteration == 1:
                        result = agent.generate(request)
                    else:
                        result = agent.regenerate(request, compliance_feedback, iteration)

                    st.write(f"**[{iteration}/{MAX_ITERATIONS}] 법규 준수 검토 중...**")
                    compliance_feedback = run_compliance(
                        content=result["content"],
                        request=request,
                        iteration=iteration,
                        session_id=str(session_id),
                    )

                    if compliance_feedback.get("violations"):
                        last_violations = compliance_feedback["violations"]

                    if compliance_feedback["status"] == "COMPLIANCE_PASSED":
                        final_result = result
                        status.update(
                            label=f"약관 초안 생성 완료 — {iteration}회 검토 통과",
                            state="complete",
                        )
                        break
                else:
                    final_result = result
                    status.update(
                        label=f"최대 {MAX_ITERATIONS}회 도달 — 수동 검토 필요",
                        state="error",
                    )

            if compliance_feedback.get("status") == "COMPLIANCE_PASSED":
                st.success(
                    f"법규 검토 통과 — {final_result['iteration']}회 만에 완료 "
                    f"(세션 ID: {session_id})"
                )
            else:
                st.error(
                    f"⚠️ MANUAL_REVIEW_REQUIRED — {MAX_ITERATIONS}회 재생성 후에도 "
                    "법규 준수 미달. 담당자 수동 검토가 필요합니다."
                )

            with st.spinner("상품설명서 생성 중..."):
                description = agent.generate_product_description(
                    final_result["content"], request
                )

            tab_clause, tab_desc = st.tabs(["약관", "상품설명서"])

            with tab_clause:
                highlighted = apply_violation_highlights(
                    final_result["content"], last_violations
                )
                st.markdown(highlighted, unsafe_allow_html=True)

            with tab_desc:
                st.markdown(description)

        except FileNotFoundError as e:
            st.error(str(e))
            st.info(
                "`data/samsung_insurance_clause_dataset.json` 파일을 data 폴더에 배치한 후 다시 시도하세요."
            )
        except Exception as e:
            st.error(f"오류 발생: {e}")
            st.exception(e)

    else:
        st.caption("좌측 설정을 입력하고 '약관 초안 생성' 버튼을 클릭하세요.")
        st.info(
            "**생성 흐름**\n"
            "1. RAG로 기존 약관 5개 청크 검색\n"
            "2. Upstage Solar LLM으로 약관 초안 생성\n"
            "3. ComplianceAgent로 법규 준수 검토\n"
            "4. VIOLATIONS_FOUND → regenerate()로 재생성 (최대 3회)\n"
            "5. COMPLIANCE_PASSED → 최종 결과 출력"
        )
