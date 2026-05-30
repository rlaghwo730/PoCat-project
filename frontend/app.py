"""
실손의료보험 약관 초안 작성 — LangManus 아키텍처 프론트엔드
백엔드: http://localhost:8000 (FastAPI + LangGraph)
"""
import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import requests
from dotenv import load_dotenv

load_dotenv()

import streamlit as st

MAX_ITERATIONS = 3
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(
    page_title="실손의료보험 약관 초안 작성 에이전트",
    page_icon="📄",
    layout="wide",
)


# ── ui_config.json 로드 ───────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def load_ui_config():
    path = Path(__file__).parent / "data" / "ui_config.json"
    if not path.exists():
        raise FileNotFoundError(f"ui_config.json을 찾을 수 없습니다: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


config = load_ui_config()
steps = config["steps"]
total_steps = len(steps)


# ── 보험사별 자동 설정값 ──────────────────────────────────────────────────────
COMPANY_DEFAULTS = {
    "삼성화재": {
        "product_name": "무배당 삼성화재 실손의료비보험",
        "join_age_range": "0세~65세",
        "max_coverage_age": 100,
        "fetal_enrollment": "가능",
        "policy_loan": "가능",
        "coverage_limit_basic": "5천만원",
        "coverage_limit_noncovered": "5천만원",
        "coverage_limit_dosu": "350만원",
        "coverage_limit_injection": "250만원",
        "coverage_limit_mri": "300만원",
    },
    "DB손해보험": {
        "product_name": "무배당프로미라이프실손의료비보험",
        "join_age_range": "5세~99세",
        "max_coverage_age": 100,
        "fetal_enrollment": "가능",
        "policy_loan": "가능",
        "coverage_limit_basic": "5천만원",
        "coverage_limit_noncovered": "5천만원",
        "coverage_limit_dosu": "350만원",
        "coverage_limit_injection": "250만원",
        "coverage_limit_mri": "200만원",
    },
    "현대해상": {
        "product_name": "무배당 현대해상다이렉트실손의료비보장보험",
        "join_age_range": "태아~60세",
        "max_coverage_age": 100,
        "fetal_enrollment": "가능",
        "policy_loan": "가능",
        "coverage_limit_basic": "5천만원",
        "coverage_limit_noncovered": "5천만원",
        "coverage_limit_dosu": "350만원",
        "coverage_limit_injection": "250만원",
        "coverage_limit_mri": "300만원",
    },
}


def apply_company_defaults(company: str) -> None:
    for key, value in COMPANY_DEFAULTS.get(company, {}).items():
        st.session_state[key] = value
    st.session_state["company_last_applied"] = company


# ── 세션 초기화 ───────────────────────────────────────────────────────────────
def init_defaults():
    if "current_step" not in st.session_state:
        st.session_state.current_step = 0

    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid4())

    if "company_defaults_applied" not in st.session_state:
        for key, value in COMPANY_DEFAULTS["삼성화재"].items():
            st.session_state[key] = value
        st.session_state["company_defaults_applied"] = True
        st.session_state["company_last_applied"] = "삼성화재"

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
            elif ftype == "checkbox_all":
                st.session_state[key] = list(field.get("default", []))


init_defaults()


