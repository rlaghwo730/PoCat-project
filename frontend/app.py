"""
실손의료보험 약관 초안 작성 — LangManus 아키텍처 프론트엔드
백엔드: http://localhost:8000 (FastAPI + LangGraph)
"""
import asyncio
import json
import os
from datetime import date
from pathlib import Path
from typing import Optional
from uuid import uuid4

import aiohttp
import requests
import sseclient
from dotenv import load_dotenv

load_dotenv()

import streamlit as st

MAX_ITERATIONS = 3
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "z-ai/glm-4.5-air:free",
]

REGULATORY_RISK_MODEL = "solar-pro"
SAMPLE_CLARITY_DOCUMENTS = {
    "약관": (
        "제5조 보험금 지급\n"
        "회사가 필요하다고 인정하는 경우 보험금을 지급합니다.\n"
        "보험금 지급 사유에 해당하고 필요한 서류 제출 및 심사 절차를 거친 경우 보험금을 지급합니다.\n\n"
        "제6조 보장 한도 및 자기부담금\n"
        "보험금은 연간 보장 한도 및 자기 부담금 공제 후 지급합니다.\n"
        "약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않습니다."
    ),
    "상품설명서": (
        "보장 내용\n"
        "이 상품은 다양한 의료비를 폭넓게 보장받을 수 있는 상품입니다.\n"
        "주요 의료비에 대해 보장받을 수 있으나 일부 항목은 보장하지 않을 수 있습니다.\n\n"
        "보험료 및 자기부담금\n"
        "보험료 부담을 줄일 수 있으며 일정 비용만 부담하면 보장이 가능합니다.\n"
        "갱신 시 보험료가 달라질 수 있습니다.\n\n"
        "해지 및 환급금\n"
        "계약을 중도해지하는 경우 환급금은 달라질 수 있습니다.\n"
        "가입 전 주요 유의사항을 확인하시기 바랍니다."
    ),
    "사업방법서": (
        "계약 인수\n"
        "회사가 필요하다고 판단하는 경우 가입이 제한될 수 있습니다.\n"
        "심사 결과에 따라 조건부 인수가 적용될 수 있습니다.\n\n"
        "보험금 지급 심사\n"
        "추가 확인이 필요한 경우 보험금 지급이 제한될 수 있습니다.\n"
        "회사의 내부 기준에 따라 지급 여부를 결정할 수 있습니다.\n\n"
        "운영 기준\n"
        "예외적으로 달리 적용할 수 있으며 필요 시 기준을 변경할 수 있습니다."
    ),
}

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

    if "generated_result" not in st.session_state:
        st.session_state.generated_result = None

    if "regulatory_risk_result" not in st.session_state:
        st.session_state.regulatory_risk_result = None

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


def build_request(model: Optional[str] = None) -> dict:
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
        "model": model,
    }


def best_result(results: list[dict]) -> dict:
    """
    4개 모델 결과 중 가장 좋은 결과 1개 반환.
    1순위: status == COMPLIANCE_PASSED
    2순위: iteration 적은 것
    3순위: violations_for_ui 수 적은 것
    4순위: 첫 번째
    """
    passed = [r for r in results if r.get("status") == "COMPLIANCE_PASSED"]
    pool = passed if passed else results
    return min(pool, key=lambda r: (
        r.get("iteration", 99),
        len(r.get("violations_for_ui", [])),
    ))


async def _post_one(session: aiohttp.ClientSession, model_id: str) -> dict:
    payload = build_request(model=model_id)
    payload["session_id"] = str(uuid4())
    try:
        async with session.post(
            f"{BACKEND_URL}/generate",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=300),
        ) as r:
            data = await r.json()
            data["model_used"] = model_id
            return data
    except Exception as e:
        return {"status": "ORCHESTRATOR_ERROR", "error": str(e), "model_used": model_id}


