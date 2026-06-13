"""RAGAS 평가 파이프라인 — RAG 검색/답변 품질 평가 (독립 실행 모듈)

이 스크립트는 서비스 흐름에 연결되는 에이전트가 아니라,
개발자가 RAG 시스템의 검색/생성 품질을 측정하기 위한 별도 평가 도구다.

평가 흐름:
  1) ragas_test_dataset.json 에서 (question, ground_truth) 로드
  2) 각 question 을 RAG 시스템에 입력해 answer + contexts 수집  ← run_rag()
  3) RAGAS evaluate() 로 4개 지표 점수 계산
  4) 결과를 CSV / JSON 으로 저장

설계 메모 (final_validation_agent 와 동일한 철학):
  - 기존 LangGraph builder.py / nodes.py 는 건드리지 않는다.
  - .env / API key 를 코드에 하드코딩하지 않는다. (LLM/임베딩은 RAGAS 가 환경변수에서 읽음)
  - run_rag() 는 지금은 TODO/모의 구현이며, 나중에 기존 retriever/agent 호출로 교체한다.

실행:
  python ragas_evaluator.py
  python ragas_evaluator.py --dataset ragas_test_dataset.json --out-csv ragas_results.csv
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_DEFAULT_DATASET = _HERE / "ragas_test_dataset.json"
_DEFAULT_CSV = _HERE / "ragas_results.csv"
_DEFAULT_JSON = _HERE / "ragas_results.json"


# ══════════════════════════════════════════════════════════════════════════════
# 1) RAG 호출부 — 나중에 기존 시스템으로 연결할 지점
# ══════════════════════════════════════════════════════════════════════════════

def run_rag(question: str) -> dict:
    """질문 하나를 RAG 시스템에 입력해 answer 와 contexts 를 돌려준다.

    ┌──────────────────────────────────────────────────────────────────────┐
    │ TODO: 여기를 기존 프로젝트의 retriever / RAG agent 호출로 교체하세요.   │
    └──────────────────────────────────────────────────────────────────────┘

    반환 형식 (반드시 아래 두 키를 채울 것):
        {
            "answer":   str,         # RAG 가 생성한 최종 답변
            "contexts": list[str],   # 검색되어 답변 생성에 사용된 문서 청크들
        }

    연결 예시 ① — retriever + LLM 을 직접 호출하는 경우:
        from backend.src.rag.retriever import get_retriever
        from backend.src.agents.agents import get_generation_llm

        retriever = get_retriever()
        docs = retriever.invoke(question)                 # 검색
        contexts = [d.page_content for d in docs]
        llm = get_generation_llm()
        prompt = f"다음 문맥을 참고해 답하세요.\n\n{contexts}\n\n질문: {question}"
        answer = llm.invoke(prompt).content
        return {"answer": answer, "contexts": contexts}

    연결 예시 ② — 이미 RAG 체인/에이전트가 있는 경우:
        from backend.src.rag.chain import rag_chain
        result = rag_chain.invoke({"question": question})
        return {
            "answer": result["answer"],
            "contexts": [d.page_content for d in result["source_documents"]],
        }

    주의:
      - contexts 는 반드시 '문자열 리스트' 여야 한다 (Document 객체면 .page_content 로 변환).
      - contexts 가 비면 context 관련 지표(precision/recall)가 계산되지 않으니 주의.
    """
    # ── 임시 모의 구현 (단독 실행/스모크 테스트용) ────────────────────────────
    # 실제 연결 시 아래 블록을 위 예시처럼 교체하면 된다.
    logger.warning("[run_rag] 모의 구현 사용 중 — 실제 RAG 시스템에 연결하세요 (TODO).")
    return {
        "answer": f"(모의 답변) '{question}' 에 대한 답변입니다. 실제 RAG 연결 후 교체됩니다.",
        "contexts": [
            "(모의 문맥1) 실제 retriever 가 반환한 문서 청크로 교체하세요.",
            "(모의 문맥2) 실제 retriever 가 반환한 문서 청크로 교체하세요.",
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2) 테스트셋 로드 & RAG 실행으로 평가 입력 구성
# ══════════════════════════════════════════════════════════════════════════════

def load_test_dataset(path: Path) -> list[dict]:
    """[{question, ground_truth}, ...] 형태의 JSON 테스트셋 로드."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("테스트셋은 JSON 배열이어야 합니다.")
    for i, row in enumerate(data):
        if "question" not in row:
            raise ValueError(f"{i}번 항목에 'question' 키가 없습니다.")
        row.setdefault("ground_truth", "")
    logger.info("[dataset] %d개 질문 로드", len(data))
    return data