# ── 폼 렌더링 ─────────────────────────────────────────────────────────────────
def render_field(field):
    key = field["key"]
    label = field["label"]
    ftype = field["type"]

    if ftype == "fixed":
        st.text_input(label, value=field["fixed_value"], disabled=True, key=f"_fixed_{key}")
        st.caption(f"고정값 기준: {field['fixed_reason']}")

    elif ftype == "dropdown":
        if key == "insurance_company":
            st.selectbox(
                label,
                field["options"],
                key=key,
                on_change=lambda: apply_company_defaults(
                    st.session_state.get("insurance_company", "삼성화재")
                ),
            )
        else:
            st.selectbox(label, field["options"], key=key)

    elif ftype == "text":
        company = st.session_state.get("insurance_company", "삼성화재")
        widget_key = f"{key}__{company}"
        current_val = st.session_state.get(key, field.get("default", ""))

        noncovered_selected = bool(st.session_state.get("noncovered_rider_items", []))
        three_major_selected = bool(st.session_state.get("three_major_noncovered_items", []))

        noncovered_only_keys = ["coverage_limit_noncovered"]
        three_major_keys = ["coverage_limit_dosu", "coverage_limit_injection", "coverage_limit_mri"]

        if key in noncovered_only_keys and not noncovered_selected:
            st.text_input(label, value=current_val, key=widget_key, disabled=True)
            st.caption("※ 비급여 특약을 선택해야 활성화됩니다.")
        elif key in three_major_keys and not three_major_selected:
            st.text_input(label, value=current_val, key=widget_key, disabled=True)
            st.caption("※ 3대 비급여 세부항목을 선택해야 활성화됩니다.")
        else:
            new_val = st.text_input(label, value=current_val, key=widget_key)
            st.session_state[key] = new_val

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
        def _save(k=key):
            st.session_state[f"_saved_{k}"] = st.session_state.get(k)
        if f"_saved_{key}" not in st.session_state:
            st.session_state[f"_saved_{key}"] = st.session_state.get(key, field["options"][0])
        st.radio(label, field["options"], horizontal=True, key=key, on_change=_save)

    elif ftype == "checkbox_all":
        all_options = field["options"]
        current = st.session_state.get(key, [])

        if key == "noncovered_rider_items":
            include = st.checkbox(label, value=bool(current), key=f"_check_{key}")
            if not include:
                st.session_state["three_major_noncovered_items"] = []
                st.session_state["_check_three_major_noncovered_items"] = False
            st.session_state[key] = all_options if include else []

        elif key == "three_major_noncovered_items":
            noncovered = st.session_state.get("noncovered_rider_items", [])
            enabled = bool(noncovered)
            if not enabled:
                st.session_state[key] = []
            include = st.checkbox(
                label,
                value=bool(current) and enabled,
                key=f"_check_{key}",
                disabled=not enabled,
            )
            if not enabled:
                st.caption("※ 비급여 특약을 선택해야 활성화됩니다.")
            st.session_state[key] = all_options if (include and enabled) else []

        else:
            include = st.checkbox(label, value=bool(current), key=f"_check_{key}")
            st.session_state[key] = all_options if include else []

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


def build_request() -> dict:
    flat = {}
    for step in steps:
        for field in step["fields"]:
            flat[field["key"]] = get_field_value(field)

    return {
        "document_request": {
            "document_type":   "약관",
            "insurance_company": flat.get("insurance_company", "삼성화재"),
            "insurance_type":  flat.get("insurance_type", "일반 실손의료비보험"),
            "product_name":    flat["product_name"],
            "product_version": flat["product_version"],
            "dividend_type":   "무배당",
        },
        "product_design_conditions": {
            "policy_period":          flat["policy_period"],
            "premium_payment_period": flat["premium_payment_period"],
            "premium_payment_cycle":  flat.get("premium_payment_cycle", "월납"),
            "renewal_type":           flat["renewal_type"],
            "renewal_period":         flat["renewal_period"],
            "max_coverage_age":       flat["max_coverage_age"],
            "join_age_range":         flat["join_age_range"],
            "mandatory_enrollment":   flat.get("mandatory_enrollment", "해당없음"),
            "fetal_enrollment":       flat.get("fetal_enrollment", "가능"),
            "policy_loan":            flat.get("policy_loan", "불가"),
        },
        "coverage_conditions": {
            "basic_coverage_items":        flat["basic_coverage_items"],
            "noncovered_rider_items":      flat["noncovered_rider_items"],
            "three_major_noncovered_items": flat["three_major_noncovered_items"],
            "coverage_limit": {
                "급여":   flat.get("coverage_limit_basic", "5천만원"),
                "비급여": flat.get("coverage_limit_noncovered", "5천만원"),
                "도수치료": flat.get("coverage_limit_dosu", "350만원"),
                "주사료": flat.get("coverage_limit_injection", "250만원"),
                "MRI":  flat.get("coverage_limit_mri", "300만원"),
            },
            "deductible_rule": flat["deductible_rule"],
        },
        "applicant_info": {
            "applicant_type": flat.get("applicant_type", "본인"),
        },
        "session_id": st.session_state.session_id,
    }


# ── 위반 하이라이트 ───────────────────────────────────────────────────────────
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


def go_prev():
    st.session_state.current_step -= 1


def go_next():
    st.session_state.current_step += 1


# ── Header ────────────────────────────────────────────────────────────────────
st.title("📄 실손의료보험 약관 초안 작성 에이전트")
st.caption("RAG 기반으로 삼성화재·DB손해보험·현대해상 약관 데이터를 참고하여 새로운 약관 초안을 생성합니다.")
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
            if current_step == 2:
                basic_items = st.session_state.get("basic_coverage_items", [])
                if not basic_items:
                    st.button("다음 →", type="primary", use_container_width=True, disabled=True)
                    st.warning("⚠️ 기본 보장종목을 선택해야 다음 단계로 진행할 수 있습니다.")
                else:
                    st.button("다음 →", type="primary", on_click=go_next, use_container_width=True)
            else:
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


