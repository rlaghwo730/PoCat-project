from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from rag.document_loader import get_vectorstore

load_dotenv()

_SCHEMA_PATH = Path(__file__).parent.parent / "data" / "input_schema.json"


def _load_default_schema() -> dict:
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    """override 값으로 base를 덮어씀. None 값은 무시하고 base 기본값을 유지."""
    result = base.copy()
    for key, val in override.items():
        if val is None:
            continue
        if isinstance(val, dict) and key in result and isinstance(result[key], dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


# ────────────────────────────────────────────────────────────────────────────
# 회사별 메타데이터: 약관 구조, 표기 방식, 상품 특성
# JSON 데이터 분석 기반
# ────────────────────────────────────────────────────────────────────────────

_COMPANY_META = {
    "삼성화재": {
        "product_name_official": "무배당 삼성화재 다이렉트 실손의료비보험(2605.1)",
        "insurance_type_label": "장기손해보험 / 장기기타보험",
        "clause_structure": (
            "보통약관 12관 구조: "
            "제1관(일반사항 및 용어의 정의) → 제2관(회사가 보상하는 사항) → "
            "제3관(회사가 보상하지 않는 사항) → 제4관(보험금의 지급) → "
            "제5관(계약자의 계약 전 알릴 의무 등) → 제6관(보험계약의 성립과 유지) → "
            "제7관(보험료의 납입) → 제8관(계약의 해지 및 해약환급금 등) → "
            "제9관(다수보험의 처리 등) → 제10관(분쟁의 조정 등) → "
            "제11관(자동갱신에 관한 사항 등) → 제12관(재가입에 관한 사항 등)"
        ),
        "article_format": "제N조 (조항명) 형식. 항은 ①②③ 기호 사용.",
        "special_clause_note": (
            "특별약관은 보통약관과 별도 편제. "
            "중증·비중증 비급여 실손의료비 특별약관 각각 독립 구성."
        ),
        "join_age": "0세 ~ 65세",
        "fetal_note": "태아 가입 시 출생일부터 보험기간 개시, 출생 통지 필요.",
        "renewal_note": "갱신횟수 최대 4회, 재가입주기 5년, 갱신나이 (가입나이+1)세 ~ (가입나이+4)세와 99세 중 적은 나이.",
        "mri_limit": "300만원",
        "outpatient_deductible_general": "1만원과 보장대상의료비의 20%, 보장대상의료비에 건강보험 본인부담률을 곱한 금액 중 큰 금액",
        "outpatient_deductible_major": "2만원과 보장대상의료비의 20%, 보장대상의료비에 건강보험 본인부담률을 곱한 금액 중 큰 금액",
    },
    "현대해상": {
        "product_name_official": "무배당 현대해상다이렉트실손의료비보장보험(갱신형)(Hi2605)",
        "insurance_type_label": "장기손해보험 / 장기기타",
        "clause_structure": (
            "보통약관은 공통조항 + 보장종목별 조항 이원 구조: "
            "보통약관_공통조항(계약 공통 사항) + "
            "보통약관_보장종목별(Ⅰ.상해급여실손의료비보장 / Ⅱ.질병급여실손의료비보장). "
            "특별약관은 비급여 실손의료비 보장 특약으로 별도 편제."
        ),
        "article_format": "제N조(조항명) 형식(괄호 앞 공백 없음). 항은 ①②③ 기호 사용.",
        "special_clause_note": (
            "중증비급여 실손의료비(갱신형)보장 특약, "
            "비중증비급여 실손의료비(갱신형)보장 특약 포함. "
            "자기공명영상진단(MRI) 특약 별도 구성 가능."
        ),
        "join_age": "태아 ~ 60세",
        "fetal_note": "태아 가입 시 계약체결일부터 출생 시점까지를 보험기간으로 하며, 출생일 기준으로 매 1년 갱신.",
        "renewal_note": "갱신횟수 최대 4회, 갱신주기 1년, 갱신보험료 변경주기 1년.",
        "mri_limit": "300만원",
        "outpatient_deductible_general": "1만원과 보장대상의료비의 20%, 보장대상의료비에 건강보험 본인부담률을 곱한 금액 중 큰 금액",
        "outpatient_deductible_major": "2만원과 보장대상의료비의 20%, 보장대상의료비에 건강보험 본인부담률을 곱한 금액 중 큰 금액",
    },
    "DB손해보험": {
        "product_name_official": "무배당프로미라이프실손의료비보험2605",
        "insurance_type_label": "장기손해보험 / 장기기타보험",
        "clause_structure": (
            "보통약관 11관 구조: "
            "제1관(일반사항 및 용어의 정의) → 제2관(회사가 보상하는 사항) → "
            "[제3관 없음, 보상하지 않는 사항은 제2관 내 포함] → 제4관(보험금의 지급) → "
            "제5관(계약자의 계약 전 알릴 의무 등) → 제6관(보험계약의 성립과 유지) → "
            "제7관(자동갱신 및 재가입 등) → 제8관(보험료의 납입) → "
            "제9관(계약의 해지 및 해약환급금 등) → 제10관(다수 보험의 처리 등) → "
            "제11관(분쟁의 조정 등). "
            "특별약관1(중증 비급여), 특별약관2(비중증 비급여)는 각 4관 구조로 독립 편제."
        ),
        "article_format": "1.(조항명) 형식(제N조 대신 숫자+점 사용). 항은 ① ② ③ 기호 사용.",
        "special_clause_note": (
            "특별약관1: 중증 비급여 실손의료비(상해·질병·3대비급여). "
            "특별약관2: 비중증 비급여 실손의료비(상해·질병·자기공명영상진단). "
            "각 특별약관은 1관~4관 독립 구조."
        ),
        "join_age": "5세 ~ 99세",
        "fetal_note": "태아 가입 가능. 계약체결일부터 출생 시점까지를 보험기간으로 하며, 피보험자별 출생일 기준으로 매 1년 갱신.",
        "renewal_note": "갱신횟수 최대 4회, 보험료 변경주기 1년, 보장내용변경주기 5년(재가입주기).",
        "mri_limit": "200만원",
        "outpatient_deductible_general": "1만원과 보장대상의료비의 20%, 보장대상의료비에 건강보험 본인부담률을 곱한 금액 중 큰 금액",
        "outpatient_deductible_major": "2만원과 보장대상의료비의 20%, 보장대상의료비에 건강보험 본인부담률을 곱한 금액 중 큰 금액",
    },
}

# ────────────────────────────────────────────────────────────────────────────
# 문서 유형별 System 프롬프트
# ────────────────────────────────────────────────────────────────────────────

_SYSTEM_CLAUSE = (
    "당신은 보험 약관 전문 작성자입니다. "
    "참고 약관과 법규를 기반으로 정확하고 법규에 맞는 실손의료보험 약관 초안을 작성하세요. "
    "반드시 해당 보험회사의 약관 구조(관 편제, 조항 번호 형식)를 그대로 따르세요. "
    "법적 정확성을 유지하면서 명확하고 이해하기 쉬운 언어로 작성하세요."
)

_SYSTEM_DESCRIPTION = (
    "당신은 보험 상품설명서 전문 작성자입니다. "
    "보험 약관을 바탕으로 일반 소비자가 이해하기 쉬운 상품설명서를 작성하세요. "
    "전문 용어는 쉬운 말로 풀어서 설명하고, 핵심 내용을 간결하고 명확하게 전달하세요. "
    "표와 목록을 적극 활용하여 가독성을 높이세요. "
    "금융감독원 상품설명서 작성 기준(주요 내용 요약, 유의사항 포함)을 준수하세요."
)

_SYSTEM_BIZ_METHOD = (
    "당신은 보험 사업방법서 전문 작성자입니다. "
    "보험업법 및 보험업감독규정에 따라 사업방법서 필수 기재 항목을 빠짐없이 작성하세요. "
    "해당 보험회사의 실제 사업방법서 형식과 항목 순서를 그대로 따르세요. "
    "수치(보험료, 한도, 연령 등)는 UI에서 입력받은 값을 정확히 반영하세요."
)

_SYSTEM_DESC = _SYSTEM_DESCRIPTION
_SYSTEM_BIZ  = _SYSTEM_BIZ_METHOD


class GenerationAgent:
    def __init__(self) -> None:
        self._model_override = None
        self._defaults = _load_default_schema()
        self._vectorstore = get_vectorstore()
        self._db_url = os.getenv("DB_API_URL")

    def _get_llm(self, model_override: Optional[str] = None):
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        upstage_key = os.getenv("UPSTAGE_API_KEY")
        if openrouter_key and model_override:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model_override,
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "https://github.com/rlaghwo730/pocat-project",
                    "X-Title": "PoCat5-Insurance-Agent",
                },
            )
        if upstage_key:
            from langchain_upstage import ChatUpstage
            return ChatUpstage(model="solar-pro")
        raise ValueError("API 키 없음")

    # ────────────────────────────────────────────────────────────────────────
    # RAG 검색 — 회사 + 문서유형 기반으로 정밀화
    # ────────────────────────────────────────────────────────────────────────

    def _retrieve_context(self, request: dict, doc_type: str) -> str:
        """
        회사·문서유형 메타데이터 필터 + 의미 검색으로 동일 회사 청크를 우선 반환.
        필터 결과가 부족하면 전사 검색으로 자동 폴백한다.
        """
        doc_req = request["document_request"]
        coverage = request["coverage_conditions"]
        company = doc_req.get("insurance_company", "")
        product_name = doc_req.get("product_name", "")
        basic_items = " ".join(coverage.get("basic_coverage_items", []))
        noncovered = coverage.get("noncovered_rider_items", [])

        if doc_type == "약관":
            type_kw = "보통약관 보장종목 보상하는 사항 보상하지 않는 사항"
            meta_doc_type = "약관"
        elif doc_type == "상품설명서":
            type_kw = "상품요약서 보험금 지급사유 가입자격 유의사항"
            meta_doc_type = "상품요약서"
        else:
            type_kw = "사업방법서 보험기간 가입나이 갱신 재가입"
            meta_doc_type = "사업방법서"

        noncov_kw = " ".join(noncovered) if noncovered else ""
        query = f"{company} {product_name} {basic_items} {noncov_kw} {type_kw}".strip()

        # 회사 + 문서유형 필터 우선 검색
        where = {"$and": [{"company": company}, {"document_type": meta_doc_type}]}
        docs = self._vectorstore.similarity_search(query, k=5, filter=where)

        # 결과 부족 시 회사 필터만으로 폴백
        if len(docs) < 2:
            docs = self._vectorstore.similarity_search(query, k=5, filter={"company": company})

        # 그래도 없으면 전사 검색
        if not docs:
            docs = self._vectorstore.similarity_search(query, k=5)

        return "\n\n---\n\n".join(d.page_content for d in docs)

    def _retrieve_legal_context(self, request: dict) -> Optional[str]:
        """DB에서 관련 법률/규제 데이터를 조회한다."""
        if not self._db_url:
            return None
        try:
            import psycopg2
            conn = psycopg2.connect(self._db_url)
            cur = conn.cursor()

            coverage = request["coverage_conditions"]
            basic_items = coverage.get("basic_coverage_items", [])
            noncovered = coverage.get("noncovered_rider_items", [])
            keywords = basic_items + noncovered
            keyword_str = " ".join(keywords) if keywords else "실손의료보험"

            cur.execute("""
                SELECT
                    source_domain,
                    citation_label,
                    title,
                    LEFT(content, 400) AS content_preview
                FROM unified_retrieval_chunk
                WHERE is_active = TRUE
                  AND source_domain IN ('legal', 'insurance_cited_law')
                  AND (
                    content ILIKE %s
                    OR content ILIKE '%%실손의료보험%%'
                    OR content ILIKE '%%보험업감독규정%%'
                  )
                ORDER BY source_domain
                LIMIT 5;
            """, (f"%{keyword_str[:20]}%",))

            rows = cur.fetchall()
            cur.close()
            conn.close()

            if not rows:
                return None

            legal_lines = []
            for domain, citation, title, preview in rows:
                legal_lines.append(f"[{citation or domain}] {title or ''}")
                legal_lines.append(preview)
                legal_lines.append("")
            return "\n".join(legal_lines)

        except Exception as e:
            print(f"[GenerationAgent] DB 법률 데이터 조회 실패: {e}")
            return None

    # ────────────────────────────────────────────────────────────────────────
    # 공통 입력값 블록 빌더 (3개 문서 공통으로 사용)
    # ────────────────────────────────────────────────────────────────────────

    def _build_input_block(self, request: dict) -> list[str]:
        """UI에서 입력받은 값을 공통 블록으로 정리."""
        doc_req = request["document_request"]
        design  = request["product_design_conditions"]
        coverage = request["coverage_conditions"]
        company = doc_req.get("insurance_company", "삼성화재")
        meta = _COMPANY_META.get(company, {})

        noncovered = coverage.get("noncovered_rider_items", [])
        three_major = coverage.get("three_major_noncovered_items", [])
        coverage_limit = coverage.get("coverage_limit", {})
        deductible = coverage.get("deductible_rule", {})

        # 자기부담금: dict면 세분화, string이면 그대로
        if isinstance(deductible, dict):
            deductible_str = (
                f"일반 의료기관 통원: {deductible.get('일반_의료기관', meta.get('outpatient_deductible_general', ''))}, "
                f"상급종합병원 통원: {deductible.get('상급종합병원', meta.get('outpatient_deductible_major', ''))}"
            )
        else:
            deductible_str = str(deductible)

        # 보장한도 - 선택된 항목만 포함
        limit_lines = []
        if isinstance(coverage_limit, dict):
            limit_lines.append(f"  · 급여 연간 한도: {coverage_limit.get('급여', '5천만원')}")
            limit_lines.append(f"  · 통원 1회 한도: {coverage.get('outpatient_limit', '20만원')}")
            if noncovered:
                limit_lines.append(f"  · 비급여 연간 한도: {coverage_limit.get('비급여', '5천만원')}")
            if three_major:
                limit_lines.append(f"  · 도수치료·체외충격파·증식치료: {coverage_limit.get('도수치료', '350만원')}")
                limit_lines.append(f"  · 주사료(비급여): {coverage_limit.get('주사료', '250만원')}")
                limit_lines.append(f"  · MRI/MRA: {coverage_limit.get('MRI', meta.get('mri_limit', '300만원'))}")
        else:
            limit_lines.append(f"  · {coverage_limit}")

        lines = [
            "## 입력된 상품 조건",
            f"- 보험회사: {company} ({meta.get('insurance_type_label', '')})",
            f"- 생성 문서: 약관·상품설명서·사업방법서 (일괄 생성)",
            f"- 상품명: {doc_req.get('product_name', '')}",
            f"- 버전/코드: {doc_req.get('product_version', '')}",
            f"- 배당 여부: {doc_req.get('dividend_type', '무배당')}",
            f"- 보험 유형: {doc_req.get('insurance_type', '기본형 실손의료비보험')}",
            "",
            "### 상품 설계 조건 (사업방법서 기준)",
            f"- 보험기간: {design.get('policy_period', '1년 만기')}",
            f"- 납입기간: {design.get('premium_payment_period', '전기납')}",
            f"- 납입주기: {design.get('premium_payment_cycle', '월납')}",
            f"- 갱신 유형/주기: {design.get('renewal_type', '갱신형')} / {design.get('renewal_period', '1년')}",
            f"- 최대 갱신 횟수: {design.get('max_renewal_count', 4)}회",
            f"- 재가입 주기: {design.get('reinstatement_cycle', '5년')}",
            f"- 가입나이: {design.get('join_age_min', '')} ~ {design.get('join_age_max', '')}",
            f"  (참고: {company} 기본 가입나이: {meta.get('join_age', '')})",
            f"- 최대 보장나이: {design.get('max_coverage_age', 100)}세",
            f"- 태아 가입: {design.get('fetal_enrollment', '가능')}",
            f"  (태아 가입 처리: {meta.get('fetal_note', '')})",
            f"- 보험계약대출: {design.get('policy_loan', '가능')}",
            f"- 갱신 관련 특이사항: {meta.get('renewal_note', '')}",
            "",
            "### 보장 조건 (약관 기준)",
            f"- 기본 보장 종목: {', '.join(coverage.get('basic_coverage_items', []))}",
        ]

        if noncovered:
            lines.append(f"- 비급여 특약: {', '.join(noncovered)}")
        if three_major:
            lines.append(f"- 3대 비급여 세부항목: {', '.join(three_major)}")

        lines.append("- 보험가입금액 한도:")
        lines.extend(limit_lines)
        lines.append(f"- 자기부담금(공제금액): {deductible_str}")
        lines.append("")

        return lines

    def _build_company_structure_block(self, company: str, doc_type: str) -> list[str]:
        """회사별 문서 구조 지침 블록."""
        meta = _COMPANY_META.get(company, {})
        lines = [f"## {company} {doc_type} 작성 지침"]

        if doc_type == "약관":
            lines += [
                f"### 약관 구조",
                f"{meta.get('clause_structure', '')}",
                "",
                f"### 조항 번호/기호 형식",
                f"{meta.get('article_format', '')}",
                "",
                f"### 특별약관 편제",
                f"{meta.get('special_clause_note', '')}",
                "",
                "### 작성 규칙",
                "- 위 관 편제 순서대로 빠짐없이 작성할 것",
                "- 각 조항은 해당 회사 형식(조 번호, ①②③ 기호)을 정확히 따를 것",
                "- 비급여 특약이 선택된 경우에만 특별약관 파트를 포함할 것",
                "- 참고 약관 텍스트의 표현 방식과 용어를 최대한 유지할 것",
            ]
        elif doc_type == "상품설명서":
            if company == "현대해상":
                lines += [
                    "### 상품설명서 필수 항목 (현대해상 형식)",
                    "1. 보험상품의 특성 및 가입자격",
                    "2. 보험금 지급사유, 지급금액 및 지급제한사항",
                    "3. 주요 용어 해설",
                    "4. 보험료 산출기초 (예정이율, 보험가격지수)",
                    "5. 보험료 및 위험률 변동에 관한 사항",
                    "6. 해약환급금에 관한 사항",
                    "7. 유의사항",
                    "",
                    "- Q&A 형식(Q> / A>) 활용 권장",
                    "- 표 형식으로 보장내용 정리",
                ]
            elif company == "DB손해보험":
                lines += [
                    "### 상품설명서 필수 항목 (DB손해보험 형식)",
                    "1. 보험가입자격 제한 등 상품별 특이사항",
                    "2. 보험금 지급사유 및 지급제한 사항 (통원항목별 공제금액 포함)",
                    "3. 보험료 산출기초 (보험료의 구성, 예정이율, 예정위험률, 예정사업비율)",
                    "4. 보험가격지수",
                    "5. 해약환급금에 관한 사항",
                    "",
                    "- 표 형식으로 보장내용 및 공제금액 정리",
                    "- 연간 보험가입금액 예시 포함",
                ]
            else:  # 삼성화재
                lines += [
                    "### 상품설명서 필수 항목 (삼성화재 형식)",
                    "1. 상품 개요 (상품명, 보험기간, 보장내용 요약)",
                    "2. 주요 보장내용 (급여/비급여 보장 범위, 보상금액)",
                    "3. 자기부담금 및 보장 한도",
                    "4. 보험료 납입 안내",
                    "5. 유의사항",
                    "",
                    "- 표 형식 적극 활용",
                    "- 소비자 친화적 언어 사용",
                ]
        else:  # 사업방법서
            if company == "삼성화재":
                lines += [
                    "### 사업방법서 필수 항목 (삼성화재 형식, 총 21개 항목)",
                    "1. 보험의 종류: 장기손해보험 / 장기기타보험",
                    "2. 보험종목의 명칭",
                    "3. 보험의 목적",
                    "4. 보험기간, 보험료 납입기간, 재가입 주기, 가입나이, 보험료 납입주기",
                    "5. 의무가입에 관한 사항",
                    "6. 배당에 관한 사항",
                    "7. 보험료 차등 적용에 관한 사항",
                    "8. 자동갱신 적용 및 갱신에 관한 사항",
                    "9. 보험료 운영에 관한 사항",
                    "10. 보험료의 납입을 연체하여 해지된 계약의 부활(효력회복)시 연체이율에 관한 사항",
                    "11. 보험료 선납에 관한 사항",
                    "12. 추가납입보험료에 관한 사항 (해당없음)",
                    "13. 중도인출에 관한 사항 (해당없음)",
                    "14. 보험계약대출에 관한 사항",
                    "15. 공시이율에 관한 사항",
                    "16. 재가입에 관한 사항",
                    "17. 태아(胎兒) 가입시의 처리",
                    "18. 태아(胎兒) 가입 후 해지 시의 처리",
                    "19. 부가 서비스에 관한 사항",
                    "20. 태아(胎兒) 가입시 계약 전 알릴의무 사항에 관한 사항",
                    "21. 기타 사항",
                ]
            elif company == "현대해상":
                lines += [
                    "### 사업방법서 필수 항목 (현대해상 형식, 총 16개 항목)",
                    "1. 보험의 종류",
                    "2. 보험종목의 명칭",
                    "3. 보험기간, 보험료 납입기간, 가입나이, 보험료 납입주기 등",
                    "4. 의무가입에 관한 사항",
                    "5. 배당에 관한 사항",
                    "6. 보험료 차등적용에 관한 사항",
                    "7. 갱신계약에 관한 사항",
                    "8. 보험료 운영에 관한 사항",
                    "9. 보험료의 납입연체로 인한 해지계약의 부활(효력회복)시 연체이율에 관한 사항",
                    "10. 보험료 선납에 관한 사항",
                    "11. 추가적립보험료에 관한 사항",
                    "12. 중도인출에 관한 사항",
                    "13. 보험계약대출이율에 관한 사항",
                    "14. 공시이율에 관한 사항",
                    "15. 보험료 정산에 관한 사항",
                    "16. 기 타",
                ]
            else:  # DB손해보험
                lines += [
                    "### 사업방법서 필수 항목 (DB손해보험 형식, 총 18개 항목)",
                    "1. 보험의종류",
                    "2. 보험종목의명칭등",
                    "3. 보험의목적",
                    "4. 보험기간, 보험료납입기간, 보험료변경주기, 보장내용변경주기, 가입나이, 재가입종료나이 및 보험료납입주기",
                    "5. 의무가입에관한사항",
                    "6. 배당에관한사항",
                    "7. 보험료차등적용에관한사항",
                    "8. 갱신담보에관한사항",
                    "9. 보험료운영에관한사항",
                    "10. 보험료의납입연체로인한해지계약의부활(효력회복)시연체이율에관한사항",
                    "11. 보험료선납에관한사항",
                    "12. 추가적립보험료에관한사항",
                    "13. 중도인출에관한사항",
                    "14. 보험계약대출이율에관한사항",
                    "15. 공시이율에관한사항",
                    "16. 조건부인수를위한특별약관",
                    "17. 보험금지급사유가회사의자체적인기준이아닌계약에관한사항",
                    "18. 기타",
                ]

        lines.append("")
        return lines

    # ────────────────────────────────────────────────────────────────────────
    # 약관 프롬프트
    # ────────────────────────────────────────────────────────────────────────

    def _build_clause_prompt(self, request: dict, context: str, legal_context: Optional[str] = None) -> str:
        doc_req = request["document_request"]
        company = doc_req.get("insurance_company", "삼성화재")
        coverage = request["coverage_conditions"]
        noncovered = coverage.get("noncovered_rider_items", [])

        lines = [
            "## 참고 약관 (RAG 검색 결과 — 동일 회사 실제 약관)",
            context,
            "",
        ]
        if legal_context:
            lines += ["## 관련 법률/규제 참고자료", legal_context, ""]

        lines += self._build_company_structure_block(company, "약관")
        lines += self._build_input_block(request)
        lines += [
            "## 작성 지시",
            f"위 참고 약관, 입력 조건, {company} 약관 구조 지침을 바탕으로 약관 초안을 작성하세요.",
            "",
            "【필수 포함 항목】",
            "1. 보통약관 전체 관 구조 (위 구조 지침의 순서대로)",
            "   - 제1관: 일반사항 및 용어의 정의 (보장종목 정의 포함)",
            "   - 제2관: 회사가 보상하는 사항 (기본 보장 종목별 보상금액, 자기부담금 표 포함)",
            "   - 제3관: 회사가 보상하지 않는 사항 (면책조항)",
            "   - 제4관: 보험금의 지급 (보험가입금액 한도, 지급 절차)",
            "   - 제5관~: 계약 관련 사항 (성립, 알릴 의무, 갱신, 재가입 등)",
        ]
        if noncovered:
            lines += [
                "",
                "2. 특별약관 파트 (비급여 특약 선택됨)",
                f"   - {company} 특별약관 형식에 따라 비급여 보장 종목별로 편제",
                "   - 중증/비중증 구분하여 작성",
            ]
        lines += [
            "",
            "【작성 시 주의사항】",
            f"- {company} 조항 번호 형식을 정확히 따를 것 (다른 회사 형식 혼용 금지)",
            "- 입력된 수치(보장 한도, 자기부담금, 가입나이 등)를 정확히 반영할 것",
            "- 참고 약관의 법적 표현과 용어를 최대한 유지할 것",
            "- 실손의료보험 표준화 요건(보험업감독규정)을 준수할 것",
        ]
        return "\n".join(lines)

    # ────────────────────────────────────────────────────────────────────────
    # 상품설명서 프롬프트
    # ────────────────────────────────────────────────────────────────────────

    def _build_description_prompt(self, clause_content: str, request: dict) -> str:
        doc_req = request["document_request"]
        company = doc_req.get("insurance_company", "삼성화재")

        lines = [
            "## 생성된 약관 텍스트 (참고용)",
            clause_content[:3000],  # 너무 길면 앞부분만 참조
            "",
        ]
        lines += self._build_company_structure_block(company, "상품설명서")
        lines += self._build_input_block(request)
        lines += [
            "## 작성 지시",
            f"위 약관과 입력 조건을 바탕으로 {company} 형식의 상품설명서를 작성하세요.",
            "",
            "【작성 시 주의사항】",
            "- 일반 소비자가 이해할 수 있는 쉬운 언어 사용",
            "- 보험금 지급 사유와 공제금액은 표 형식으로 정리",
            f"- 위 [{company} 형식] 항목 순서대로 빠짐없이 작성",
            "- 입력된 수치(보장 한도, 자기부담금, 가입나이 등)를 정확히 반영",
            "- 과장 표현 및 주관적 표현 금지 (법규 준수)",
        ]
        return "\n".join(lines)

    # ────────────────────────────────────────────────────────────────────────
    # 사업방법서 프롬프트
    # ────────────────────────────────────────────────────────────────────────

    def _build_biz_method_prompt(self, request: dict, context: str) -> str:
        doc_req = request["document_request"]
        company = doc_req.get("insurance_company", "삼성화재")

        lines = [
            "## 참고 사업방법서 (RAG 검색 결과 — 동일 회사 실제 사업방법서)",
            context,
            "",
        ]
        lines += self._build_company_structure_block(company, "사업방법서")
        lines += self._build_input_block(request)
        lines += [
            "## 작성 지시",
            f"위 참고 사업방법서와 입력 조건을 바탕으로 {company} 형식의 사업방법서 초안을 작성하세요.",
            "",
            "【작성 시 주의사항】",
            f"- 위 [{company} 형식] 항목 번호와 순서를 그대로 따를 것",
            "- 각 항목에 입력된 수치(보험기간, 가입나이, 갱신 횟수, 한도 등)를 정확히 반영",
            "- '해당없음' 항목(추가납입, 중도인출 등)은 해당없음으로 명시",
            "- 참고 사업방법서의 표현 방식과 용어를 최대한 유지",
            "- 보험업법 및 보험업감독규정 상 필수 기재사항 누락 금지",
        ]
        return "\n".join(lines)

    def _build_desc_prompt(self, clause_content: str, request: dict) -> str:
        desc_context = self._retrieve_context(request, doc_type="상품설명서")
        return self._build_description_prompt(
            clause_content + "\n\n---\n\n" + desc_context, request
        )

    def _build_biz_prompt(self, clause_content: str, request: dict) -> str:
        context = self._retrieve_context(request, doc_type="사업방법서")
        return self._build_biz_method_prompt(request, context)

    # ────────────────────────────────────────────────────────────────────────
    # 기존 인터페이스와의 하위 호환을 위한 래퍼 (generate 내부에서 통합 처리)
    # ────────────────────────────────────────────────────────────────────────

    def _build_generation_prompt(self, request: dict, context: str, legal_context: Optional[str] = None) -> str:
        """기존 코드 호환용. 약관 프롬프트로 위임."""
        return self._build_clause_prompt(request, context, legal_context)

    # ────────────────────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────────────────────

    def generate(self, request: dict) -> dict:
        """약관 초안 생성."""
        model_override = request.get("model")
        llm = self._get_llm(model_override)
        request = _deep_merge(self._defaults, request)
        doc_req = request["document_request"]
        coverage = request["coverage_conditions"]

        context = self._retrieve_context(request, doc_type="약관")
        legal_context = self._retrieve_legal_context(request)
        prompt = self._build_clause_prompt(request, context, legal_context)

        response = llm.invoke([
            SystemMessage(content=_SYSTEM_CLAUSE),
            HumanMessage(content=prompt),
        ])

        return {
            "section_type": doc_req["document_type"],
            "content": response.content,
            "product_meta": {
                "product_name": doc_req["product_name"],
                "deductible": coverage.get("deductible_rule", ""),
            },
            "iteration": 1,
        }

    def generate_product_description(self, clause_content: str, request: dict) -> dict:
        """상품설명서 + 사업방법서 동시 생성.

        edit_node에서 약관 최종본 확정 후 한 번만 호출하면 된다.

        Returns:
            {
                "product_description": str,  # 상품설명서
                "business_method":     str,  # 사업방법서
            }
        """
        llm = self._get_llm(request.get("model"))

        # ── 상품설명서 ──────────────────────────────────────────────────────
        desc_context = self._retrieve_context(request, doc_type="상품설명서")
        desc_prompt  = self._build_description_prompt(
            clause_content + "\n\n---\n\n" + desc_context, request
        )
        desc_response = llm.invoke([
            SystemMessage(content=_SYSTEM_DESCRIPTION),
            HumanMessage(content=desc_prompt),
        ])

        # ── 사업방법서 ──────────────────────────────────────────────────────
        biz_content = self._generate_biz_method(request, llm)

        return {
            "product_description": desc_response.content,
            "business_method":     biz_content,
        }

    async def generate_product_description_parallel(self, clause_content: str, request: dict) -> dict:
        """상품설명서 + 사업방법서 병렬 생성"""
        import asyncio
        llm = self._get_llm(request.get("model"))

        desc_prompt = self._build_desc_prompt(clause_content, request)
        biz_prompt  = self._build_biz_prompt(clause_content, request)

        desc_response, biz_response = await asyncio.gather(
            asyncio.to_thread(llm.invoke, [SystemMessage(content=_SYSTEM_DESC), HumanMessage(content=desc_prompt)]),
            asyncio.to_thread(llm.invoke, [SystemMessage(content=_SYSTEM_BIZ), HumanMessage(content=biz_prompt)]),
        )

        return {
            "product_description": desc_response.content,
            "business_method":     biz_response.content,
        }

    def _generate_biz_method(self, request: dict, llm=None) -> str:
        """사업방법서 생성 (내부 전용).

        generate_product_description에서만 호출한다.
        llm을 인자로 받아 재사용하므로 LLM 초기화가 한 번만 일어난다.
        """
        if llm is None:
            llm = self._get_llm(request.get("model"))

        context = self._retrieve_context(request, doc_type="사업방법서")
        prompt  = self._build_biz_method_prompt(request, context)

        response = llm.invoke([
            SystemMessage(content=_SYSTEM_BIZ_METHOD),
            HumanMessage(content=prompt),
        ])
        return response.content

    def regenerate(self, request: dict, feedback: dict, iteration: int) -> dict:
        """법규 위반 피드백 기반 약관 재생성."""
        model_override = request.get("model")
        llm = self._get_llm(model_override)
        request = _deep_merge(self._defaults, request)
        doc_req = request["document_request"]
        coverage = request["coverage_conditions"]

        priority_fixes = feedback.get("priority_fixes", [])
        context = self._retrieve_context(request, doc_type="약관")
        legal_context = self._retrieve_legal_context(request)
        base_prompt = self._build_clause_prompt(request, context, legal_context)

        fixes_text = "\n".join(f"- {fix}" for fix in priority_fixes)
        regeneration_section = (
            f"\n\n## 법규 준수 검토 피드백 (초안 #{iteration - 1} 검토 결과)\n"
            f"아래 항목을 반드시 수정하여 약관을 재작성하세요:\n{fixes_text}\n"
        )

        response = llm.invoke([
            SystemMessage(content=_SYSTEM_CLAUSE),
            HumanMessage(content=base_prompt + regeneration_section),
        ])

        return {
            "section_type": doc_req["document_type"],
            "content": response.content,
            "product_meta": {
                "product_name": doc_req["product_name"],
                "deductible": coverage.get("deductible_rule", ""),
            },
            "iteration": iteration,
        }
