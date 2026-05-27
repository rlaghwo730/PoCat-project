"""
실손의료보험 약관 초안 작성 — 총괄 오케스트레이터 UI

기존 generation_agent/app.py의 Streamlit UI를 그대로 유지하되,
mock_compliance() + 수동 generate/regenerate 루프를
Orchestrator.run()으로 완전히 대체한다.
"""
import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv

import orchestrator  # noqa: F401 — __init__.py의 sys.path 보정을 트리거
from orchestrator.orchestrator import Orchestrator

load_dotenv()

MAX_ITERATIONS = 3

st.set_page_config(
    page_title="실손의료보험 약관 초안 작성 에이전트",
    page_icon="📄",
    layout="wide",
)


# ── ui_config.json 로드 ───────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def load_ui_config():
    """generation_agent/data/ui_config.json을 탐색해서 로드한다."""
    candidates = [
        # orchestrator 프로젝트와 poact_agent_my가 Desktop에 나란히 있는 경우
        Path(__file__).parent.parent / "poact_agent_my" / "generation_agent" / "data" / "ui_config.json",
        # 환경변수로 명시적으로 지정한 경우
        Path(os.getenv("GENERATION_AGENT_DIR", "")) / "data" / "ui_config.json",
    ]
    for path in candidates:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(
        "ui_config.json을 찾을 수 없습니다. "
        "GENERATION_AGENT_DIR 환경변수로 generation_agent 경로를 지정하거나 "
        "poact_agent_my 폴더가 Desktop에 있는지 확인하세요."
    )


config = load_ui_config()
steps = config["steps"]
total_steps = len(steps)


# ── 세션 초기화 ───────────────────────────────────────────────────────────────
def init_defaults():
    if "current_step" not in st.session_state:
        st.session_state.current_step = 0

    # session_id는 ComplianceAgent의 IterationTracker가 SOFT_LOOP을 감지하기 위해
    # 동일 세션 내에서 고정되어야 한다.
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid4())

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


# ── 폼 렌더링 ─────────────────────────────────────────────────────────────────
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


def build_request() -> dict:
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


# ── 위반 하이라이트 ───────────────────────────────────────────────────────────
def apply_violation_highlights(content: str, violations: list) -> str:
    """violations_for_ui 리스트를 받아 약관 텍스트에 빨간색 하이라이트를 적용한다."""
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


def go_prev():
    st.session_state.current_step -= 1


def go_next():
    st.session_state.current_step += 1


# ── Header ────────────────────────────────────────────────────────────────────
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


# ── Result panel ──────────────────────────────────────────────────────────────
with col_result:
    st.subheader("생성된 약관 초안")

    if generate_btn:
        session_id = st.session_state.session_id
        request = build_request()

        try:
            orch = get_orchestrator()

            # ── 오케스트레이터 실행 ───────────────────────────────────────
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

            # ── 상태 배너 ─────────────────────────────────────────────────
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

            # ── 데이터 파이프라인 DB 경고 ─────────────────────────────────
            if result.get("db_warning"):
                st.warning(f"⚠️ {result['db_warning']}")

            # ── 개선 추이 ─────────────────────────────────────────────────
            if result.get("improvement_note"):
                st.info(f"📊 {result['improvement_note']}")

            # ── 상품설명서 생성 ───────────────────────────────────────────
            with st.spinner("상품설명서 생성 중..."):
                description = orch.generate_description(result["content"], request)

            # ── 탭 출력 ───────────────────────────────────────────────────
            tab_clause, tab_desc = st.tabs(["약관", "상품설명서"])

            with tab_clause:
                highlighted = apply_violation_highlights(
                    result["content"],
                    result.get("violations_for_ui", []),
                )
                st.markdown(highlighted, unsafe_allow_html=True)

            with tab_desc:
                st.markdown(description)

        except FileNotFoundError as e:
            st.error(str(e))
            st.info(
                "`samsung_insurance_clause_dataset.json` 파일을 "
                "generation_agent/data 폴더에 배치한 후 다시 시도하세요."
            )
        except Exception as e:
            st.error(f"오류 발생: {e}")
            st.exception(e)

    else:
        st.caption("좌측 설정을 입력하고 '약관 초안 생성' 버튼을 클릭하세요.")
        st.info(
            "**생성 흐름**\n"
            "1. 요청 검증 및 작업 계획 수립\n"
            "2. RAG로 기존 약관 5개 청크 검색\n"
            "3. Upstage Solar LLM으로 약관 초안 생성\n"
            "4. ComplianceAgent로 법규 준수 검토 (실제 규제 DB 연동)\n"
            "5. VIOLATIONS_FOUND → regenerate()로 재생성 (최대 3회)\n"
            "6. COMPLIANCE_PASSED → 최종 결과 출력 / 미통과 → 수동 검토 안내"
        )
