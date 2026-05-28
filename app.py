"""
실손의료보험 약관 초안 작성 — 총괄 오케스트레이터 UI
"""
import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

import orchestrator  # noqa: F401
from orchestrator.orchestrator import Orchestrator

MAX_ITERATIONS = 3

st.set_page_config(
    page_title="실손의료보험 약관 초안 작성 에이전트",
    page_icon="📄",
    layout="wide",
)


# ── ui_config.json 로드 ───────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def load_ui_config():
    path = Path(__file__).parent / "orchestrator" / "data" / "ui_config.json"
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
    """보험사 선택 시 관련 필드값을 자동으로 업데이트한다."""
    for key, value in COMPANY_DEFAULTS.get(company, {}).items():
        st.session_state[key] = value
    st.session_state["company_last_applied"] = company


# ── 세션 초기화 ───────────────────────────────────────────────────────────────
def init_defaults():
    if "current_step" not in st.session_state:
        st.session_state.current_step = 0

    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid4())

    # 처음 로드 시 삼성화재 기본값 먼저 적용
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
                on_change=lambda: apply_company_defaults(st.session_state.get("insurance_company", "삼성화재")),
            )
        else:
            st.selectbox(label, field["options"], key=key)

    elif ftype == "text":
        # 보험사 변경 시 위젯 강제 재렌더링을 위해 보험사명을 key에 포함
        company = st.session_state.get("insurance_company", "삼성화재")
        widget_key = f"{key}__{company}"
        current_val = st.session_state.get(key, field.get("default", ""))

        # 비급여/3대비급여 미선택 시 해당 한도 필드 비활성화
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
            include = st.checkbox(
                label,
                value=bool(current),
                key=f"_check_{key}",
            )
            if not include:
                # 비급여 특약 해제 시 3대 비급여도 자동 해제
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
            include = st.checkbox(
                label,
                value=bool(current),
                key=f"_check_{key}",
            )
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
            "document_type": "약관",
            "insurance_company": flat.get("insurance_company", "삼성화재"),
            "insurance_type": flat.get("insurance_type", "일반 실손의료비보험"),
            "product_name": flat["product_name"],
            "product_version": flat["product_version"],
            "dividend_type": "무배당",
        },
        "product_design_conditions": {
            "policy_period": flat["policy_period"],
            "premium_payment_period": flat["premium_payment_period"],
            "premium_payment_cycle": flat.get("premium_payment_cycle", "월납"),
            "renewal_type": flat["renewal_type"],
            "renewal_period": flat["renewal_period"],
            "max_coverage_age": flat["max_coverage_age"],
            "join_age_range": flat["join_age_range"],
            "mandatory_enrollment": flat.get("mandatory_enrollment", "해당없음"),
            "fetal_enrollment": flat.get("fetal_enrollment", "가능"),
            "policy_loan": flat.get("policy_loan", "불가"),
        },
        "coverage_conditions": {
            "basic_coverage_items": flat["basic_coverage_items"],
            "noncovered_rider_items": flat["noncovered_rider_items"],
            "three_major_noncovered_items": flat["three_major_noncovered_items"],
            "coverage_limit": {
                "급여": flat.get("coverage_limit_basic", "5천만원"),
                "비급여": flat.get("coverage_limit_noncovered", "5천만원"),
                "도수치료": flat.get("coverage_limit_dosu", "350만원"),
                "주사료": flat.get("coverage_limit_injection", "250만원"),
                "MRI": flat.get("coverage_limit_mri", "300만원"),
            },
            "deductible_rule": flat["deductible_rule"],
        },
        "applicant_info": {
            "applicant_type": flat.get("applicant_type", "본인"),
        },
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


# ── Orchestrator 캐시 ─────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_orchestrator() -> Orchestrator:
    return Orchestrator()


def generate_business_method(request: dict) -> str:
    """사업방법서 JSON 데이터에서 해당 보험사 데이터를 찾아 반환한다."""
    # 환경변수 우선, 없으면 프로젝트 루트 기준으로 자동 탐색
    gen_agent_dir = os.getenv("GENERATION_AGENT_DIR", "")
    if gen_agent_dir:
        data_path = Path(gen_agent_dir) / "data" / "일반_사업방법서_3사통합.json"
    else:
        data_path = Path(__file__).parent / "generation_agent" / "data" / "일반_사업방법서_3사통합.json"
    if not data_path.exists():
        return "사업방법서 데이터 파일을 찾을 수 없습니다."
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)
    company = request["document_request"].get("insurance_company", "삼성화재")
    chunks = [
        item["page_content"]
        for item in data
        if item.get("metadata", {}).get("company") == company
    ]
    if not chunks:
        chunks = [item["page_content"] for item in data]
    return "\n\n".join(chunks)


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
            # Step 3(보장조건)에서 기본보장종목 미선택 시 다음 차단
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

        # 태아 가입 불가인데 태아를 선택한 경우 차단
        fetal_enrollment = st.session_state.get("_saved_fetal_enrollment", "가능")
        applicant_type = st.session_state.get("applicant_type", "본인")
        if fetal_enrollment == "불가" and applicant_type == "태아":
            st.error("⚠️ 태아 가입이 불가능합니다. 상품 설계 조건에서 태아 가입 가능 여부를 확인하거나 가입자 유형을 변경해주세요.")
        else:
            try:
                orch = get_orchestrator()

                with st.status("약관 초안 생성 중...", expanded=True) as status:
                    result = orch.run(
                        request=request,
                        session_id=session_id,
                        status_callback=lambda msg: st.write(msg),
                    )

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
                        status.update(
                            label=f"오류 발생: {result.get('error', '알 수 없는 오류')}",
                            state="error",
                        )

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
                    st.error(f"시스템 오류: {result.get('error')}")

                if result.get("db_warning"):
                    st.warning(f"⚠️ {result['db_warning']}")

                if result.get("improvement_note"):
                    st.info(f"📊 {result['improvement_note']}")

                with st.spinner("상품설명서 생성 중..."):
                    description = orch.generate_description(result["content"], request)

                with st.spinner("사업방법서 불러오는 중..."):
                    business_method = generate_business_method(request)

                tab_clause, tab_desc, tab_biz = st.tabs(["약관", "상품설명서", "사업방법서"])

                with tab_clause:
                    highlighted = apply_violation_highlights(
                        result["content"],
                        result.get("violations_for_ui", []),
                    )
                    st.markdown(highlighted, unsafe_allow_html=True)

                with tab_desc:
                    st.markdown(description)

                with tab_biz:
                    st.markdown(business_method)

            except FileNotFoundError as e:
                st.error(str(e))
                st.info("데이터 파일을 generation_agent/data 폴더에 배치한 후 다시 시도하세요.")
            except Exception as e:
                st.error(f"오류 발생: {e}")
                st.exception(e)

    else:
        st.caption("좌측 설정을 입력하고 '약관 초안 생성' 버튼을 클릭하세요.")
        st.info(
            "**생성 흐름**\n"
            "1. 요청 검증 및 작업 계획 수립\n"
            "2. RAG로 기존 약관 5개 청크 검색\n"
            "3. Ollama(qwen2.5:14b)로 약관 초안 생성\n"
            "4. ComplianceAgent로 법규 준수 검토 (실제 규제 DB 연동)\n"
            "5. VIOLATIONS_FOUND → regenerate()로 재생성 (최대 3회)\n"
            "6. COMPLIANCE_PASSED → 최종 결과 출력 / 미통과 → 수동 검토 안내"
        )
