from sqlalchemy import text
from db import get_engine

engine = get_engine()

queries = {
    "전체 건수": """
        SELECT COUNT(*) AS cnt
        FROM legal_source_inventory;
    """,
    "load_status별 건수": """
        SELECT load_status, COUNT(*) AS cnt
        FROM legal_source_inventory
        GROUP BY load_status
        ORDER BY load_status;
    """,
    "collection_channel별 건수": """
        SELECT collection_channel, COUNT(*) AS cnt
        FROM legal_source_inventory
        GROUP BY collection_channel
        ORDER BY collection_channel;
    """,
    "상위 15개 대상": """
        SELECT
            source_id,
            source_name,
            source_scope,
            collection_channel,
            target_type,
            load_status,
            status
        FROM legal_source_inventory
        ORDER BY source_id
        LIMIT 15;
    """,
}

with engine.connect() as conn:
    for title, query in queries.items():
        print("\n" + "=" * 80)
        print(f"[{title}]")
        rows = conn.execute(text(query)).fetchall()

        for row in rows:
            print(row)