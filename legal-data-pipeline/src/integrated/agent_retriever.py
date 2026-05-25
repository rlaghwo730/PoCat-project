import os
import sys
import json
from typing import Dict, List, Optional, Any

import psycopg2
from sentence_transformers import SentenceTransformer


# =========================================================
# Team-shared read-only DB default config
# ---------------------------------------------------------
# 팀원은 .env 없이도 바로 실행할 수 있다.
# 단, 이 값은 반드시 read-only 계정(agent_reader)이어야 한다.
# 관리자 계정(neondb_owner)은 절대 코드에 넣지 않는다.
# =========================================================

DB_HOST = os.getenv(
    "POSTGRES_HOST",
    "ep-red-smoke-aol741au.c-2.ap-southeast-1.aws.neon.tech",
)
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "neondb")
DB_USER = os.getenv("POSTGRES_USER", "agent_reader")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "AgentRead_2026_Strong!")
DB_SSLMODE = os.getenv("POSTGRES_SSLMODE", "require")

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

DEFAULT_TOP_K = 20


QUERY_TYPE_ALIASES = {
    "misleading_expression": "misleading_expression",
    "오인표현": "misleading_expression",
    "전액보장": "misleading_expression",
    "coverage_limit": "coverage_limit",
    "보장한도": "coverage_limit",
    "자기부담금": "coverage_limit",
    "exclusion_clause": "exclusion_clause",
    "면책": "exclusion_clause",
    "보상하지않는사항": "exclusion_clause",
    "explanation_duty": "explanation_duty",
    "설명의무": "explanation_duty",
    "general": "general",
}


DOMAIN_PRIORITY = {
    "misleading_expression": {
        "external_reference": 0.08,
        "legal": 0.07,
        "insurance_cited_law": 0.05,
        "insurance_policy": 0.03,
        "legal_attachment": 0.01,
    },
    "coverage_limit": {
        "insurance_policy": 0.08,
        "insurance_cited_law": 0.05,
        "legal": 0.03,
        "legal_attachment": 0.02,
        "external_reference": 0.01,
    },
    "exclusion_clause": {
        "insurance_policy": 0.08,
        "insurance_cited_law": 0.05,
        "legal": 0.04,
        "legal_attachment": 0.02,
        "external_reference": 0.01,
    },
    "explanation_duty": {
        "legal": 0.08,
        "insurance_cited_law": 0.06,
        "external_reference": 0.04,
        "insurance_policy": 0.02,
        "legal_attachment": 0.01,
    },
    "general": {
        "insurance_policy": 0.04,
        "legal": 0.04,
        "insurance_cited_law": 0.03,
        "external_reference": 0.02,
        "legal_attachment": 0.01,
    },
}


DOMAIN_GROUPS = {
    "policy_evidence": {"insurance_policy"},
    "legal_evidence": {"legal", "insurance_cited_law", "legal_attachment"},
    "external_evidence": {"external_reference"},
}


_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        sslmode=DB_SSLMODE,
    )


def vector_to_pgvector(values):
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def normalize_query_type(query_type: Optional[str]) -> str:
    if not query_type:
        return "general"

    key = query_type.strip()
    return QUERY_TYPE_ALIASES.get(key, key if key in DOMAIN_PRIORITY else "general")


def infer_query_type(query: str) -> str:
    q = query.replace(" ", "")

    if any(keyword in q for keyword in ["전액보장", "100%보장", "모두보장", "오인", "과장", "광고"]):
        return "misleading_expression"

    if any(keyword in q for keyword in ["비급여", "자기부담금", "공제금액", "보장한도", "가입금액"]):
        return "coverage_limit"

    if any(keyword in q for keyword in ["보상하지않", "면책", "지급제한", "제외"]):
        return "exclusion_clause"

    if any(keyword in q for keyword in ["설명의무", "상품설명서", "중요사항", "설명서"]):
        return "explanation_duty"

    return "general"