def build_eval_records(test_rows: list[dict]) -> list[dict]:
    """각 question 에 run_rag() 를 실행해 RAGAS 평가용 레코드 리스트를 만든다.

    반환 각 항목:
        {question, answer, contexts(list[str]), ground_truth}
    """
    records = []
    for row in test_rows:
        q = row["question"]
        rag_out = run_rag(q)
        contexts = rag_out.get("contexts", []) or []
        # 안전 변환: Document 객체가 섞여 와도 문자열 리스트로 정규화
        contexts = [
            c if isinstance(c, str) else getattr(c, "page_content", str(c))
            for c in contexts
        ]
        records.append({
            "question": q,
            "answer": rag_out.get("answer", ""),
            "contexts": contexts,
            "ground_truth": row.get("ground_truth", ""),
        })
    logger.info("[rag] %d개 레코드 생성 완료", len(records))
    return records


# ══════════════════════════════════════════════════════════════════════════════
# 3) RAGAS 평가 실행
# ══════════════════════════════════════════════════════════════════════════════

def _load_metrics() -> list:
    """RAGAS 지표 4종 로드.

    ⚠️ RAGAS 버전에 따라 import 경로/이름이 다를 수 있습니다.
       ImportError 가 나면 아래 후보 중 설치된 버전에 맞게 조정하세요.

       - 0.1.x / 0.2.x:
           from ragas.metrics import (
               faithfulness, answer_relevancy,
               context_precision, context_recall,
           )
       - 일부 버전은 클래스형으로 제공:
           from ragas.metrics import (
               Faithfulness, ResponseRelevancy,
               LLMContextPrecisionWithReference, LLMContextRecall,
           )
         이 경우 인스턴스화해서 사용: [Faithfulness(), ResponseRelevancy(), ...]
    """
    from ragas.metrics import (  # noqa: F401
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
    )
    return [faithfulness, answer_relevancy, context_precision, context_recall]


def _to_ragas_dataset(records: list[dict]):
    """RAGAS evaluate() 입력으로 변환.

    ⚠️ 버전별 입력 형식이 다릅니다. 두 경로를 모두 시도합니다.
       (A) 신버전(0.2+): EvaluationDataset.from_list(...)
       (B) 구버전(0.1.x): datasets.Dataset.from_list(...)  ← 'contexts' 컬럼 사용
    """
    # ── (A) 신버전 경로 ───────────────────────────────────────────────────────
    try:
        from ragas import EvaluationDataset, SingleTurnSample

        samples = [
            SingleTurnSample(
                user_input=r["question"],
                response=r["answer"],
                retrieved_contexts=r["contexts"],
                reference=r["ground_truth"],
            )
            for r in records
        ]
        logger.info("[ragas] 신버전(EvaluationDataset) 입력 사용")
        return EvaluationDataset(samples=samples)
    except ImportError:
        pass

    # ── (B) 구버전 경로 ───────────────────────────────────────────────────────
    # datasets 라이브러리의 Dataset 사용. 컬럼명은 question/answer/contexts/ground_truth.
    from datasets import Dataset

    cols = {
        "question": [r["question"] for r in records],
        "answer": [r["answer"] for r in records],
        "contexts": [r["contexts"] for r in records],
        "ground_truth": [r["ground_truth"] for r in records],
    }
    logger.info("[ragas] 구버전(datasets.Dataset) 입력 사용")
    return Dataset.from_dict(cols)


