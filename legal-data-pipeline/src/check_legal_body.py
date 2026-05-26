from sqlalchemy import text
from db import get_engine

engine = get_engine()

queries = {
    "legal_document 건수": """
        SELECT COUNT(*) FROM legal_document;
    """,
    "legal_article 건수": """
        SELECT COUNT(*) FROM legal_article;
    """,
    "legal_attachment 건수": """
        SELECT COUNT(*) FROM legal_attachment;
    """,
    "문서별 조문 수 상위 20개": """
        SELECT
            d.source_id,
            d.source_name,
            d.target_type,
            COUNT(a.article_id) AS article_count
        FROM legal_document d
        LEFT JOIN legal_article a
            ON d.document_id = a.document_id
        GROUP BY d.source_id, d.source_name, d.target_type
        ORDER BY article_count DESC
        LIMIT 20;
    """,
    "조문이 0건인 문서": """
        SELECT
            d.source_id,
            d.source_name,
            d.target_type
        FROM legal_document d
        LEFT JOIN legal_article a
            ON d.document_id = a.document_id
        GROUP BY d.source_id, d.source_name, d.target_type
        HAVING COUNT(a.article_id) = 0
        ORDER BY d.source_id;
    """,
    "첨부/별표 보유 문서": """
        SELECT
            d.source_id,
            d.source_name,
            COUNT(att.attachment_id) AS attachment_count
        FROM legal_document d
        JOIN legal_attachment att
            ON d.document_id = att.document_id
        GROUP BY d.source_id, d.source_name
        ORDER BY attachment_count DESC;
    """,
    "조문 샘플": """
        SELECT
            source_name,
            article_no,
            article_title,
            LEFT(article_text, 200) AS article_preview
        FROM legal_article
        ORDER BY source_id, article_order
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