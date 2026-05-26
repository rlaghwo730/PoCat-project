from sqlalchemy import text
from db import get_engine

engine = get_engine()

query = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
"""

with engine.connect() as conn:
    rows = conn.execute(text(query)).fetchall()

print("[현재 public schema 테이블 목록]")
for row in rows:
    print("-", row[0])