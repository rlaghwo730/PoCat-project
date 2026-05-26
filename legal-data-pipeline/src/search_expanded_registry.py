import sys
from sqlalchemy import text
from db import get_engine


def get_expansion_terms(query):
    engine = get_engine()

    sql = text("""
        SELECT
            user_expression,
            risk_type,
            expanded_keyword,
            priority
        FROM risk_query_expansion
        WHERE
            active_yn = 'Y'
            AND (
                user_expression = :query
                OR :query ILIKE '%' || user_expression || '%'
                OR user_expression ILIKE '%' || :query || '%'
            )
        ORDER BY priority, expanded_keyword;
    """)

    with engine.connect() as conn:
        rows = conn.execute(sql, {"query": query}).fetchall()

    terms = []

    # 원문 검색어도 항상 포함
    terms.append(
        {
            "term": query,
            "risk_type": "사용자 입력 원문",
            "priority": 0,
        }
    )

    for row in rows:
        terms.append(
            {
                "term": row.expanded_keyword,
                "risk_type": row.risk_type,
                "priority": row.priority,
            }
        )

    # 사용자가 공백 포함 표현을 입력했을 때 단어 단위도 보조 검색어로 포함
    for token in query.split():
        if len(token) >= 2:
            terms.append(
                {
                    "term": token,
                    "risk_type": "사용자 입력 토큰",
                    "priority": 4,
                }
            )

    # 중복 제거
    unique = {}
    for item in terms:
        if item["term"] not in unique:
            unique[item["term"]] = item

    return list(unique.values())


def load_registry():
    engine = get_engine()

    sql = text("""
        SELECT
            registry_id,
            source_table,
            source_id,
            vector_collection,
            document_title,
            chunk_type,
            article_no,
            article_title,
            page_no,
            chunk_order,
            chunk_text
        FROM retrieval_chunk_registry
        WHERE current_version_yn = 'Y';
    """)

    with engine.connect() as conn:
        return conn.execute(sql).fetchall()


def score_row(row, terms):
    score = 0
    matched_terms = []

    document_title = row.document_title or ""
    article_title = row.article_title or ""
    chunk_text = row.chunk_text or ""

    doc_lower = document_title.lower()
    article_lower = article_title.lower()
    text_lower = chunk_text.lower()

    for item in terms:
        term = item["term"]
        term_lower = term.lower()
        priority = item["priority"]

        weight_base = max(1, 6 - priority)

        matched = False

        if term_lower in doc_lower:
            score += 10 * weight_base
            matched = True

        if term_lower in article_lower:
            score += 8 * weight_base
            matched = True

        if term_lower in text_lower:
            score += 3 * weight_base
            matched = True

        if matched:
            matched_terms.append(term)

    # 외부 기준자료는 정책/가이드라인 근거성이 높으므로 약간 가산
    if row.source_table == "external_reference_chunk":
        score += 5

    # 제목이 있는 조문은 근거 제시 품질이 높으므로 약간 가산
    if row.article_title:
        score += 3

    return score, matched_terms


def search_expanded(query, limit=10):
    terms = get_expansion_terms(query)
    rows = load_registry()

    scored = []

    for row in rows:
        score, matched_terms = score_row(row, terms)

        if score > 0:
            scored.append(
                {
                    "score": score,
                    "matched_terms": matched_terms,
                    "row": row,
                }
            )

    scored.sort(key=lambda x: x["score"], reverse=True)

    return terms, scored[:limit]


def print_results(query, terms, results):
    print("\n" + "=" * 100)
    print(f"[사용자 검색어] {query}")

    print("\n[확장 검색어]")
    for item in terms:
        print(f"- {item['term']} | {item['risk_type']} | priority={item['priority']}")

    print("\n" + "=" * 100)
    print(f"[검색 결과] {len(results)}건")

    if not results:
        print("- 검색 결과 없음")
        return

    for idx, item in enumerate(results, start=1):
        row = item["row"]

        print("\n" + "-" * 100)
        print(f"[{idx}] score={item['score']}")
        print(f"matched_terms    : {', '.join(item['matched_terms'])}")
        print(f"registry_id      : {row.registry_id}")
        print(f"source_table     : {row.source_table}")
        print(f"source_id        : {row.source_id}")
        print(f"vector_collection: {row.vector_collection}")
        print(f"document_title   : {row.document_title}")
        print(f"chunk_type       : {row.chunk_type}")
        print(f"article_no       : {row.article_no}")
        print(f"article_title    : {row.article_title}")
        print(f"page_no          : {row.page_no}")
        print(f"chunk_order      : {row.chunk_order}")
        print(f"preview          : {(row.chunk_text or '')[:700]}")


def main():
    if len(sys.argv) < 2:
        test_queries = [
            "전액 보장",
            "허위 과장 광고",
            "실손의료보험",
            "손해사정",
        ]
    else:
        test_queries = [" ".join(sys.argv[1:])]

    for query in test_queries:
        terms, results = search_expanded(query, limit=10)
        print_results(query, terms, results)


if __name__ == "__main__":
    main()