# ── Result panel ──────────────────────────────────────────────────────────────
with col_result:
    st.subheader("생성된 약관 초안")

    if generate_btn:
        session_id = st.session_state.session_id
        request = build_request()

        fetal_enrollment = st.session_state.get("_saved_fetal_enrollment", "가능")
        applicant_type   = st.session_state.get("applicant_type", "본인")
        if fetal_enrollment == "불가" and applicant_type == "태아":
            st.error("⚠️ 태아 가입이 불가능합니다.")
        else:
            try:
                with st.status("약관 초안 생성 중...", expanded=True) as status:
                    st.write("백엔드 LangGraph 워크플로우 실행 중...")
                    resp = requests.post(
                        f"{BACKEND_URL}/generate",
                        json=request,
                        timeout=300,
                    )
                    resp.raise_for_status()
                    result = resp.json()

                    final_status = result["status"]
                    if final_status == "COMPLIANCE_PASSED":
                        status.update(
                            label=f"약관 초안 생성 완료 — {result['iteration']}회 검토 통과",
                            state="complete",
                        )
                    elif final_status == "MANUAL_REVIEW_REQUIRED":
                        status.update(
                            label=f"최대 {MAX_ITERATIONS}회 도달 — 수동 검토 필요",
                            state="error",
                        )
                    else:
                        status.update(label="오류 발생", state="error")

                if final_status == "COMPLIANCE_PASSED":
                    st.success(
                        f"✅ 법규 검토 통과 — {result['iteration']}회 만에 완료 "
                        f"(세션 ID: {session_id})"
                    )
                elif final_status == "MANUAL_REVIEW_REQUIRED":
                    st.error(
                        f"⚠️ MANUAL_REVIEW_REQUIRED — {MAX_ITERATIONS}회 재생성 후에도 "
                        "법규 준수 미달. 담당자 수동 검토가 필요합니다."
                    )
                    if result.get("suggestions"):
                        with st.expander("📋 수동 검토 필요 항목 상세보기"):
                            for s in result["suggestions"]:
                                manual = " 🔴 반복 위반" if s.get("requires_manual_review") else ""
                                st.markdown(
                                    f"- **[{s['severity']}] {s['type']}**{manual}\n\n"
                                    f"  {s['action']}\n\n"
                                    f"  > 대상 문구: `{s['target_text']}`"
                                )
                elif final_status == "ORCHESTRATOR_ERROR":
                    st.error(f"시스템 오류: {result.get('error', '알 수 없는 오류')}")

                if result.get("db_warning"):
                    st.warning(f"⚠️ {result['db_warning']}")

                if result.get("improvement_note"):
                    st.info(f"📊 {result['improvement_note']}")

                tab_clause, tab_desc, tab_biz = st.tabs(["약관", "상품설명서", "사업방법서"])

                with tab_clause:
                    highlighted = apply_violation_highlights(
                        result["content"],
                        result.get("violations_for_ui", []),
                    )
                    st.markdown(highlighted, unsafe_allow_html=True)

                with tab_desc:
                    st.markdown(result.get("product_description", ""))

                with tab_biz:
                    st.markdown(result.get("business_method", ""))

            except requests.exceptions.ConnectionError:
                st.error(
                    f"백엔드 서버에 연결할 수 없습니다. "
                    f"`python backend/main.py` 로 서버를 먼저 실행하세요. "
                    f"(URL: {BACKEND_URL})"
                )
            except requests.exceptions.Timeout:
                st.error("요청 시간 초과 (300초). 서버 부하를 확인하거나 다시 시도하세요.")
            except requests.exceptions.HTTPError as e:
                detail = ""
                try:
                    detail = e.response.json().get("detail", e.response.text)
                except Exception:
                    detail = e.response.text
                st.error(f"API 오류 {e.response.status_code}: {detail}")
            except Exception as e:
                st.error(f"오류 발생: {e}")
                st.exception(e)

    else:
        st.caption("좌측 설정을 입력하고 '약관 초안 생성' 버튼을 클릭하세요.")
        st.info(
            "**생성 흐름 (LangManus 아키텍처)**\n"
            "1. Coordinator: 요청 유효성 검증\n"
            "2. Planner: 실행 계획 수립\n"
            "3. Generation: RAG + LLM으로 약관 초안 생성\n"
            "4. Compliance: 법규 준수 검증 (5개 룰)\n"
            "5. Supervisor: 재생성 or 편집 결정\n"
            "6. Edit: 최종 편집 및 상품설명서 생성"
        )
