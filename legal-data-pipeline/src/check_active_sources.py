from sqlalchemy import text
from db import get_engine

engine = get_engine()

query = """
SELECT
    source_id,
    source_name,
    domain_group,
    collection_channel,
    target_type,
    load_status,
    status
FROM legal_source_inventory
WHERE status IN ('active', 'external_active')
ORDER BY source_id;
"""

summary_query = """
SELECT
    collection_channel,
    target_type,
    status,
    COUNT(*) AS cnt
FROM legal_source_inventory
GROUP BY collection_channel, target_type, status
ORDER BY collection_channel, target_type, status;
"""

with engine.connect() as conn:
    print("[수집 대상 요약]")
    rows = conn.execute(text(summary_query)).fetchall()
    for row in rows:
        print(row)

    print("\n[active / external_active 수집 대상 목록]")
    rows = conn.execute(text(query)).fetchall()
    for row in rows:
        print(row)