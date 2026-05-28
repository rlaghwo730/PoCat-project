from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

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


_GENERATION_SYSTEM = (
    "당신은 보험 약관 전문 작성자입니다. "
    "참고 약관을 기반으로 정확하고 법규에 맞는 실손의료보험 약관 초안을 작성하세요. "
    "약관은 명확하고 이해하기 쉬운 언어로 작성하되, 법적 정확성을 유지해야 합니다."
)

_DESCRIPTION_SYSTEM = (
    "당신은 보험 상품 설명 전문가입니다. "
    "보험 약관을 바탕으로 일반 소비자가 이해하기 쉬운 상품설명서를 작성하세요. "
    "전문 용어는 쉬운 말로 풀어서 설명하고, 핵심 내용을 간결하고 명확하게 전달하세요. "
    "표나 목록을 적극 활용하여 가독성을 높이세요."
)


class GenerationAgent:
    def __init__(self) -> None:
        self.llm = ChatOllama(model="qwen2.5:14b")
        self._defaults = _load_default_schema()
        vectorstore = get_vectorstore()
        self.retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
        self.langfuse = Langfuse()
        self.langfuse_handler = CallbackHandler()

    def _retrieve_context(self, request: dict) -> str:
        doc_req = request["document_request"]
        coverage = request["coverage_conditions"]
        query = (
            f"{doc_req['product_name']} "
            f"{' '.join(coverage['basic_coverage_items'])} "
            f"자기부담금 {coverage['deductible_rule']}"
        )
        docs = self.retriever.invoke(query)
        return "\n\n---\n\n".join(d.page_content for d in docs)

    def _build_generation_prompt(self, request: dict, context: str) -> str:
        doc_req = request["document_request"]
        design = request["product_design_conditions"]
        coverage = request["coverage_conditions"]
        applicant = request["applicant_info"]

        lines = [
            "## 참고 약관 (RAG 검색 결과)",
            context,
            "",
            "## 상품 정보",
            f"- 문서 유형: {doc_req['document_type']}",
            f"- 보험회사: {doc_req['insurance_company']}",
            f"- 상품명: {doc_req['product_name']}",
            f"- 버전: {doc_req['product_version']}",
            "",
            "## 상품 설계 조건",
            f"- 보험기간: {design['policy_period']}",
            f"- 납입기간: {design['premium_payment_period']}",
            f"- 갱신유형: {design['renewal_type']} ({design['renewal_period']})",
            f"- 최대보장나이: {design['max_coverage_age']}",
            f"- 가입연령: {design['join_age_range']}",
            "",
            "## 보장 조건",
            f"- 기본보장종목: {', '.join(coverage['basic_coverage_items'])}",
            f"- 비급여 특약종목: {', '.join(coverage['noncovered_rider_items'])}",
            f"- 3대 비급여 항목: {', '.join(coverage['three_major_noncovered_items'])}",
            f"- 보장한도: {coverage['coverage_limit']}",
            f"- 자기부담금: {coverage['deductible_rule']}",
            "",
            "## 계약자 정보",
            f"- 가입자 유형: {applicant['applicant_type']}",
            f"- 생년월일: {applicant['birth_date']}",
            f"- 성별: {applicant['gender']}",
            f"- 직업: {applicant['occupation']}",
            "",
            "위 참고 약관과 조건을 기반으로 실손의료보험 약관 초안을 작성하세요.",
            "다음 항목을 포함하여 상세히 작성하세요:",
            "1. 약관 전문 (목적, 용어 정의)",
            "2. 보험금 지급 조건 및 보장 내용",
            "3. 자기부담금 및 보장 한도",
            "4. 면책 조항 및 보험금 부지급 사유",
            "5. 갱신 조건 및 절차",
            "6. 계약의 성립 및 유지",
            "7. 보험금 청구 절차",
        ]

        return "\n".join(lines)

    def generate(self, request: dict) -> dict:
        request = _deep_merge(self._defaults, request)
        doc_req = request["document_request"]
        coverage = request["coverage_conditions"]

        context = self._retrieve_context(request)
        prompt = self._build_generation_prompt(request, context)
        response = self.llm.invoke(
            [
                SystemMessage(content=_GENERATION_SYSTEM),
                HumanMessage(content=prompt),
            ],
            config={"callbacks": [self.langfuse_handler]},
        )

        return {
            "section_type": doc_req["document_type"],
            "content": response.content,
            "product_meta": {
                "product_name": doc_req["product_name"],
                "deductible": coverage["deductible_rule"],
            },
            "iteration": 1,
        }

    def generate_product_description(self, clause_content: str, request: dict) -> str:
        doc_req = request["document_request"]
        design = request["product_design_conditions"]
        coverage = request["coverage_conditions"]

        prompt_lines = [
            "## 참고 약관 텍스트",
            clause_content,
            "",
            "## 상품 정보",
            f"- 상품명: {doc_req['product_name']}",
            f"- 보험기간: {design['policy_period']}",
            f"- 갱신유형: {design['renewal_type']} ({design['renewal_period']})",
            f"- 최대보장나이: {design['max_coverage_age']}",
            f"- 가입연령: {design['join_age_range']}",
            "",
            "## 보장 조건",
            f"- 기본보장종목: {', '.join(coverage['basic_coverage_items'])}",
            f"- 비급여 특약종목: {', '.join(coverage['noncovered_rider_items'])}",
            f"- 3대 비급여 항목: {', '.join(coverage['three_major_noncovered_items'])}",
            f"- 보장한도: {coverage['coverage_limit']}",
            f"- 자기부담금: {coverage['deductible_rule']}",
            "",
            "위 약관을 기반으로 일반 소비자를 위한 상품설명서를 작성하세요.",
            "다음 5가지 항목을 모두 포함하여 쉽고 친절한 언어로 작성하세요:",
            "1. 상품 개요 (상품명, 보험기간, 보장내용 요약)",
            "2. 주요 보장내용 (급여/비급여 보장 범위)",
            "3. 자기부담금 안내",
            "4. 보험료 납입 안내",
            "5. 유의사항",
        ]

        response = self.llm.invoke(
            [
                SystemMessage(content=_DESCRIPTION_SYSTEM),
                HumanMessage(content="\n".join(prompt_lines)),
            ],
            config={"callbacks": [self.langfuse_handler]},
        )
        return response.content

    def regenerate(self, request: dict, feedback: dict, iteration: int) -> dict:
        request = _deep_merge(self._defaults, request)
        doc_req = request["document_request"]
        coverage = request["coverage_conditions"]

        priority_fixes = feedback.get("priority_fixes", [])
        context = self._retrieve_context(request)
        base_prompt = self._build_generation_prompt(request, context)

        fixes_text = "\n".join(f"- {fix}" for fix in priority_fixes)
        regeneration_section = (
            f"\n\n## 법규 준수 검토 피드백 (초안 #{iteration - 1} 검토 결과)\n"
            f"아래 항목을 반드시 수정하여 약관을 재작성하세요:\n{fixes_text}\n"
        )

        response = self.llm.invoke(
            [
                SystemMessage(content=_GENERATION_SYSTEM),
                HumanMessage(content=base_prompt + regeneration_section),
            ],
            config={"callbacks": [self.langfuse_handler]},
        )

        return {
            "section_type": doc_req["document_type"],
            "content": response.content,
            "product_meta": {
                "product_name": doc_req["product_name"],
                "deductible": coverage["deductible_rule"],
            },
            "iteration": iteration,
        }
