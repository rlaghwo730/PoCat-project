import sys
import hashlib
from datetime import datetime

from sqlalchemy import text

from db import get_engine
from search_expanded_registry import get_expansion_terms, load_registry, score_row


DEFAULT_INPUT_TEXT = "비급여 치료비는 전액 보장합니다."


def make_hash(value):
    if value is None:
        value = ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def detect_user_expression(input_text):
    """
    MVP용 위험표현 탐지.
    risk_query_expansion.user_expression 중 입력문에 포함된 표현을 찾는다.
    없으면 입력문 전체를 검색어로 사용한다.
    """
    engine = get_engine()

    sql = text("""
    SELECT
        user_expression,
        risk_type,
        MAX(LENGTH(user_expression)) AS expr_len
    FROM risk_query_expansion
    WHERE active_yn = 'Y'
    GROUP BY user_expression, risk_type
    ORDER BY expr_len DESC;
""")

    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()

    detected = []

    for row in rows:
        expr = row.user_expression
        if expr and expr in input_text:
            detected.append(
                {
                    "user_expression": expr,
                    "risk_type": row.risk_type,
                }
            )

    if detected:
        return detected

    return [
        {
            "user_expression": input_text,
            "risk_type": "미분류 위험표현",
        }
    ]


def search_evidence(query, limit=5):
    terms = get_expansion_terms(query)
    rows = load_registry()

    scored = []

    for row in rows:
        score, matched_terms = score_row(row, terms)

        if score > 0:
            scored.append(
                {
                    "score": score,
                    "matched_terms": matched_terms,
                    "row": row,
                }
            )

    scored.sort(key=lambda x: x["score"], reverse=True)

    return terms, scored[:limit]


