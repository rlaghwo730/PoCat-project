from sqlalchemy import text
from db import get_engine

engine = get_engine()

queries = {
    "external_reference_document 건수": """
        SELECT COUNT(*) FROM external_reference_document;
    """,
    "external_reference_chunk 건수": """
        SELECT COUNT(*) FROM external_reference_chunk;
    """,
    "외부 문서별 chunk 수": """
        SELECT
            d.external_doc_id,
            d.source_id,
            d.title,
            d.file_type,
            COUNT(c.external_chunk_id) AS chunk_count
        FROM external_reference_document d
        LEFT JOIN external_reference_chunk c
            ON d.external_doc_id = c.external_doc_id
        GROUP BY d.external_doc_id, d.source_id, d.title, d.file_type
        ORDER BY d.external_doc_id;
    """,
    "외부 chunk 샘플": """
        SELECT
            source_id,
            title,
            chunk_order,
            page_no,
            LEFT(chunk_text, 250) AS chunk_preview
        FROM external_reference_chunk
        ORDER BY source_id, chunk_order
        LIMIT 10;
    """,
}

with engine.connect() as conn:
    for title, query in queries.items():
        print("\n" + "=" * 80)
        print(f"[{title}]")
        rows = conn.execute(text(query)).fetchall()
        for row in rows:
            print(row)