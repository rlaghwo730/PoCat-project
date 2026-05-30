import os
import sys
from pathlib import Path

from langchain_core.tools import tool

# PoCat-project 루트: backend/src/tools/db_tool.py 기준 4단계 상위
_ROOT = Path(__file__).parent.parent.parent.parent

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@tool
def search_legal_regulations(keyword: str) -> str:
    """PostgreSQL DB에서 보험 관련 법률/규제 조항을 조회합니다."""
    db_url = os.getenv("DB_API_URL")
    if not db_url:
        return "DB 미연결 — MOCK 모드: 법률 데이터를 조회할 수 없습니다."
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT citation_label, title, LEFT(content, 400)
            FROM unified_retrieval_chunk
            WHERE is_active = TRUE
              AND source_domain IN ('legal', 'insurance_cited_law')
              AND (content ILIKE %s OR content ILIKE '%%실손의료보험%%')
            ORDER BY source_domain
            LIMIT 5;
            """,
            (f"%{keyword[:20]}%",),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if not rows:
            return "관련 법률 조항을 찾을 수 없습니다."
        return "\n\n".join(f"[{r[0]}] {r[1]}\n{r[2]}" for r in rows)
    except Exception as e:
        return f"DB 조회 실패: {e}"
