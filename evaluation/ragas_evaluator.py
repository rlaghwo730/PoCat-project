# RAGAS 평가 파이프라인
# ragas==0.2.6 + pydantic v2 충돌로 인해 동등한 LLM 기반 평가로 구현
# 평가 메트릭: faithfulness, answer_relevancy, context_precision, context_recall
# 골든셋: evaluation/ragas_test_dataset.json (31개 질문)

"""
RAGAS-style evaluation using Upstage solar-pro directly.
Implements the 4 core metrics: faithfulness, answer_relevancy,
context_precision, context_recall.
"""
import sys
import json
import os
import re
import math
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "generation_agent"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


# ---------------------------------------------------------------------------
# RAG pipeline
# ---------------------------------------------------------------------------

def run_rag(question: str) -> dict:
    try:
        from generation_agent.rag.document_loader import get_vectorstore
        from langchain_upstage import ChatUpstage
        from langchain_core.messages import HumanMessage

        vectorstore = get_vectorstore()
        retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
        docs = retriever.invoke(question)
        contexts = [doc.page_content for doc in docs]

        llm = ChatUpstage(
            model="solar-pro",
            api_key=os.getenv("UPSTAGE_API_KEY")
        )
        context_text = "\n\n---\n\n".join(contexts)
        prompt = f"""다음 약관 내용을 참고하여 질문에 간결하고 정확하게 답변하세요.

## 참고 약관
{context_text}

## 질문
{question}

## 답변:"""
        response = llm.invoke([HumanMessage(content=prompt)])
        return {"answer": response.content, "contexts": contexts}

    except Exception as e:
        return {"answer": f"오류: {e}", "contexts": []}


# ---------------------------------------------------------------------------
# Test dataset
# ---------------------------------------------------------------------------

TEST_DATASET = [
    {
        "question": "암 진단 시 보험금 지급 조건은 무엇인가요?",
        "ground_truth": "암으로 최초 진단 확정 시 암 진단금이 지급됩니다.",
    },
    {
        "question": "보험료 납입 면제 조건은 어떻게 되나요?",
        "ground_truth": "피보험자가 특정 중증 질환으로 진단되거나 장해 상태가 되면 이후 보험료 납입이 면제됩니다.",
    },
    {
        "question": "실손 의료비 보험에서 자기부담금은 얼마인가요?",
        "ground_truth": "실손 의료비 보험의 자기부담금은 통상 급여 항목 20%, 비급여 항목 30%입니다.",
    },
    {
        "question": "보험 계약 해지 시 환급금은 어떻게 계산되나요?",
        "ground_truth": "해지 환급금은 계약 경과 기간과 납입 보험료를 기준으로 산출된 해약환급금 표에 따라 지급됩니다.",
    },
    {
        "question": "갱신형 보험의 보험료 인상 기준은 무엇인가요?",
        "ground_truth": "갱신 시점의 나이, 위험률 변동, 물가 상승 등을 반영하여 보험료가 재산정됩니다.",
    },
]


# ---------------------------------------------------------------------------
# RAGAS-style metric implementations
# ---------------------------------------------------------------------------

def _ask_score(llm, prompt: str) -> float:
    """Ask the LLM to return a 0-1 score and parse it."""
    from langchain_core.messages import HumanMessage
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        text = response.content.strip()
        numbers = re.findall(r"0?\.\d+|1\.0|0|1", text)
        if numbers:
            return min(1.0, max(0.0, float(numbers[0])))
    except Exception:
        pass
    return float("nan")


def score_faithfulness(llm, answer: str, contexts: list[str]) -> float:
    context_text = "\n\n".join(contexts)
    prompt = f"""아래 '참고 문서'를 바탕으로 '답변'이 얼마나 충실하게 근거에만 기반하는지 평가하세요.
참고 문서에 없는 내용이 포함될수록 점수가 낮아집니다.
0.0(전혀 충실하지 않음) ~ 1.0(완전히 충실함) 사이의 숫자 하나만 출력하세요.

참고 문서:
{context_text}

답변:
{answer}

점수:"""
    return _ask_score(llm, prompt)


def score_answer_relevancy(llm, question: str, answer: str) -> float:
    prompt = f"""아래 '질문'에 대해 '답변'이 얼마나 관련성 있고 직접적으로 답하는지 평가하세요.
0.0(전혀 관련 없음) ~ 1.0(완벽하게 답변함) 사이의 숫자 하나만 출력하세요.

질문:
{question}

답변:
{answer}

점수:"""
    return _ask_score(llm, prompt)


def score_context_precision(llm, question: str, contexts: list[str]) -> float:
    scores = []
    for ctx in contexts:
        prompt = f"""아래 '참고 문서'가 '질문'에 답하기 위해 얼마나 유용한지 평가하세요.
0.0(전혀 관련 없음) ~ 1.0(완전히 관련 있음) 사이의 숫자 하나만 출력하세요.

질문:
{question}

참고 문서:
{ctx}

점수:"""
        s = _ask_score(llm, prompt)
        if not math.isnan(s):
            scores.append(s)
    return sum(scores) / len(scores) if scores else float("nan")


def score_context_recall(llm, contexts: list[str], ground_truth: str) -> float:
    context_text = "\n\n".join(contexts)
    prompt = f"""아래 '정답'의 내용이 '참고 문서'에 얼마나 포함되어 있는지 평가하세요.
0.0(전혀 포함되지 않음) ~ 1.0(완전히 포함됨) 사이의 숫자 하나만 출력하세요.

참고 문서:
{context_text}

정답:
{ground_truth}

점수:"""
    return _ask_score(llm, prompt)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    from langchain_upstage import ChatUpstage

    llm = ChatUpstage(
        model="solar-pro",
        api_key=os.getenv("UPSTAGE_API_KEY")
    )

    print("=== RAG 응답 수집 중... ===")
    rows = []
    for item in TEST_DATASET:
        q = item["question"]
        gt = item["ground_truth"]
        print(f"  Q: {q}")
        result = run_rag(q)
        print(f"  A: {result['answer'][:80]}...")
        rows.append({
            "question": q,
            "answer": result["answer"],
            "contexts": result["contexts"],
            "ground_truth": gt,
        })

    print("\n=== RAGAS 메트릭 평가 중... ===")
    metric_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    all_scores: dict[str, list[float]] = {k: [] for k in metric_keys}

    for i, row in enumerate(rows):
        q, a, ctx, gt = row["question"], row["answer"], row["contexts"], row["ground_truth"]
        print(f"  [{i+1}/{len(rows)}] 평가 중: {q[:40]}...")

        f = score_faithfulness(llm, a, ctx)
        ar = score_answer_relevancy(llm, q, a)
        cp = score_context_precision(llm, q, ctx)
        cr = score_context_recall(llm, ctx, gt)

        for key, val in zip(metric_keys, [f, ar, cp, cr]):
            if not math.isnan(val):
                all_scores[key].append(val)

    def safe_mean(lst):
        return sum(lst) / len(lst) if lst else float("nan")

    scores = {k: safe_mean(v) for k, v in all_scores.items()}

    output_path = ROOT / "ragas_results.json"
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(scores, fp, ensure_ascii=False, indent=2)

    print("\n=== RAGAS 평가 결과 ===")
    for k, v in scores.items():
        print(f"  {k}: {v:.4f}" if not math.isnan(v) else f"  {k}: NaN")
    print(f"\n결과 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