def evaluate_records(records: list[dict]):
    """RAGAS evaluate() 실행 후 결과 객체 반환.

    LLM/임베딩 자격증명은 RAGAS 가 환경변수(OPENAI_API_KEY 등)에서 읽는다.
    (이 스크립트는 키를 코드에 넣지 않는다.)
    """
    from ragas import evaluate

    metrics = _load_metrics()
    dataset = _to_ragas_dataset(records)

    logger.info("[ragas] evaluate() 실행 — 지표 %d종", len(metrics))
    result = evaluate(dataset=dataset, metrics=metrics)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 4) 결과 저장
# ══════════════════════════════════════════════════════════════════════════════

def save_results(result: Any, records: list[dict],
                 csv_path: Path, json_path: Path) -> dict:
    """평가 결과를 CSV(질문별 점수) + JSON(요약 평균)으로 저장.

    RAGAS result 는 .to_pandas() 로 질문별 점수 DataFrame 을 제공한다(버전별 공통).
    """
    summary: dict = {}

    # ── CSV: 질문별 상세 점수 ────────────────────────────────────────────────
    try:
        df = result.to_pandas()
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        logger.info("[save] CSV 저장: %s", csv_path)

        # 요약 평균: 숫자형 컬럼만 평균
        numeric = df.select_dtypes("number")
        summary = {col: round(float(numeric[col].mean()), 4) for col in numeric.columns}
    except Exception as e:  # noqa: BLE001
        logger.error("[save] to_pandas/CSV 실패: %s", e)
        # 폴백: result 를 dict 로 직접 변환 시도
        try:
            summary = dict(result)
        except Exception:  # noqa: BLE001
            summary = {"error": "결과를 표 형태로 변환하지 못했습니다."}

    # ── JSON: 요약 + 레코드 메타 ─────────────────────────────────────────────
    out = {
        "summary": summary,
        "num_questions": len(records),
        "records": records,
    }
    Path(json_path).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("[save] JSON 저장: %s", json_path)
    return summary


# ══════════════════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(dataset_path: Path, csv_path: Path, json_path: Path,
                 dry_run: bool = False) -> dict:
    """전체 파이프라인 실행. dry_run=True 면 RAGAS 호출 없이 레코드 구성까지만."""
    test_rows = load_test_dataset(dataset_path)
    records = build_eval_records(test_rows)

    if dry_run:
        logger.info("[dry-run] RAGAS 평가 생략 — 레코드 구성까지만 수행")
        # dry-run 에서도 RAG 입력 구조를 확인할 수 있게 JSON 으로 덤프
        Path(json_path).write_text(
            json.dumps({"records": records, "num_questions": len(records)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"dry_run": True, "num_questions": len(records)}

    result = evaluate_records(records)
    summary = save_results(result, records, csv_path, json_path)
    logger.info("[done] 평가 요약: %s", summary)
    return summary


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAGAS RAG 품질 평가 파이프라인")
    p.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET,
                   help="테스트셋 JSON 경로")
    p.add_argument("--out-csv", type=Path, default=_DEFAULT_CSV,
                   help="질문별 점수 CSV 저장 경로")
    p.add_argument("--out-json", type=Path, default=_DEFAULT_JSON,
                   help="요약 결과 JSON 저장 경로")
    p.add_argument("--dry-run", action="store_true",
                   help="RAGAS 평가 없이 RAG 입력 레코드 구성만 확인 (RAGAS 미설치 시 유용)")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _parse_args(argv)
    summary = run_pipeline(
        dataset_path=args.dataset,
        csv_path=args.out_csv,
        json_path=args.out_json,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
