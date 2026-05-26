from sqlalchemy import text
from db import get_engine


def main():
    engine = get_engine()

    queries = {
        "review_finding 건수": """
            SELECT COUNT(*) FROM review_finding;
        """,
        "입력문구별 finding 수": """
            SELECT
                input_text,
                detected_expression,
                risk_type,
                COUNT(*) AS finding_count
            FROM review_finding
            GROUP BY input_text, detected_expression, risk_type
            ORDER BY input_text, detected_expression;
        """,
        "최근 finding 샘플": """
            SELECT
                input_text,
                detected_expression,
                risk_level,
                document_title,
                article_no,
                article_title,
                evidence_score,
                LEFT(evidence_text, 300) AS preview
            FROM review_finding
            ORDER BY created_at DESC, evidence_rank
            LIMIT 10;
        """,
    }

    with engine.connect() as conn:
        for title, query in queries.items():
            print("\n" + "=" * 100)
            print(f"[{title}]")
            rows = conn.execute(text(query)).fetchall()

            if not rows:
                print("- 결과 없음")
                continue

            for row in rows:
                print(row)


if __name__ == "__main__":
    main()