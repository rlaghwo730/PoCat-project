import hashlib
from datetime import datetime

import pandas as pd
from sqlalchemy import text

from db import get_engine


def make_hash(value):
    if value is None:
        value = ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def clean_text(value):
    if value is None:
        return ""

    value = str(value)
    value = value.replace("\x00", " ")
    value = " ".join(value.split())
    return value.strip()


def first_existing_column(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    return None


def safe_get(row, col, default=None):
    if col is None:
        return default
    value = row.get(col, default)
    if pd.isna(value):
        return default
    return value


def recreate_registry_table(engine):
    sql = """
    DROP TABLE IF EXISTS retrieval_chunk_registry;

    CREATE TABLE retrieval_chunk_registry (
        registry_id TEXT PRIMARY KEY,
        source_table TEXT NOT NULL,
        source_pk TEXT,
        source_id TEXT,
        source_category TEXT,
        provider TEXT,
        document_title TEXT,
        chunk_type TEXT,
        article_no TEXT,
        article_title TEXT,
        page_no INTEGER,
        chunk_order INTEGER,
        chunk_text TEXT NOT NULL,
        chunk_hash TEXT NOT NULL,
        vector_collection TEXT NOT NULL,
        embedding_status TEXT NOT NULL DEFAULT 'pending',
        current_version_yn TEXT NOT NULL DEFAULT 'Y',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_retrieval_registry_source_id
        ON retrieval_chunk_registry(source_id);

    CREATE INDEX IF NOT EXISTS idx_retrieval_registry_vector_collection
        ON retrieval_chunk_registry(vector_collection);

    CREATE INDEX IF NOT EXISTS idx_retrieval_registry_embedding_status
        ON retrieval_chunk_registry(embedding_status);

    CREATE INDEX IF NOT EXISTS idx_retrieval_registry_chunk_hash
        ON retrieval_chunk_registry(chunk_hash);
    """

    with engine.begin() as conn:
        conn.execute(text(sql))

    print("[테이블 재생성 완료] retrieval_chunk_registry")


def build_from_legal_article(engine):
    df = pd.read_sql("SELECT * FROM legal_article;", engine)

    if df.empty:
        return []

    print(f"[legal_article 로드] {len(df)}건")
    print(f"- columns: {list(df.columns)}")

    pk_col = first_existing_column(df, ["article_id", "legal_article_id", "id"])
    source_id_col = first_existing_column(df, ["source_id"])
    category_col = first_existing_column(df, ["source_category", "source_type", "document_type"])
    provider_col = first_existing_column(df, ["provider"])
    title_col = first_existing_column(
    df,
    ["official_name", "source_name", "title", "document_title", "law_name", "admrul_name"]
)
    article_no_col = first_existing_column(df, ["article_no", "article_number", "조문번호"])
    article_title_col = first_existing_column(df, ["article_title", "조문제목"])
    text_col = first_existing_column(df, ["article_text", "article_content", "조문내용", "text", "content"])

    if text_col is None:
        raise ValueError("legal_article에서 조문 본문 컬럼을 찾지 못했습니다.")

    records = []
    now = datetime.now()

    for idx, row in df.iterrows():
        chunk_text = clean_text(safe_get(row, text_col, ""))

        if len(chunk_text) < 20:
            continue

        source_id = safe_get(row, source_id_col, "")
        article_no = safe_get(row, article_no_col, "")
        source_pk = safe_get(row, pk_col, f"legal_article_{idx + 1}")

        registry_id = f"REG_LEGAL_ARTICLE_{idx + 1:06d}"

        records.append(
            {
                "registry_id": registry_id,
                "source_table": "legal_article",
                "source_pk": str(source_pk),
                "source_id": source_id,
                "source_category": safe_get(row, category_col, "legal"),
                "provider": safe_get(row, provider_col, "국가법령정보센터"),
                "document_title": safe_get(row, title_col, None),
                "chunk_type": "legal_article",
                "article_no": str(article_no) if article_no is not None else None,
                "article_title": safe_get(row, article_title_col, None),
                "page_no": None,
                "chunk_order": None,
                "chunk_text": chunk_text,
                "chunk_hash": make_hash(chunk_text),
                "vector_collection": "law_regulation_vectors",
                "embedding_status": "pending",
                "current_version_yn": "Y",
                "created_at": now,
            }
        )

    return records


def build_from_legal_attachment(engine):
    df = pd.read_sql("SELECT * FROM legal_attachment;", engine)

    if df.empty:
        return []

    print(f"[legal_attachment 로드] {len(df)}건")
    print(f"- columns: {list(df.columns)}")

    pk_col = first_existing_column(df, ["attachment_id", "legal_attachment_id", "id"])
    source_id_col = first_existing_column(df, ["source_id"])
    category_col = first_existing_column(df, ["source_category", "source_type", "document_type"])
    provider_col = first_existing_column(df, ["provider"])
    title_col = first_existing_column(df, ["title", "document_title", "law_name", "admrul_name"])
    attachment_title_col = first_existing_column(df, ["attachment_title", "별표제목", "appendix_title"])
    text_col = first_existing_column(
        df,
        [
            "attachment_text",
            "content_text",
            "attachment_content",
            "별표내용",
            "raw_content",
            "text",
            "content",
        ],
    )

    records = []
    now = datetime.now()

    for idx, row in df.iterrows():
        source_id = safe_get(row, source_id_col, "")
        source_pk = safe_get(row, pk_col, f"legal_attachment_{idx + 1}")
        attachment_title = safe_get(row, attachment_title_col, None)

        if text_col:
            chunk_text = clean_text(safe_get(row, text_col, ""))
        else:
            chunk_text = ""

        # 별표/첨부 본문이 비어 있더라도 제목은 검색 후보로 남긴다.
        if len(chunk_text) < 20:
            chunk_text = clean_text(
                f"{safe_get(row, title_col, '')} {attachment_title or ''}"
            )

        if len(chunk_text) < 10:
            continue

        registry_id = f"REG_LEGAL_ATTACHMENT_{idx + 1:06d}"

        records.append(
            {
                "registry_id": registry_id,
                "source_table": "legal_attachment",
                "source_pk": str(source_pk),
                "source_id": source_id,
                "source_category": safe_get(row, category_col, "legal_attachment"),
                "provider": safe_get(row, provider_col, "국가법령정보센터"),
                "document_title": safe_get(row, title_col, None),
                "chunk_type": "legal_attachment",
                "article_no": None,
                "article_title": attachment_title,
                "page_no": None,
                "chunk_order": None,
                "chunk_text": chunk_text,
                "chunk_hash": make_hash(chunk_text),
                "vector_collection": "law_attachment_vectors",
                "embedding_status": "pending",
                "current_version_yn": "Y",
                "created_at": now,
            }
        )

    return records


def build_from_external_chunk(engine):
    df = pd.read_sql("SELECT * FROM external_reference_chunk;", engine)

    if df.empty:
        return []

    print(f"[external_reference_chunk 로드] {len(df)}건")
    print(f"- columns: {list(df.columns)}")

    records = []
    now = datetime.now()

    for idx, row in df.iterrows():
        chunk_text = clean_text(row.get("chunk_text", ""))

        if len(chunk_text) < 20:
            continue

        source_pk = row.get("external_chunk_id", f"external_chunk_{idx + 1}")
        registry_id = f"REG_EXTERNAL_{idx + 1:06d}"

        page_no = row.get("page_no", None)
        if pd.isna(page_no):
            page_no = None

        chunk_order = row.get("chunk_order", None)
        if pd.isna(chunk_order):
            chunk_order = None

        records.append(
            {
                "registry_id": registry_id,
                "source_table": "external_reference_chunk",
                "source_pk": str(source_pk),
                "source_id": row.get("source_id", None),
                "source_category": row.get("source_category", "external_reference"),
                "provider": row.get("provider", None),
                "document_title": row.get("title", None),
                "chunk_type": "external_reference",
                "article_no": None,
                "article_title": row.get("section_title", None),
                "page_no": int(page_no) if page_no is not None else None,
                "chunk_order": int(chunk_order) if chunk_order is not None else None,
                "chunk_text": chunk_text,
                "chunk_hash": make_hash(chunk_text),
                "vector_collection": "external_reference_vectors",
                "embedding_status": "pending",
                "current_version_yn": "Y",
                "created_at": now,
            }
        )

    return records


def insert_registry_records(engine, records):
    if not records:
        print("[주의] 적재할 retrieval record가 없습니다.")
        return

    df = pd.DataFrame(records)

    df.to_sql(
        "retrieval_chunk_registry",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=500,
    )

    print(f"[retrieval_chunk_registry 적재 완료] {len(df)}건")


def print_summary(engine):
    queries = {
        "전체 registry 건수": """
            SELECT COUNT(*) FROM retrieval_chunk_registry;
        """,
        "source_table별 건수": """
            SELECT source_table, COUNT(*)
            FROM retrieval_chunk_registry
            GROUP BY source_table
            ORDER BY source_table;
        """,
        "vector_collection별 건수": """
            SELECT vector_collection, COUNT(*)
            FROM retrieval_chunk_registry
            GROUP BY vector_collection
            ORDER BY vector_collection;
        """,
        "embedding_status별 건수": """
            SELECT embedding_status, COUNT(*)
            FROM retrieval_chunk_registry
            GROUP BY embedding_status
            ORDER BY embedding_status;
        """,
        "샘플": """
            SELECT
                source_table,
                source_id,
                document_title,
                chunk_type,
                article_no,
                article_title,
                LEFT(chunk_text, 250) AS preview
            FROM retrieval_chunk_registry
            ORDER BY registry_id
            LIMIT 10;
        """,
    }

    with engine.connect() as conn:
        for title, query in queries.items():
            print("\n" + "=" * 80)
            print(f"[{title}]")
            rows = conn.execute(text(query)).fetchall()
            for row in rows:
                print(row)


def main():
    engine = get_engine()

    recreate_registry_table(engine)

    all_records = []

    all_records.extend(build_from_legal_article(engine))
    all_records.extend(build_from_legal_attachment(engine))
    all_records.extend(build_from_external_chunk(engine))

    # 동일 chunk_hash 중복 제거
    unique = {}
    for record in all_records:
        key = (
            record["source_table"],
            record["source_id"],
            record["chunk_hash"],
        )
        if key not in unique:
            unique[key] = record

    final_records = list(unique.values())

    print("\n" + "=" * 80)
    print("[중복 제거 결과]")
    print(f"- 원본 후보: {len(all_records)}건")
    print(f"- 최종 후보: {len(final_records)}건")

    insert_registry_records(engine, final_records)
    print_summary(engine)


if __name__ == "__main__":
    main()