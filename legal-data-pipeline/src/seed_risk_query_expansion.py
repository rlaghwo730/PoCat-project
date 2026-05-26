from sqlalchemy import text
from db import get_engine


SEED_ROWS = [
    # 전액 보장 계열
    ("전액 보장", "과장·오인 가능 표현", "보장내용", 1),
    ("전액 보장", "과장·오인 가능 표현", "보험금 지급사유", 1),
    ("전액 보장", "과장·오인 가능 표현", "보험금 지급제한", 1),
    ("전액 보장", "과장·오인 가능 표현", "지급제한 조건", 1),
    ("전액 보장", "과장·오인 가능 표현", "약관상 보장", 2),
    ("전액 보장", "과장·오인 가능 표현", "설명의무", 2),
    ("전액 보장", "과장·오인 가능 표현", "중요사항", 2),
    ("전액 보장", "과장·오인 가능 표현", "소비자 오인", 2),
    ("전액 보장", "과장·오인 가능 표현", "불완전판매", 3),
    ("전액 보장", "과장·오인 가능 표현", "상품설명서", 3),

    # 100% 보장 계열
    ("100% 보장", "과장·오인 가능 표현", "보장내용", 1),
    ("100% 보장", "과장·오인 가능 표현", "보험금 지급사유", 1),
    ("100% 보장", "과장·오인 가능 표현", "보험금 지급제한", 1),
    ("100% 보장", "과장·오인 가능 표현", "설명의무", 2),
    ("100% 보장", "과장·오인 가능 표현", "소비자 오인", 2),

    # 허위 광고 계열
    ("허위 광고", "광고규제 위반 가능 표현", "금융광고", 1),
    ("허위 광고", "광고규제 위반 가능 표현", "광고규제", 1),
    ("허위 광고", "광고규제 위반 가능 표현", "광고의 내용 및 방법", 1),
    ("허위 광고", "광고규제 위반 가능 표현", "표시광고법", 1),
    ("허위 광고", "광고규제 위반 가능 표현", "부당한 표시", 2),
    ("허위 광고", "광고규제 위반 가능 표현", "과장광고", 2),
    ("허위 광고", "광고규제 위반 가능 표현", "소비자의 오인", 2),
    ("허위 광고", "광고규제 위반 가능 표현", "오인", 3),

    # 허위 과장 광고 계열
    ("허위 과장 광고", "광고규제 위반 가능 표현", "금융광고", 1),
    ("허위 과장 광고", "광고규제 위반 가능 표현", "광고규제", 1),
    ("허위 과장 광고", "광고규제 위반 가능 표현", "광고의 내용 및 방법", 1),
    ("허위 과장 광고", "광고규제 위반 가능 표현", "표시광고법", 1),
    ("허위 과장 광고", "광고규제 위반 가능 표현", "허위", 2),
    ("허위 과장 광고", "광고규제 위반 가능 표현", "과장광고", 2),
    ("허위 과장 광고", "광고규제 위반 가능 표현", "소비자의 오인", 2),
    ("허위 과장 광고", "광고규제 위반 가능 표현", "오인", 3),

    # 실손의료보험 계열
    ("실손의료보험", "실손보험 관련 근거", "실손의료보험", 1),
    ("실손의료보험", "실손보험 관련 근거", "실손의료보험계약", 1),
    ("실손의료보험", "실손보험 관련 근거", "보험금 청구", 2),
    ("실손의료보험", "실손보험 관련 근거", "중복가입", 2),
    ("실손의료보험", "실손보험 관련 근거", "제3보험", 3),

    # 손해사정 계열
    ("손해사정", "손해사정 관련 근거", "손해사정", 1),
    ("손해사정", "손해사정 관련 근거", "손해사정사", 1),
    ("손해사정", "손해사정 관련 근거", "손해사정서", 1),
    ("손해사정", "손해사정 관련 근거", "보험금 지급 금액", 2),
    ("손해사정", "손해사정 관련 근거", "보정요청", 2),
]


def main():
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text("""
            DROP TABLE IF EXISTS risk_query_expansion;

            CREATE TABLE risk_query_expansion (
                expansion_id SERIAL PRIMARY KEY,
                user_expression TEXT NOT NULL,
                risk_type TEXT NOT NULL,
                expanded_keyword TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 3,
                active_yn TEXT NOT NULL DEFAULT 'Y',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_risk_query_expression
                ON risk_query_expansion(user_expression);

            CREATE INDEX IF NOT EXISTS idx_risk_query_keyword
                ON risk_query_expansion(expanded_keyword);
        """))

        for row in SEED_ROWS:
            conn.execute(
                text("""
                    INSERT INTO risk_query_expansion (
                        user_expression,
                        risk_type,
                        expanded_keyword,
                        priority
                    )
                    VALUES (
                        :user_expression,
                        :risk_type,
                        :expanded_keyword,
                        :priority
                    );
                """),
                {
                    "user_expression": row[0],
                    "risk_type": row[1],
                    "expanded_keyword": row[2],
                    "priority": row[3],
                },
            )

    print("[완료] risk_query_expansion 테이블 생성 및 seed 적재")
    print(f"- seed row 수: {len(SEED_ROWS)}")


if __name__ == "__main__":
    main()