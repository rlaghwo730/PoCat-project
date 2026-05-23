import sys
from sqlalchemy import text
from db import get_engine


DEFAULT_QUERIES = [
    "전액 보장",
    "허위 과장 광고",
    "보험금 지급",
    "손해사정",
    "전문보험계약자",
    "실손의료보험",
    "설명의무",
    "보험계약자 보호",
]


def search_registry(query, limit=10):
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
            LEFT(chunk_text, 500) AS preview
        FROM retrieval_chunk_registry
        WHERE
            chunk_text ILIKE :q
            OR document_title ILIKE :q
            OR article_title ILIKE :q
            OR source_id ILIKE :q
        ORDER BY
            CASE
                WHEN document_title ILIKE :q THEN 1
                WHEN article_title ILIKE :q THEN 2
                WHEN chunk_text ILIKE :q THEN 3
                ELSE 4
            END,
            source_table,
            source_id,
            chunk_order NULLS LAST
        LIMIT :limit;
    """)

    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "q": f"%{query}%",
                "limit": limit,
            },
        ).fetchall()

    return rows


def print_results(query, rows):
    print("\n" + "=" * 100)
    print(f"[검색어] {query}")
    print(f"[검색 결과] {len(rows)}건")

    if not rows:
        print("- 검색 결과 없음")
        return

    for idx, row in enumerate(rows, start=1):
        print("\n" + "-" * 100)
        print(f"[{idx}]")
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
        print(f"preview          : {row.preview}")


def main():
    if len(sys.argv) >= 2:
        queries = [" ".join(sys.argv[1:])]
    else:
        queries = DEFAULT_QUERIES

    for query in queries:
        rows = search_registry(query, limit=10)
        print_results(query, rows)


if __name__ == "__main__":
    main()