from sqlalchemy import text
from db import get_engine

engine = get_engine()

with engine.begin() as conn:
    conn.execute(text("DELETE FROM legal_article;"))
    conn.execute(text("DELETE FROM legal_attachment;"))
    conn.execute(text("DELETE FROM legal_document;"))

print("[초기화 완료] legal_document / legal_article / legal_attachment")