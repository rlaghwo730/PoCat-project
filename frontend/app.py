"""
실손의료보험 약관 초안 작성 에이전트 — Streamlit UI
백엔드: http://localhost:8000 (FastAPI + LangGraph)

구조:
  STEP 1. 기본 설정     (보험사 선택, 상품명)
  STEP 2. 상품 설계 조건 (보험기간, 납입, 갱신, 가입나이)
  STEP 3. 보장 조건     (보장 종목, 비급여, 한도, 자기부담)
  STEP 4. 확인 및 생성  (입력값 요약 + 생성 버튼)
  결과   : 약관 / 상품설명서 / 사업방법서 3탭 항상 표시
"""

import asyncio
import json
import os
from uuid import uuid4

import aiohttp
import requests
import sseclient
from dotenv import load_dotenv

load_dotenv()

import streamlit as st

# ────────────────────────────────────────────────────────────────────────────
# 상수
# ────────────────────────────────────────────────────────────────────────────

MAX_ITERATIONS = 3
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "z-ai/glm-4.5-air:free",
]

STEPS = [
    "기본 설정",
    "상품 설계 조건",
    "보장 조건",
    "확인 및 생성",
]
TOTAL_STEPS = len(STEPS)

# ────────────────────────────────────────────────────────────────────────────
# 3사 기본값 (JSON 데이터 기반)
# ────────────────────────────────────────────────────────────────────────────

COMPANY_DEFAULTS = {
    "삼성화재": {
        "product_name":             "무배당 삼성화재 다이렉트 실손의료비보험(2605.1)",
        "product_version":          "2605.1",
        "join_age_min":             "0세",
        "join_age_max":             "65세",
        "fetal_enrollment":         "가능",
        "max_coverage_age":         100,
        "policy_period":            "1년 만기",
        "premium_payment_period":   "전기납",
        "premium_payment_cycle":    "월납",
        "renewal_type":             "갱신형",
        "renewal_period":           "1년",
        "max_renewal_count":        4,
        "reinstatement_cycle":      "5년",
        "policy_loan":              "가능",
        "coverage_limit_basic":     "5천만원",
        "coverage_limit_noncovered":"5천만원",
        "coverage_limit_dosu":      "350만원",
        "coverage_limit_injection": "250만원",
        "coverage_limit_mri":       "300만원",
        "outpatient_limit":         "20만원",
        "deductible_hospital":      "1만원 또는 보장대상의료비의 20% 중 큰 금액",
        "deductible_major":         "2만원 또는 보장대상의료비의 20% 중 큰 금액",
    },
    "현대해상": {
        "product_name":             "무배당 현대해상다이렉트실손의료비보장보험(갱신형)(Hi2605)",
        "product_version":          "Hi2605",
        "join_age_min":             "태아",
        "join_age_max":             "60세",
        "fetal_enrollment":         "가능",
        "max_coverage_age":         100,
        "policy_period":            "1년 만기",
        "premium_payment_period":   "전기납",
        "premium_payment_cycle":    "월납",
        "renewal_type":             "갱신형",
        "renewal_period":           "1년",
        "max_renewal_count":        4,
        "reinstatement_cycle":      "5년",
        "policy_loan":              "가능",
        "coverage_limit_basic":     "5천만원",
        "coverage_limit_noncovered":"5천만원",
        "coverage_limit_dosu":      "350만원",
        "coverage_limit_injection": "250만원",
        "coverage_limit_mri":       "300만원",
        "outpatient_limit":         "20만원",
        "deductible_hospital":      "1만원 또는 보장대상의료비의 20% 중 큰 금액",
        "deductible_major":         "2만원 또는 보장대상의료비의 20% 중 큰 금액",
    },
    "DB손해보험": {
        "product_name":             "무배당프로미라이프실손의료비보험",
        "product_version":          "2605",
        "join_age_min":             "5세",
        "join_age_max":             "99세",
        "fetal_enrollment":         "가능",
        "max_coverage_age":         100,
        "policy_period":            "1년 만기",
        "premium_payment_period":   "전기납",
        "premium_payment_cycle":    "월납",
        "renewal_type":             "갱신형",
        "renewal_period":           "1년",
        "max_renewal_count":        4,
        "reinstatement_cycle":      "5년",
        "policy_loan":              "가능",
        "coverage_limit_basic":     "5천만원",
        "coverage_limit_noncovered":"5천만원",
        "coverage_limit_dosu":      "350만원",
        "coverage_limit_injection": "250만원",
        "coverage_limit_mri":       "200만원",
        "outpatient_limit":         "20만원",
        "deductible_hospital":      "1만원 또는 보장대상의료비의 20% 중 큰 금액",
        "deductible_major":         "2만원 또는 보장대상의료비의 20% 중 큰 금액",
    },
}

