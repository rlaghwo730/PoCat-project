from sqlalchemy import text
from db import get_engine

engine = get_engine()

with engine.connect() as conn:
    result = conn.execute(text("SELECT version();"))
    print("[DB 연결 성공]")
    print(result.fetchone()[0])