async def _run_parallel() -> list[dict]:
    async with aiohttp.ClientSession() as session:
        return list(await asyncio.gather(*[_post_one(session, m) for m in MODELS]))


def extract_text_from_nested_result(obj, max_depth: int = 4) -> tuple[str, str]:
    best_text = ""
    best_path = ""

    def visit(value, path: str, depth: int) -> None:
        nonlocal best_text, best_path
        if depth > max_depth:
            return
        if isinstance(value, str):
            text = value.strip()
            if len(text) > len(best_text):
                best_text = text
                best_path = path
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                visit(nested, f"{path}.{key}" if path else str(key), depth + 1)
            return
        if isinstance(value, list):
            text_items = [item.strip() for item in value if isinstance(item, str) and item.strip()]
            if text_items:
                combined = "\n".join(text_items)
                if len(combined) > len(best_text):
                    best_text = combined
                    best_path = path
            for index, nested in enumerate(value[:10]):
                visit(nested, f"{path}[{index}]", depth + 1)

    visit(obj, "", 0)
    return best_text, best_path


def extract_generated_document_text(result: dict, document_type: str = "약관") -> tuple[str, str]:
    fields_by_document_type = {
        "약관": ["final_content", "final_document", "draft_content", "content", "generated_draft", "generated_text"],
        "상품설명서": ["product_description", "description", "product_description_content", "final_document"],
        "사업방법서": ["business_method", "business_method_content", "operation_method"],
    }
    candidate_fields = fields_by_document_type.get(document_type, []) + [
        "final_content",
        "final_document",
        "draft_content",
        "content",
        "generated_draft",
        "generated_text",
        "product_description",
        "business_method",
        "answer",
    ]
    for key in candidate_fields:
        value = result.get(key)
        if isinstance(value, str) and len(value.strip()) > 20:
            return value.strip(), key
        if isinstance(value, (dict, list)):
            nested_text, nested_path = extract_text_from_nested_result(value, max_depth=3)
            if len(nested_text.strip()) > 20:
                return nested_text.strip(), f"{key}.{nested_path}" if nested_path else key
    nested_text, nested_path = extract_text_from_nested_result(result)
    if len(nested_text.strip()) > 20:
        return nested_text.strip(), nested_path or "nested"
    return "", ""