COVERAGE_LIMIT_OPTIONS  = ["3천만원", "5천만원"]
DOSU_LIMIT_OPTIONS      = ["250만원", "350만원", "500만원"]
INJECTION_LIMIT_OPTIONS = ["150만원", "250만원", "350만원"]
MRI_LIMIT_OPTIONS       = ["150만원", "200만원", "300만원"]
OUTPATIENT_LIMIT_OPTIONS= ["10만원",  "20만원",  "30만원"]

DEDUCTIBLE_OPTIONS = [
    "1만원 또는 보장대상의료비의 20% 중 큰 금액",
    "2만원 또는 보장대상의료비의 20% 중 큰 금액",
    "15% 정률제",
    "20% 정률제",
]

NODE_EMOJI = {
    "coordinator": "🔍",
    "planner":     "📋",
    "supervisor":  "🎯",
    "generation":  "✍️",
    "compliance":  "⚖️",
    "edit":        "✏️",
}

# ────────────────────────────────────────────────────────────────────────────
# 페이지 설정
# ────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="실손의료보험 초안 작성 에이전트",
    page_icon="📄",
    layout="wide",
)

# ────────────────────────────────────────────────────────────────────────────
# CSS
# ────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.step-bar {
    display: flex;
    align-items: center;
    gap: 0;
    margin-bottom: 1.4rem;
}
.step-item {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.82rem;
    font-weight: 600;
    color: #94a3b8;
    white-space: nowrap;
}
.step-item.active { color: #2563eb; }
.step-item.done   { color: #16a34a; }
.step-circle {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    font-weight: 700;
    background: #e2e8f0;
    color: #64748b;
    flex-shrink: 0;
}
.step-item.active .step-circle { background: #2563eb; color: white; }
.step-item.done   .step-circle { background: #16a34a; color: white; }
.step-connector {
    flex: 1;
    height: 2px;
    background: #e2e8f0;
    margin: 0 6px;
    min-width: 16px;
}
.step-connector.done { background: #16a34a; }
.summary-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.7rem;
}
.summary-card h4 {
    margin: 0 0 0.6rem 0;
    font-size: 0.85rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.summary-row {
    display: flex;
    justify-content: space-between;
    font-size: 0.88rem;
    padding: 0.18rem 0;
    border-bottom: 1px solid #f1f5f9;
}
.summary-row:last-child { border-bottom: none; }
.summary-key { color: #64748b; }
.summary-val { font-weight: 600; color: #1e293b; }
</style>
""", unsafe_allow_html=True)


# ────────────────────────────────────────────────────────────────────────────
# 세션 초기화
# ────────────────────────────────────────────────────────────────────────────

def _init_session():
    if "current_step" not in st.session_state:
        st.session_state.current_step = 0
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid4())

    defaults = COMPANY_DEFAULTS["삼성화재"]
    init_keys = {
        "insurance_company":  "삼성화재",
        "insurance_type":     "기본형 실손의료비보험",
        "policy_period":      defaults["policy_period"],
        "premium_payment_period": defaults["premium_payment_period"],
        "premium_payment_cycle":  defaults["premium_payment_cycle"],
        "renewal_type":       defaults["renewal_type"],
        "renewal_period":     defaults["renewal_period"],
        "max_renewal_count":  defaults["max_renewal_count"],
        "reinstatement_cycle":defaults["reinstatement_cycle"],
        "join_age_min":       defaults["join_age_min"],
        "join_age_max":       defaults["join_age_max"],
        "max_coverage_age":   defaults["max_coverage_age"],
        "fetal_enrollment":   defaults["fetal_enrollment"],
        "policy_loan":        defaults["policy_loan"],
        "product_name":       defaults["product_name"],
        "product_version":    defaults["product_version"],
        "basic_coverage_items":         ["상해급여", "질병급여"],
        "noncovered_enabled":           False,
        "three_major_enabled":          False,
        "noncovered_rider_items":       [],
        "three_major_noncovered_items": [],
        "coverage_limit_basic":         defaults["coverage_limit_basic"],
        "coverage_limit_noncovered":    defaults["coverage_limit_noncovered"],
        "coverage_limit_dosu":          defaults["coverage_limit_dosu"],
        "coverage_limit_injection":     defaults["coverage_limit_injection"],
        "coverage_limit_mri":           defaults["coverage_limit_mri"],
        "outpatient_limit":             defaults["outpatient_limit"],
        "deductible_hospital":          defaults["deductible_hospital"],
        "deductible_major":             defaults["deductible_major"],
    }
    for k, v in init_keys.items():
        if k not in st.session_state:
            st.session_state[k] = v


def apply_company_defaults(company: str):
    d = COMPANY_DEFAULTS.get(company, COMPANY_DEFAULTS["삼성화재"])
    for f in d:
        st.session_state[f] = d[f]


_init_session()


# ────────────────────────────────────────────────────────────────────────────
# 네비게이션
# ────────────────────────────────────────────────────────────────────────────

def go_prev(): st.session_state.current_step -= 1
def go_next(): st.session_state.current_step += 1


# ────────────────────────────────────────────────────────────────────────────
# 스텝 인디케이터
# ────────────────────────────────────────────────────────────────────────────

def render_step_bar(current: int):
    html = '<div class="step-bar">'
    for i, label in enumerate(STEPS):
        if i < current:
            cls, circle = "done", "✓"
        elif i == current:
            cls, circle = "active", str(i + 1)
        else:
            cls, circle = "", str(i + 1)
        html += f'<div class="step-item {cls}"><div class="step-circle">{circle}</div><span>{label}</span></div>'
        if i < len(STEPS) - 1:
            conn_cls = "done" if i < current else ""
            html += f'<div class="step-connector {conn_cls}"></div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


# ────────────────────────────────────────────────────────────────────────────
# 스텝 렌더링
# ────────────────────────────────────────────────────────────────────────────

def render_step1():
    """STEP 1: 기본 설정"""
    st.subheader("🏢 기본 설정")
    st.caption("보험사를 선택하면 해당 보험사의 실제 상품 기본값이 자동으로 채워집니다.")

    st.selectbox(
        "보험사",
        list(COMPANY_DEFAULTS.keys()),
        key="insurance_company",
        on_change=lambda: apply_company_defaults(st.session_state.insurance_company),
    )

    st.caption("ℹ️ 약관·상품설명서·사업방법서 3개 문서를 한 번에 생성합니다.")

    st.divider()
    st.text_input("상품명",          key="product_name",    help="보험사 변경 시 자동 업데이트")
    st.text_input("버전 / 상품코드", key="product_version")
    st.selectbox("보험 유형", ["기본형 실손의료비보험", "특약 포함 실손의료비보험"], key="insurance_type")

    return True  # STEP 1은 항상 다음으로 진행 가능


def render_step2():
    """STEP 2: 상품 설계 조건"""
    st.subheader("⚙️ 상품 설계 조건")
    st.caption("사업방법서 기준 항목입니다.")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**📅 보험기간 / 납입**")
        st.text_input("보험기간", value="1년 만기", disabled=True, key="_fp_period")
        st.caption("✔ 실손의료보험 1년 만기 고정 (법령)")

        st.text_input("보험료 납입기간", value="전기납", disabled=True, key="_fp_pay")
        st.caption("✔ 전기납 고정")

        st.selectbox("보험료 납입주기", ["월납", "3개월납", "6개월납", "연납"], key="premium_payment_cycle")

        st.divider()
        st.markdown("**🔁 갱신**")
        st.text_input("갱신 유형", value="갱신형", disabled=True, key="_fp_renewal")
        st.caption("✔ 갱신형 고정 (현행 제도)")

        st.text_input("갱신 주기", value="1년", disabled=True, key="_fp_rcycle")
        st.caption("✔ 1년 고정")

        st.number_input("최대 갱신 횟수", min_value=1, max_value=10, step=1, key="max_renewal_count")

        st.text_input("재가입 주기", value="5년", disabled=True, key="_fp_reinstate")
        st.caption("✔ 5년 고정")

    with col_b:
        st.markdown("**👤 가입 조건**")
        company = st.session_state.get("insurance_company", "삼성화재")
        age_hints = {"삼성화재": "0세 / 65세", "현대해상": "태아 / 60세", "DB손해보험": "5세 / 99세"}
        st.caption(f"ℹ️ {company} 기본: {age_hints.get(company, '')}")

        st.text_input("가입 최소 나이", key="join_age_min")
        st.text_input("가입 최대 나이", key="join_age_max")
        st.number_input("최대 보장 나이 (세)", min_value=70, max_value=120, step=1, key="max_coverage_age")

        st.divider()
        st.markdown("**🍼 특수 조건**")
        st.radio("태아 가입 가능 여부", ["가능", "불가"], horizontal=True, key="fetal_enrollment")
        st.radio("보험계약대출 가능 여부", ["가능", "불가"], horizontal=True, key="policy_loan")


def render_step3():
    """STEP 3: 보장 조건"""
    st.subheader("🏥 보장 조건")

    # 기본 보장 종목
    st.markdown("**기본 보장 종목** (약관 제1조 기준, 1개 이상 필수)")
    basic_items = st.session_state.get("basic_coverage_items", [])
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        injury  = st.checkbox("상해급여 실손의료비", value="상해급여" in basic_items, key="_basic_injury",
                              help="상해로 인한 입원·통원 급여의료비 보상")
    with col_b2:
        disease = st.checkbox("질병급여 실손의료비", value="질병급여" in basic_items, key="_basic_disease",
                              help="질병으로 인한 입원·통원 급여의료비 보상")

    new_basic = (["상해급여"] if injury else []) + (["질병급여"] if disease else [])
    st.session_state.basic_coverage_items = new_basic
    if not new_basic:
        st.error("⚠️ 기본 보장 종목을 최소 1개 이상 선택해야 합니다.")

    st.divider()

    # 비급여 특약
    st.markdown("**비급여 특약** (선택사항)")
    noncov = st.checkbox("비급여 실손의료비 특약 포함", key="noncovered_enabled",
                         help="중증·비중증 비급여 의료비 보상 특약")
    if noncov:
        st.session_state.noncovered_rider_items = [
            "[갱신형]중증 비급여 실손의료비 특별약관(상해)",
            "[갱신형]중증 비급여 실손의료비 특별약관(질병)",
            "[갱신형]비중증 비급여 실손의료비 특별약관(상해)",
            "[갱신형]비중증 비급여 실손의료비 특별약관(질병)",
        ]
        three_major = st.checkbox("3대 비급여 세부항목 포함 (도수치료·주사료·MRI)", key="three_major_enabled")
        if three_major:
            st.session_state.three_major_noncovered_items = [
                "[갱신형]중증 비급여 실손의료비 특별약관(3대비급여)",
                "[갱신형]비중증 비급여 자기공명영상진단보장 특별약관",
            ]
        else:
            st.session_state.three_major_noncovered_items = []
    else:
        st.session_state.noncovered_rider_items       = []
        st.session_state.three_major_noncovered_items = []
        st.session_state.three_major_enabled          = False

    st.divider()

    # 보험가입금액 한도
    st.markdown("**보험가입금액 한도**")
    col_l1, col_l2 = st.columns(2)
    with col_l1:
        _sel(st, "급여 연간 한도",  COVERAGE_LIMIT_OPTIONS,   "coverage_limit_basic")
        _sel(st, "통원 1회 한도",   OUTPATIENT_LIMIT_OPTIONS, "outpatient_limit",
             help="약관 제6조 ⑤항")
    with col_l2:
        _sel(st, "비급여 연간 한도", COVERAGE_LIMIT_OPTIONS, "coverage_limit_noncovered",
             disabled=not noncov,
             help="비급여 특약 선택 시 활성화" if not noncov else "")
        if not noncov:
            st.caption("※ 비급여 특약 선택 시 활성화됩니다.")

    if noncov and st.session_state.get("three_major_enabled", False):
        st.markdown("**3대 비급여 세부 한도**")
        col_3a, col_3b, col_3c = st.columns(3)
        with col_3a: _sel(st, "도수치료 한도", DOSU_LIMIT_OPTIONS,      "coverage_limit_dosu")
        with col_3b: _sel(st, "주사료 한도",   INJECTION_LIMIT_OPTIONS, "coverage_limit_injection")
        with col_3c:
            company = st.session_state.get("insurance_company", "삼성화재")
            _sel(st, "MRI/MRA 한도", MRI_LIMIT_OPTIONS, "coverage_limit_mri",
                 help="DB손해보험 200만원 / 삼성·현대 300만원")

    st.divider()

    # 자기부담금
    st.markdown("**자기부담금 (공제금액) 규칙** — 약관 제3조 〈표1〉")
    col_d1, col_d2 = st.columns(2)
    with col_d1: _sel(st, "일반 의료기관 통원", DEDUCTIBLE_OPTIONS, "deductible_hospital")
    with col_d2: _sel(st, "상급종합병원 통원",  DEDUCTIBLE_OPTIONS, "deductible_major",
                      index_default=1)

    return bool(new_basic)


def _sel(parent, label, options, key, disabled=False, help="", index_default=0):
    """selectbox 헬퍼 — 현재 session_state 값 기준으로 index 자동 설정"""
    cur = st.session_state.get(key)
    try:
        idx = options.index(cur) if cur in options else index_default
    except ValueError:
        idx = index_default
    parent.selectbox(label, options, index=idx, key=key, disabled=disabled, help=help)


def render_step4():
    """STEP 4: 확인 및 생성"""
    st.subheader("✅ 입력 확인")
    st.caption("아래 내용으로 초안을 생성합니다. 수정이 필요하면 이전 단계로 돌아가세요.")

    s = st.session_state

    def card(title, rows):
        html = f'<div class="summary-card"><h4>{title}</h4>'
        for k, v in rows:
            html += (f'<div class="summary-row">'
                     f'<span class="summary-key">{k}</span>'
                     f'<span class="summary-val">{v}</span></div>')
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)

    card("기본 설정", [
        ("보험사",    s.get("insurance_company", "-")),
        ("상품명",    s.get("product_name", "-")),
        ("버전/코드", s.get("product_version", "-")),
        ("보험 유형", s.get("insurance_type", "-")),
    ])

    card("상품 설계 조건", [
        ("보험기간",       s.get("policy_period", "-")),
        ("납입기간/주기",  f"{s.get('premium_payment_period','-')} / {s.get('premium_payment_cycle','-')}"),
        ("갱신",           f"{s.get('renewal_type','-')} ({s.get('renewal_period','-')}, 최대 {s.get('max_renewal_count','-')}회)"),
        ("재가입 주기",    s.get("reinstatement_cycle", "-")),
        ("가입나이",       f"{s.get('join_age_min','-')} ~ {s.get('join_age_max','-')}"),
        ("최대 보장나이",  f"{s.get('max_coverage_age','-')}세"),
        ("태아 가입",      s.get("fetal_enrollment", "-")),
        ("보험계약대출",   s.get("policy_loan", "-")),
    ])

    basic        = s.get("basic_coverage_items", [])
    noncov_items = s.get("noncovered_rider_items", [])
    three_items  = s.get("three_major_noncovered_items", [])
    cov_rows = [
        ("기본 보장 종목",  ", ".join(basic) if basic else "미선택"),
        ("비급여 특약",     "포함" if noncov_items else "미포함"),
        ("3대 비급여 특약", "포함" if three_items  else "미포함"),
        ("급여 연간 한도",  s.get("coverage_limit_basic",  "-")),
        ("통원 1회 한도",   s.get("outpatient_limit",       "-")),
    ]
    if noncov_items:
        cov_rows.append(("비급여 연간 한도", s.get("coverage_limit_noncovered", "-")))
    if three_items:
        cov_rows += [
            ("도수치료 한도", s.get("coverage_limit_dosu",      "-")),
            ("주사료 한도",   s.get("coverage_limit_injection",  "-")),
            ("MRI/MRA 한도",  s.get("coverage_limit_mri",        "-")),
        ]
    cov_rows += [
        ("일반 통원 공제", s.get("deductible_hospital", "-")),
        ("종합병원 공제",  s.get("deductible_major",    "-")),
    ]
    card("보장 조건", cov_rows)


# ────────────────────────────────────────────────────────────────────────────
# 백엔드 요청 빌더
# ────────────────────────────────────────────────────────────────────────────

def build_request(model=None) -> dict:
    s = st.session_state
    return {
        "document_request": {
            "document_type":     "전체",   # 약관·상품설명서·사업방법서 일괄 생성
            "insurance_company": s.get("insurance_company", "삼성화재"),
            "insurance_type":    s.get("insurance_type", "기본형 실손의료비보험"),
            "product_name":      s.get("product_name", ""),
            "product_version":   s.get("product_version", ""),
            "dividend_type":     "무배당",
        },
        "product_design_conditions": {
            "policy_period":          s.get("policy_period", "1년 만기"),
            "premium_payment_period": s.get("premium_payment_period", "전기납"),
            "premium_payment_cycle":  s.get("premium_payment_cycle", "월납"),
            "renewal_type":           s.get("renewal_type", "갱신형"),
            "renewal_period":         s.get("renewal_period", "1년"),
            "max_renewal_count":      s.get("max_renewal_count", 4),
            "reinstatement_cycle":    s.get("reinstatement_cycle", "5년"),
            "max_coverage_age":       s.get("max_coverage_age", 100),
            "join_age_min":           s.get("join_age_min", "0세"),
            "join_age_max":           s.get("join_age_max", "65세"),
            "fetal_enrollment":       s.get("fetal_enrollment", "가능"),
            "policy_loan":            s.get("policy_loan", "가능"),
        },
        "coverage_conditions": {
            "basic_coverage_items":         s.get("basic_coverage_items", []),
            "noncovered_rider_items":       s.get("noncovered_rider_items", []),
            "three_major_noncovered_items": s.get("three_major_noncovered_items", []),
            "coverage_limit": {
                "급여":     s.get("coverage_limit_basic",       "5천만원"),
                "비급여":   s.get("coverage_limit_noncovered",  "5천만원"),
                "도수치료": s.get("coverage_limit_dosu",        "350만원"),
                "주사료":   s.get("coverage_limit_injection",   "250만원"),
                "MRI":      s.get("coverage_limit_mri",         "300만원"),
            },
            "outpatient_limit": s.get("outpatient_limit", "20만원"),
            "deductible_rule": {
                "일반_의료기관": s.get("deductible_hospital", ""),
                "상급종합병원":  s.get("deductible_major",    ""),
            },
        },
        "session_id": s.session_id,
        "model": model,
    }


# ────────────────────────────────────────────────────────────────────────────
# 병렬 실행
# ────────────────────────────────────────────────────────────────────────────

def best_result(results: list) -> dict:
    passed = [r for r in results if r.get("status") == "COMPLIANCE_PASSED"]
    pool = passed if passed else results
    return min(pool, key=lambda r: (r.get("iteration", 99), len(r.get("violations_for_ui", []))))


async def _post_one(session: aiohttp.ClientSession, model_id: str) -> dict:
    payload = build_request(model=model_id)
    payload["session_id"] = str(uuid4())
    try:
        async with session.post(
            f"{BACKEND_URL}/generate", json=payload,
            timeout=aiohttp.ClientTimeout(total=300),
        ) as r:
            data = await r.json()
            data["model_used"] = model_id
            return data
    except Exception as e:
        return {"status": "ORCHESTRATOR_ERROR", "error": str(e), "model_used": model_id}


async def _run_parallel() -> list:
    async with aiohttp.ClientSession() as session:
        return list(await asyncio.gather(*[_post_one(session, m) for m in MODELS]))


# ────────────────────────────────────────────────────────────────────────────
# 위반 하이라이트
# ────────────────────────────────────────────────────────────────────────────

def apply_violation_highlights(content: str, violations: list) -> str:
    for v in violations:
        original = v.get("original_text", "")
        if not original or original not in content:
            continue
        annotation = f"⚠️ [{v['type']}] {v['legal_basis']}: {v['fix']}"
        content = content.replace(
            original,
            f'<span style="color:red;">{original}</span>'
            f'<br><span style="color:red;font-size:12px;">{annotation}</span>',
        )
    return content


# ────────────────────────────────────────────────────────────────────────────
# 결과 패널
# ────────────────────────────────────────────────────────────────────────────

def render_result_panel(result: dict, model_label: str):
    final_status = result.get("status", "")
    if final_status == "COMPLIANCE_PASSED":
        st.success(
            f"✅ 법규 검토 통과 — {result.get('iteration', '?')}회 완료 "
            f"({model_label} / 세션: {st.session_state.session_id[:8]}…)"
        )
    elif final_status == "MANUAL_REVIEW_REQUIRED":
        st.error(f"⚠️ 최대 {MAX_ITERATIONS}회 재생성 후에도 법규 준수 미달. 수동 검토 필요.")
        if result.get("suggestions"):
            with st.expander("📋 수동 검토 필요 항목"):
                for s in result["suggestions"]:
                    manual = " 🔴 반복 위반" if s.get("requires_manual_review") else ""
                    st.markdown(
                        f"- **[{s['severity']}] {s['type']}**{manual}\n\n"
                        f"  {s['action']}\n\n  > `{s['target_text']}`"
                    )
    elif final_status == "ORCHESTRATOR_ERROR":
        st.error(f"시스템 오류: {result.get('error', '알 수 없는 오류')}")

    if result.get("db_warning"):      st.warning(f"⚠️ {result['db_warning']}")
    if result.get("improvement_note"):st.info(f"📊 {result['improvement_note']}")

    # 항상 3탭 고정
    tab_clause, tab_desc, tab_biz = st.tabs(["📜 약관", "📋 상품설명서", "📁 사업방법서"])

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


# ────────────────────────────────────────────────────────────────────────────
# 메인 레이아웃
# ────────────────────────────────────────────────────────────────────────────

st.title("📄 실손의료보험 초안 작성 에이전트")
st.caption(
    "삼성화재·현대해상·DB손해보험 실제 데이터를 기반으로 "
    "약관·상품설명서·사업방법서 초안을 생성하고 법령 검증을 수행합니다."
)
st.divider()

col_form, col_result = st.columns([4, 6], gap="large")

generate_btn = False
run_all_btn  = False

with col_form:
    current_step = st.session_state.current_step
    render_step_bar(current_step)
    st.divider()

    can_proceed = True
    if current_step == 0:
        can_proceed = render_step1()
    elif current_step == 1:
        render_step2()
    elif current_step == 2:
        can_proceed = render_step3()
    elif current_step == 3:
        render_step4()

    st.divider()
    col_prev, col_next = st.columns(2)

    with col_prev:
        if current_step > 0:
            st.button("← 이전", on_click=go_prev, use_container_width=True)

    with col_next:
        if current_step < TOTAL_STEPS - 1:
            st.button("다음 →", type="primary", on_click=go_next,
                      use_container_width=True, disabled=not can_proceed)
        else:
            can_gen = bool(st.session_state.get("basic_coverage_items", []))

            generate_btn = st.button(
                "⚡ 초안 생성 (Upstage)",
                type="primary", use_container_width=True, disabled=not can_gen,
                help="Upstage Solar 단일 모델로 빠르게 생성",
            )
            run_all_btn = st.button(
                "🔄 4개 모델 병렬 실행 (OpenRouter)",
                use_container_width=True, disabled=not can_gen,
                help="OpenRouter 무료 모델 4개 병렬 실행",
            )
            if not can_gen:
                st.warning("⚠️ STEP 3에서 기본 보장 종목을 선택하세요.")

# ────────────────────────────────────────────────────────────────────────────
# 결과 패널
# ────────────────────────────────────────────────────────────────────────────

with col_result:
    st.subheader("생성된 초안")

    if generate_btn or run_all_btn:
        if (st.session_state.get("fetal_enrollment") == "불가"
                and st.session_state.get("join_age_min") == "태아"):
            st.error("⚠️ 태아 가입 불가 설정이지만 최소 가입나이가 태아입니다. STEP 2를 확인하세요.")
        else:
            try:
                if generate_btn:
                    with st.status("초안 생성 중...", expanded=True) as status_box:
                        request = build_request(model=None)
                        response = requests.post(
                            f"{BACKEND_URL}/generate/stream",
                            json=request, stream=True, timeout=300,
                        )
                        response.raise_for_status()
                        result = None
                        for event in sseclient.SSEClient(response).events():
                            if event.data == "[DONE]":
                                break
                            data = json.loads(event.data)
                            if data.get("type") == "progress":
                                node = data.get("node", "")
                                if node:
                                    st.write(f"{NODE_EMOJI.get(node,'⚙️')} **{node}** 완료 (iter {data.get('iteration',0)})")
                            elif data.get("type") == "result":
                                result = data
                            elif data.get("type") == "error":
                                raise Exception(data.get("message", "스트리밍 오류"))
                        if result is None:
                            raise Exception("결과를 받지 못했습니다.")
                        model_used = result.get("model_used", "Upstage Solar")
                        st.write(f"✅ 생성 완료: {model_used}")
                else:
                    with st.status("4개 모델 병렬 실행 중...", expanded=True) as status_box:
                        st.write("OpenRouter 무료 모델 4개 동시 요청...")
                        all_results = asyncio.run(_run_parallel())
                        result      = best_result(all_results)
                        model_used  = result.get("model_used", "unknown")
                        st.write(f"✅ 최적 결과 선택: {model_used}")

                final_status = result.get("status", "")
                label = (
                    f"초안 생성 완료 — {result.get('iteration','?')}회 검토 통과 ({model_used})"
                    if final_status == "COMPLIANCE_PASSED"
                    else f"최대 {MAX_ITERATIONS}회 도달 — 수동 검토 필요"
                    if final_status == "MANUAL_REVIEW_REQUIRED"
                    else "오류 발생"
                )
                state = (
                    "complete" if final_status == "COMPLIANCE_PASSED" else
                    "error"    if final_status in ("MANUAL_REVIEW_REQUIRED", "ORCHESTRATOR_ERROR")
                    else "running"
                )
                status_box.update(label=label, state=state)
                st.session_state.generation_result = result
                st.session_state.generation_model  = model_used

            except requests.exceptions.HTTPError as e:
                st.error(f"오류 발생: {e}")
                if e.response is not None:
                    st.json(e.response.json())
            except Exception as e:
                st.error(f"오류 발생: {e}")
                st.exception(e)

    if "generation_result" in st.session_state:
        render_result_panel(
            st.session_state.generation_result,
            st.session_state.get("generation_model", "Upstage Solar"),
        )
    elif not (generate_btn or run_all_btn):
        company = st.session_state.get("insurance_company", "삼성화재")
        st.info(
            f"**현재 설정:** {company}\n\n"
            "좌측 폼을 모두 입력한 후 **STEP 4**에서 생성 버튼을 클릭하세요.\n\n"
            "약관·상품설명서·사업방법서 3개 문서가 한 번에 생성됩니다."
        )
        st.markdown("""
**생성 흐름 (LangManus 아키텍처)**
1. 🔍 **Coordinator** — 요청 유효성 검증
2. 📋 **Planner** — 실행 계획 수립
3. ✍️ **Generation** — RAG + LLM으로 초안 생성
4. ⚖️ **Compliance** — 법규 준수 검증 (5개 룰)
5. 🎯 **Supervisor** — 재생성 or 편집 결정
6. ✏️ **Edit** — 최종 편집 및 다중 문서 생성
        """)
        with st.expander("📊 3사 데이터 비교"):
            st.markdown("""
| 항목 | 삼성화재 | 현대해상 | DB손해보험 |
|------|---------|---------|-----------|
| 가입나이 | 0세~65세 | 태아~60세 | 5세~99세 |
| MRI 한도 | 300만원 | 300만원 | 200만원 |
| 도수치료 | 350만원 | 350만원 | 350만원 |
| 보험기간 | 1년 만기 | 1년 만기 | 1년 만기 |
| 갱신주기 | 1년 | 1년 | 1년 |
| 재가입주기 | 5년 | 5년 | 5년 |
            """)
