from sqlalchemy import text
from db import get_engine


engine = get_engine()


ACTIVE_QUERY = """
SELECT
    source_id,
    source_name,
    collection_channel,
    target_type
FROM legal_source_inventory
WHERE status = 'active'
  AND collection_channel IN ('law_api', 'admrul_api')
ORDER BY source_id;
"""


DOC_QUERY = """
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
ORDER BY source_id;
"""


def normalize(text_value):
    if text_value is None:
        return ""
    return str(text_value).replace(" ", "").replace("ㆍ", "·").strip()


def main():
    with engine.connect() as conn:
        active_rows = conn.execute(text(ACTIVE_QUERY)).mappings().all()
        doc_rows = conn.execute(text(DOC_QUERY)).mappings().all()

    active = {row["source_id"]: dict(row) for row in active_rows}
    docs = {row["source_id"]: dict(row) for row in doc_rows}

    missing = []
    suspicious = []

    for source_id, src in active.items():
        doc = docs.get(source_id)

        if doc is None:
            missing.append(src)
            continue

        src_name = normalize(src["source_name"])
        official_name = normalize(doc["official_name"])

        # 상법 제4편 보험은 official_name이 상법이면 정상 처리
        if src["source_name"] == "상법 제4편 보험" and official_name == normalize("상법"):
            continue

        # 원천명과 공식명이 서로 포함관계가 아니면 의심
        if src_name not in official_name and official_name not in src_name:
            suspicious.append(
                {
                    "source_id": source_id,
                    "source_name": src["source_name"],
                    "official_name": doc["official_name"],
                    "target_type": doc["target_type"],
                    "law_id": doc["law_id"],
                    "mst": doc["mst"],
                    "admrul_serial": doc["admrul_serial"],
                    "admrul_id": doc["admrul_id"],
                }
            )

    print("=" * 80)
    print("[기대 API 수집 대상]")
    print(f"- active API 대상: {len(active)}건")

    print("\n[현재 legal_document]")
    print(f"- 적재 문서: {len(docs)}건")

    print("\n[누락 문서]")
    print(f"- 누락: {len(missing)}건")
    for row in missing:
        print(
            row["source_id"],
            row["source_name"],
            row["collection_channel"],
            row["target_type"],
        )

    print("\n[오매칭 의심 문서]")
    print(f"- 의심: {len(suspicious)}건")
    for row in suspicious:
        print(
            row["source_id"],
            "| source:",
            row["source_name"],
            "| official:",
            row["official_name"],
            "| law_id:",
            row["law_id"],
            "| admrul_serial:",
            row["admrul_serial"],
        )


if __name__ == "__main__":
    main()