def ensure_review_finding_table():
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS review_finding (
                finding_id TEXT PRIMARY KEY,
                input_text TEXT NOT NULL,
                detected_expression TEXT,
                risk_type TEXT,
                risk_level TEXT,
                finding_summary TEXT,
                recommendation TEXT,
                evidence_rank INTEGER,
                evidence_score INTEGER,
                matched_terms TEXT,
                registry_id TEXT,
                source_table TEXT,
                source_id TEXT,
                document_title TEXT,
                chunk_type TEXT,
                article_no TEXT,
                article_title TEXT,
                page_no INTEGER,
                chunk_order INTEGER,
                evidence_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_review_finding_expression
                ON review_finding(detected_expression);

            CREATE INDEX IF NOT EXISTS idx_review_finding_source_id
                ON review_finding(source_id);

            CREATE INDEX IF NOT EXISTS idx_review_finding_registry_id
                ON review_finding(registry_id);
        """))

    print("[확인] review_finding 테이블 준비 완료")


def build_finding_summary(input_text, detected_expression, risk_type):
    if "전액 보장" in detected_expression or "100% 보장" in detected_expression:
        return (
            "입력 문구에 보장범위를 절대적으로 표현하는 문구가 포함되어 있어, "
            "실제 약관상 보장범위·면책사항·지급제한 조건과 다르게 소비자가 이해할 가능성이 있습니다."
        )

    if "허위" in detected_expression or "광고" in detected_expression:
        return (
            "입력 문구가 금융상품 광고 또는 설명자료에서 소비자 오인 가능성을 유발할 수 있는 표현인지 "
            "검토가 필요합니다."
        )

    if "손해사정" in detected_expression:
        return (
            "입력 문구가 손해사정 절차, 손해사정서 작성, 보험금 지급금액 조정과 관련된 기준에 "
            "부합하는지 검토가 필요합니다."
        )

    return (
        "입력 문구가 관련 법령·감독규정·외부 기준자료와 충돌하거나 소비자 오인을 유발할 가능성이 있는지 "
        "검토가 필요합니다."
    )


def build_recommendation(detected_expression):
    if "전액 보장" in detected_expression or "100% 보장" in detected_expression:
        return (
            "문구를 단정적으로 사용하지 말고, 보장 대상·보장 제외사항·면책사항·자기부담금·지급제한 조건을 "
            "약관 및 상품설명서 기준에 맞춰 함께 명시하는 방식으로 수정 검토가 필요합니다."
        )

    if "허위" in detected_expression or "광고" in detected_expression:
        return (
            "광고성 표현은 금융광고규제 가이드라인, 표시광고 관련 기준, 소비자 오인 가능성을 기준으로 "
            "표현의 사실성·근거자료·제한조건 표시 여부를 함께 점검해야 합니다."
        )

    if "손해사정" in detected_expression:
        return (
            "손해사정 결과, 보정요청, 보험금 지급금액 조정과 관련된 표현은 관련 절차와 근거를 명확히 "
            "기재하고, 임의 변경 또는 부당한 영향력 행사로 해석될 수 있는 표현을 피해야 합니다."
        )

    return (
        "관련 근거 조문을 확인한 뒤, 문구의 적용범위·제한조건·소비자 설명 필요사항을 명확히 보완하는 "
        "방향으로 검토해야 합니다."
    )


def infer_risk_level(score):
    if score >= 120:
        return "높음"
    if score >= 60:
        return "중간"
    return "검토 필요"


def clear_previous_findings(input_text):
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM review_finding WHERE input_text = :input_text;"),
            {"input_text": input_text},
        )


def insert_findings(input_text, detected, results):
    engine = get_engine()
    now = datetime.now()

    detected_expression = detected["user_expression"]
    risk_type = detected["risk_type"]

    summary = build_finding_summary(input_text, detected_expression, risk_type)
    recommendation = build_recommendation(detected_expression)

    records = []

    for idx, item in enumerate(results, start=1):
        row = item["row"]
        matched_terms = ", ".join(item["matched_terms"])
        score = int(item["score"])

        finding_id = make_hash(
            f"{input_text}|{detected_expression}|{row.registry_id}|{idx}"
        )[:32]

        page_no = row.page_no
        if page_no is not None:
            try:
                page_no = int(page_no)
            except Exception:
                page_no = None

        chunk_order = row.chunk_order
        if chunk_order is not None:
            try:
                chunk_order = int(chunk_order)
            except Exception:
                chunk_order = None

        records.append(
            {
                "finding_id": finding_id,
                "input_text": input_text,
                "detected_expression": detected_expression,
                "risk_type": risk_type,
                "risk_level": infer_risk_level(score),
                "finding_summary": summary,
                "recommendation": recommendation,
                "evidence_rank": idx,
                "evidence_score": score,
                "matched_terms": matched_terms,
                "registry_id": row.registry_id,
                "source_table": row.source_table,
                "source_id": row.source_id,
                "document_title": row.document_title,
                "chunk_type": row.chunk_type,
                "article_no": row.article_no,
                "article_title": row.article_title,
                "page_no": page_no,
                "chunk_order": chunk_order,
                "evidence_text": row.chunk_text,
                "created_at": now,
            }
        )

    sql = text("""
        INSERT INTO review_finding (
            finding_id,
            input_text,
            detected_expression,
            risk_type,
            risk_level,
            finding_summary,
            recommendation,
            evidence_rank,
            evidence_score,
            matched_terms,
            registry_id,
            source_table,
            source_id,
            document_title,
            chunk_type,
            article_no,
            article_title,
            page_no,
            chunk_order,
            evidence_text,
            created_at
        )
        VALUES (
            :finding_id,
            :input_text,
            :detected_expression,
            :risk_type,
            :risk_level,
            :finding_summary,
            :recommendation,
            :evidence_rank,
            :evidence_score,
            :matched_terms,
            :registry_id,
            :source_table,
            :source_id,
            :document_title,
            :chunk_type,
            :article_no,
            :article_title,
            :page_no,
            :chunk_order,
            :evidence_text,
            :created_at
        )
        ON CONFLICT (finding_id)
        DO UPDATE SET
            risk_level = EXCLUDED.risk_level,
            finding_summary = EXCLUDED.finding_summary,
            recommendation = EXCLUDED.recommendation,
            evidence_score = EXCLUDED.evidence_score,
            matched_terms = EXCLUDED.matched_terms,
            evidence_text = EXCLUDED.evidence_text,
            created_at = EXCLUDED.created_at;
    """)

    with engine.begin() as conn:
        for record in records:
            conn.execute(sql, record)

    return records


def print_report(input_text, detected, terms, records):
    print("\n" + "=" * 100)
    print("[검토 입력 문구]")
    print(input_text)

    print("\n[탐지된 위험표현]")
    print(f"- 표현: {detected['user_expression']}")
    print(f"- 위험유형: {detected['risk_type']}")

    print("\n[확장 검색어]")
    for item in terms:
        print(f"- {item['term']} | {item['risk_type']} | priority={item['priority']}")

    if not records:
        print("\n[검토 결과]")
        print("- 관련 근거 후보를 찾지 못했습니다.")
        return

    print("\n[검토 요약]")
    print(f"- 위험수준: {records[0]['risk_level']}")
    print(f"- 검토의견: {records[0]['finding_summary']}")
    print(f"- 권고사항: {records[0]['recommendation']}")

    print("\n[근거 후보 Top N]")
    for record in records:
        print("\n" + "-" * 100)
        print(f"[근거 {record['evidence_rank']}] score={record['evidence_score']}")
        print(f"문서명        : {record['document_title']}")
        print(f"source_id     : {record['source_id']}")
        print(f"source_table  : {record['source_table']}")
        print(f"조문번호      : {record['article_no']}")
        print(f"조문제목      : {record['article_title']}")
        print(f"page_no       : {record['page_no']}")
        print(f"matched_terms : {record['matched_terms']}")
        print(f"근거 미리보기 : {record['evidence_text'][:500]}")

    print("\n" + "=" * 100)
    print(f"[DB 저장 완료] review_finding {len(records)}건")


def main():
    ensure_review_finding_table()

    if len(sys.argv) >= 2:
        input_text = " ".join(sys.argv[1:])
    else:
        input_text = DEFAULT_INPUT_TEXT

    clear_previous_findings(input_text)

    detected_list = detect_user_expression(input_text)

    total_saved = 0

    for detected in detected_list:
        query = detected["user_expression"]
        terms, results = search_evidence(query, limit=5)

        records = insert_findings(input_text, detected, results)
        total_saved += len(records)

        print_report(input_text, detected, terms, records)

    print("\n" + "=" * 100)
    print(f"[전체 완료] 탐지 표현 {len(detected_list)}개, 저장 finding {total_saved}건")


if __name__ == "__main__":
    main()