def run_regulatory_risk_simulation(
    draft_content: str,
    document_type: str = "약관",
    selected_document_field: str = "",
) -> dict:
    response = requests.post(
        f"{BACKEND_URL}/regulatory-risk-simulation",
        json={
            "document_type": document_type,
            "draft_content": draft_content,
            "model": REGULATORY_RISK_MODEL,
            "max_findings": 5,
            "use_llm": True,
            "use_full_compliance_agent": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    result = response.json()
    if selected_document_field:
        result["_frontend_selected_document_field"] = selected_document_field
        result["_frontend_document_text_length"] = len(draft_content or "")
        result["_frontend_document_text_preview"] = (draft_content or "")[:500]
    return result


def render_regulatory_risk_result(result: dict) -> None:
    findings = result.get("regulatory_risk_simulation_findings", [])
    summary = result.get("regulatory_risk_simulation_summary", {})
    source_label = "Neon DB" if summary.get("gray_zone_type_source") == "db" else "기본 평가 기준"
    llm_label = "Upstage Solar Pro 사용" if summary.get("llm_used") else "기본 문장 기준 사용"
    document_type = summary.get("document_type") or "약관"
    matched_labels = sorted(
        {
            item.get("gray_zone_risk_label")
            for item in findings
            if item.get("gray_zone_risk_label")
        }
    )

    st.info(
        "본 기능은 소비자보호 관점에서 초안 문장의 명확성을 평가하고, 더 명확한 문장 제안을 함께 제공합니다. "
        "본 결과는 법적 적법성 판단이나 Compliance 검증 결과가 아닙니다."
    )
    st.markdown("### 평가 결과 요약")
    col_count, col_doc, col_source, col_types, col_llm = st.columns(5)
    col_count.metric("평가 후보", f"{len(findings)}건")
    col_doc.metric("문서 유형", document_type)
    col_source.metric("평가 기준", source_label)
    col_types.metric("평가 유형", f"{summary.get('gray_zone_type_count', 0)}개")
    col_llm.metric("LLM 보강", "사용" if summary.get("llm_used") else "미사용")
    st.caption(
        f"{llm_label} · 제목형 라인 제외 {summary.get('excluded_heading_count', 0)}건 · "
        "원문 제목이나 조항명만으로는 평가 결과를 만들지 않습니다."
    )
    if matched_labels:
        st.markdown(f"**적용된 평가 항목:** {', '.join(matched_labels)}")

    if not findings:
        st.warning(
            "현재 문서에서는 DB 평가 기준과 직접 매칭되는 불명확 표현 후보가 발견되지 않았습니다.\n\n"
            "이는 문서가 법적으로 적합하다는 판단이 아니라, 현재 등록된 평가 유형과 직접 매칭되는 표현이 없다는 의미입니다."
        )
        st.info(
            "시연용으로 문서유형별 예시 문서를 실행하면 평가 결과가 어떤 방식으로 표시되는지 확인할 수 있습니다."
        )
        sample_text = SAMPLE_CLARITY_DOCUMENTS.get(document_type)
        if sample_text and st.button(
            f"현재 문서유형 예시로 평가 실행 ({document_type})",
            key=f"run_zero_sample_{document_type}",
            use_container_width=True,
        ):
            st.session_state.regulatory_risk_result = run_regulatory_risk_simulation(
                sample_text,
                document_type=document_type,
                selected_document_field=f"sample:{document_type}",
            )
            st.rerun()
        with st.expander("개발자용 미매칭 후보 보기", expanded=False):
            st.write("body_candidate_count", summary.get("body_candidate_count", 0))
            st.write("sample_unmatched_body_candidates", summary.get("sample_unmatched_body_candidates", []))

    for index, item in enumerate(findings, 1):
        label = item.get("gray_zone_risk_label") or item.get("gray_zone_risk_type", "")
        unclear_points = item.get("unclear_points_in_source") or item.get("matched_patterns", [])
        if isinstance(unclear_points, list):
            unclear_points_text = ", ".join(str(point) for point in unclear_points if str(point).strip())
        else:
            unclear_points_text = str(unclear_points or "")
        with st.expander(f"평가 결과 {index}. {label}", expanded=index == 1):
            st.markdown(f"**원문 문장**\n\n{item.get('source_text', '')}")
            st.markdown(f"**원문 내 불명확 가능 지점**\n\n{unclear_points_text}")
            st.write("평가 유형", item.get("gray_zone_risk_type", ""))
            st.markdown(
                "**불명확하게 해석될 수 있는 표현 예시**\n\n"
                f"{item.get('ambiguous_expression_example', '')}"
            )
            st.markdown(f"**불명확성 사유**\n\n{item.get('why_ambiguous', '')}")
            st.markdown(f"**소비자 오해 가능성**\n\n{item.get('consumer_confusion_point', '')}")
            st.markdown(f"**명확화 기준**\n\n{item.get('safe_rewrite_guideline', '')}")
            st.markdown(f"**명확한 문장 제안**\n\n{item.get('strengthened_safe_sentence', '')}")
            if item.get("nearest_heading"):
                st.caption(f"가까운 제목: {item.get('nearest_heading')}")
            with st.expander("분류 상세 보기", expanded=False):
                st.write("matched_patterns", item.get("matched_patterns", []))
                st.write("final_classification", item.get("final_classification"))
                st.write("gray_zone_classification", item.get("gray_zone_classification"))
                st.write("classification_basis", item.get("classification_basis"))
                st.write("LLM 보강 상태", item.get("llm_judgement", {}))

    with st.expander("문장 명확성 평가 보고서 미리보기"):
        st.markdown(result.get("regulatory_risk_simulation_report", ""))
    with st.expander("명확한 문장 제안 보고서 미리보기"):
        st.markdown(result.get("safe_alternative_report", ""))
    with st.expander("개발자용 원본 응답 보기", expanded=False):
        st.json(result)


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
run_all_btn = False
run_sample_regulatory_btn = False
sample_regulatory_type = "약관"

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
                "⚡ 약관 초안 생성 (Upstage)",
                type="primary",
                use_container_width=True,
                disabled=not basic_items,
                help="Upstage Solar 단일 모델로 빠르게 생성"
            )
            run_all_btn = st.button(
                "🔄 4개 모델 병렬 실행 (OpenRouter)",
                use_container_width=True,
                disabled=not basic_items,
                help="OpenRouter 무료 모델 4개 병렬 실행 (일일 한도 50회)"
            )
            sample_regulatory_type = st.selectbox(
                "예시 평가 문서 유형",
                ["약관", "상품설명서", "사업방법서"],
                key="sample_regulatory_document_type",
            )
            st.caption(
                f"현재 선택한 문서유형: {sample_regulatory_type} · "
                f"{sample_regulatory_type} 예시 문서를 기준으로 문장 명확성 평가를 실행합니다."
            )
            run_sample_regulatory_btn = st.button(
                "예시 문서로 평가 실행",
                use_container_width=True,
                help="생성 흐름을 기다리지 않고 예시 문서로 문장 명확성 평가를 실행합니다.",
            )
            if not basic_items:
                st.warning("기본 보장종목을 하나 이상 선택하세요.")


# ── Result panel ──────────────────────────────────────────────────────────────
with col_result:
    st.subheader("생성된 약관 초안")

    if run_sample_regulatory_btn:
        try:
            with st.spinner("예시 문서로 문장 명확성 평가 실행 중..."):
                st.session_state.regulatory_risk_result = run_regulatory_risk_simulation(
                    SAMPLE_CLARITY_DOCUMENTS[sample_regulatory_type],
                    document_type=sample_regulatory_type,
                    selected_document_field=f"sample:{sample_regulatory_type}",
                )
            render_regulatory_risk_result(st.session_state.regulatory_risk_result)
        except Exception as e:
            st.error(f"문장 명확성 평가 오류: {e}")
            st.exception(e)

    elif generate_btn or run_all_btn:
        fetal_enrollment = st.session_state.get("_saved_fetal_enrollment", "가능")
        applicant_type = st.session_state.get("applicant_type", "본인")
        if fetal_enrollment == "불가" and applicant_type == "태아":
            st.error("⚠️ 태아 가입이 불가능합니다.")
        else:
            try:
                if generate_btn:
                    with st.status("약관 초안 생성 중...", expanded=True) as status_box:
                        # SSE 스트리밍으로 노드별 진행상황 실시간 표시
                        request = build_request(model=None)

                        response = requests.post(
                            f"{BACKEND_URL}/generate/stream",
                            json=request,
                            stream=True,
                            timeout=300,
                        )
                        response.raise_for_status()

                        client = sseclient.SSEClient(response)
                        result = None

                        for event in client.events():
                            if event.data == "[DONE]":
                                break

                            data = json.loads(event.data)

                            if data.get("type") == "progress":
                                node = data.get("node", "")
                                iteration = data.get("iteration", 0)

                                node_emoji = {
                                    "coordinator": "🔍",
                                    "planner": "📋",
                                    "supervisor": "🎯",
                                    "generation": "✍️",
                                    "compliance": "⚖️",
                                    "edit": "✏️",
                                }.get(node, "⚙️")

                                if node:
                                    st.write(f"{node_emoji} **{node}** 완료 (iteration {iteration})")

                            elif data.get("type") == "result":
                                result = data

                            elif data.get("type") == "error":
                                raise Exception(data.get("message", "스트리밍 오류"))

                        if result is None:
                            raise Exception("결과를 받지 못했습니다.")

                        model_used = result.get("model_used", "Upstage Solar")
                        st.write(f"✅ 생성 완료: {model_used}")
                else:
                    with st.status("약관 초안 생성 중...", expanded=True) as status_box:
                        st.write("4개 모델 병렬 실행 중...")
                        all_results = asyncio.run(_run_parallel())
                        result = best_result(all_results)
                        model_used = result.get("model_used", "unknown")
                        st.write(f"✅ 최적 모델 선택: {model_used}")

                st.session_state.generated_result = result
                st.session_state.regulatory_risk_result = None

                final_status = result["status"]
                if final_status == "COMPLIANCE_PASSED":
                    status_box.update(
                        label=f"약관 초안 생성 완료 — {result['iteration']}회 검토 통과 ({model_used})",
                        state="complete",
                    )
                elif final_status == "MANUAL_REVIEW_REQUIRED":
                    status_box.update(
                        label=f"최대 {MAX_ITERATIONS}회 도달 — 수동 검토 필요",
                        state="error",
                    )
                else:
                    status_box.update(label="오류 발생", state="error")

                session_id = st.session_state.session_id
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

                st.divider()
                st.subheader("문장 명확성 평가")
                st.caption(
                    "생성된 문서를 입력으로 문서유형별 문장 명확성 평가 기준을 적용합니다. "
                    "본 결과는 법적 적법성 판단이나 Compliance 검증 결과가 아닙니다."
                )
                regulatory_document_type = st.selectbox(
                    "평가 문서 유형",
                    ["약관", "상품설명서", "사업방법서"],
                    key="regulatory_document_type_live",
                )
                if st.button("문장 명확성 평가 실행", use_container_width=True):
                    with st.spinner("문장 명확성 평가 실행 중..."):
                        document_text, selected_field = extract_generated_document_text(result, regulatory_document_type)
                        st.session_state.regulatory_risk_result = run_regulatory_risk_simulation(
                            document_text,
                            document_type=regulatory_document_type,
                            selected_document_field=selected_field,
                        )
                if st.session_state.get("regulatory_risk_result"):
                    render_regulatory_risk_result(st.session_state.regulatory_risk_result)

            except Exception as e:
                st.error(f"오류 발생: {e}")
                st.exception(e)

    elif st.session_state.get("generated_result"):
        result = st.session_state.generated_result
        st.caption("이전 생성 결과를 표시합니다.")
        tab_clause, tab_desc, tab_biz = st.tabs(["약관", "상품설명서", "사업방법서"])

        with tab_clause:
            highlighted = apply_violation_highlights(
                result.get("content", ""),
                result.get("violations_for_ui", []),
            )
            st.markdown(highlighted, unsafe_allow_html=True)

        with tab_desc:
            st.markdown(result.get("product_description", ""))

        with tab_biz:
            st.markdown(result.get("business_method", ""))

        st.divider()
        st.subheader("문장 명확성 평가")
        st.caption(
            "생성된 문서를 입력으로 문서유형별 문장 명확성 평가 기준을 적용합니다. "
            "본 결과는 법적 적법성 판단이나 Compliance 검증 결과가 아닙니다."
        )
        regulatory_document_type = st.selectbox(
            "평가 문서 유형",
            ["약관", "상품설명서", "사업방법서"],
            key="regulatory_document_type_saved",
        )
        if st.button("문장 명확성 평가 실행", use_container_width=True):
            with st.spinner("문장 명확성 평가 실행 중..."):
                document_text, selected_field = extract_generated_document_text(result, regulatory_document_type)
                st.session_state.regulatory_risk_result = run_regulatory_risk_simulation(
                    document_text,
                    document_type=regulatory_document_type,
                    selected_document_field=selected_field,
                )
        if st.session_state.get("regulatory_risk_result"):
            render_regulatory_risk_result(st.session_state.regulatory_risk_result)

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