def fetch_vector_candidates(query: str, top_k: int) -> List[Dict[str, Any]]:
    model = get_model()
    query_embedding = model.encode([query], normalize_embeddings=True)[0]
    vector_text = vector_to_pgvector(query_embedding)

    sql = """
        SELECT
            r.unified_chunk_id,
            r.source_domain,
            r.source_name,
            r.company_name,
            r.product_name,
            r.document_name,
            r.document_type,
            r.section,
            r.article_no,
            r.title,
            r.citation_label,
            r.source_url,
            r.content,
            r.metadata_json,
            1 - (e.embedding <=> %s::vector) AS similarity
        FROM unified_chunk_embedding e
        JOIN unified_retrieval_chunk r
          ON e.unified_chunk_id = r.unified_chunk_id
        WHERE r.is_active = TRUE
          AND e.embedding_model = %s
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s;
    """

    conn = connect()

    try:
        with conn.cursor() as cur:
            cur.execute(sql, (vector_text, EMBEDDING_MODEL, vector_text, top_k))
            rows = cur.fetchall()

        results = []

        for row in rows:
            (
                unified_chunk_id,
                source_domain,
                source_name,
                company_name,
                product_name,
                document_name,
                document_type,
                section,
                article_no,
                title,
                citation_label,
                source_url,
                content,
                metadata_json,
                similarity,
            ) = row

            content = content or ""

            results.append(
                {
                    "unified_chunk_id": unified_chunk_id,
                    "source_domain": source_domain,
                    "source_name": source_name,
                    "company_name": company_name,
                    "product_name": product_name,
                    "document_name": document_name,
                    "document_type": document_type,
                    "section": section,
                    "article_no": article_no,
                    "title": title,
                    "citation_label": citation_label,
                    "source_url": source_url,
                    "content": content,
                    "content_preview": content[:300],
                    "metadata": metadata_json,
                    "similarity": float(similarity),
                }
            )

        return results

    finally:
        conn.close()


def rerank_candidates(
    candidates: List[Dict[str, Any]],
    query_type: str,
) -> List[Dict[str, Any]]:
    priority = DOMAIN_PRIORITY.get(query_type, DOMAIN_PRIORITY["general"])

    reranked = []

    for item in candidates:
        source_domain = item.get("source_domain")
        base_similarity = item.get("similarity", 0.0)
        domain_bonus = priority.get(source_domain, 0.0)
        final_score = base_similarity + domain_bonus

        item = dict(item)
        item["domain_bonus"] = domain_bonus
        item["final_score"] = final_score
        reranked.append(item)

    return sorted(reranked, key=lambda x: x["final_score"], reverse=True)


def simplify_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source_domain": item.get("source_domain"),
        "citation_label": item.get("citation_label"),
        "source_url": item.get("source_url"),
        "document_name": item.get("document_name"),
        "document_type": item.get("document_type"),
        "article_no": item.get("article_no"),
        "title": item.get("title"),
        "content": item.get("content"),
        "content_preview": item.get("content_preview"),
        "similarity": round(item.get("similarity", 0.0), 4),
        "domain_bonus": round(item.get("domain_bonus", 0.0), 4),
        "final_score": round(item.get("final_score", 0.0), 4),
    }


def split_evidence(
    reranked: List[Dict[str, Any]],
    per_group_limit: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    output = {
        "policy_evidence": [],
        "legal_evidence": [],
        "external_evidence": [],
        "all_evidence": [],
    }

    for item in reranked:
        source_domain = item.get("source_domain")
        simplified = simplify_item(item)

        output["all_evidence"].append(simplified)

        for group_name, domains in DOMAIN_GROUPS.items():
            if source_domain in domains and len(output[group_name]) < per_group_limit:
                output[group_name].append(simplified)

    return output


def search_for_review(
    query: str,
    query_type: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K,
    per_group_limit: int = 5,
) -> Dict[str, Any]:
    if not query or not query.strip():
        raise ValueError("query must not be empty")

    query = query.strip()

    normalized_query_type = normalize_query_type(query_type)
    if normalized_query_type == "general":
        normalized_query_type = infer_query_type(query)

    candidates = fetch_vector_candidates(query=query, top_k=top_k)
    reranked = rerank_candidates(candidates, normalized_query_type)
    grouped = split_evidence(reranked, per_group_limit=per_group_limit)

    return {
        "query": query,
        "query_type": normalized_query_type,
        "embedding_model": EMBEDDING_MODEL,
        "top_k": top_k,
        "policy_evidence": grouped["policy_evidence"],
        "legal_evidence": grouped["legal_evidence"],
        "external_evidence": grouped["external_evidence"],
        "all_evidence": grouped["all_evidence"],
    }


def print_result(result: Dict[str, Any]):
    print("=" * 100)
    print("QUERY:", result["query"])
    print("QUERY TYPE:", result["query_type"])
    print("EMBEDDING MODEL:", result["embedding_model"])
    print("=" * 100)

    for group_name in ["policy_evidence", "legal_evidence", "external_evidence"]:
        print("\n[{}]".format(group_name))
        items = result.get(group_name, [])

        if not items:
            print("  - no results")
            continue

        for idx, item in enumerate(items, start=1):
            print("-" * 100)
            print("Rank:", idx)
            print("Domain:", item["source_domain"])
            print("Similarity:", item["similarity"])
            print("Final Score:", item["final_score"])
            print("Citation:", item["citation_label"])
            print("URL:", item["source_url"])
            print("Preview:", item["content_preview"])


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]).strip()

    if not query:
        query = "전액 보장이라는 표현은 소비자에게 오인 가능성이 있는지 검토"

    result = search_for_review(query=query)
    print_result(result)