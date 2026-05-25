from sqlalchemy import text
from db import get_engine

engine = get_engine()

queries = {
    "legal_document 전체 건수": """
        SELECT COUNT(*) FROM legal_document;
    """,
    "target_type별 건수": """
        SELECT target_type, COUNT(*)
        FROM legal_document
        GROUP BY target_type
        ORDER BY target_type;
    """,
    "상위 20개 문서": """
        SELECT
            document_id,
            source_id,
            source_name,
            official_name,
            target_type,
            law_id,
            mst,
            admrul_serial,
            admrul_id,
            effective_date
        FROM legal_document
        ORDER BY source_id
        LIMIT 20;
    """,
    "식별자 누락 문서": """
        SELECT
            source_id,
            source_name,
            official_name,
            target_type,
            law_id,
            mst,
            admrul_serial,
            admrul_id
        FROM legal_document
        WHERE
            (target_type = 'law' AND law_id IS NULL AND mst IS NULL)
            OR
            (target_type = 'admrul' AND admrul_serial IS NULL AND admrul_id IS NULL)
        ORDER BY source_id;
    """,
}

with engine.connect() as conn:
    for title, query in queries.items():
        print("\n" + "=" * 80)
        print(f"[{title}]")
        rows = conn.execute(text(query)).fetchall()
        for row in rows:
            print(row)