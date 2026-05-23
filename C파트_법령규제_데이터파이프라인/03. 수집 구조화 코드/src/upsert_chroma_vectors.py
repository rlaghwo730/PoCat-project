import os
from pathlib import Path
from datetime import datetime

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from sqlalchemy import text

from db import get_engine


CHROMA_DIR = Path("data/vector_store/chroma")
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

BATCH_SIZE = 64
MAX_ROWS = None  # 테스트만 하려면 300 같은 숫자로 변경 가능


COLLECTION_MAP = {
    "law_regulation_vectors": "law_regulation_vectors",
    "law_attachment_vectors": "law_attachment_vectors",
    "external_reference_vectors": "external_reference_vectors",
}


def ensure_dirs():
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)


def load_pending_rows(limit=None):
    engine = get_engine()

    limit_sql = ""
    if limit is not None:
        limit_sql = f"LIMIT {int(limit)}"

    sql = text(f"""
        SELECT
            registry_id,
            source_table,
            source_pk,
            source_id,
            source_category,
            provider,
            document_title,
            chunk_type,
            article_no,
            article_title,
            page_no,
            chunk_order,
            chunk_text,
            chunk_hash,
            vector_collection
        FROM retrieval_chunk_registry
        WHERE
            current_version_yn = 'Y'
            AND embedding_status = 'pending'
        ORDER BY registry_id
        {limit_sql};
    """)

    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()

    return rows


def update_embedding_status(registry_ids, status="embedded"):
    if not registry_ids:
        return

    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE retrieval_chunk_registry
                SET embedding_status = :status
                WHERE registry_id = ANY(:registry_ids);
            """),
            {
                "status": status,
                "registry_ids": registry_ids,
            },
        )


def safe_metadata_value(value):
    if value is None:
        return ""
    return str(value)


def build_metadata(row):
    return {
        "registry_id": safe_metadata_value(row.registry_id),
        "source_table": safe_metadata_value(row.source_table),
        "source_pk": safe_metadata_value(row.source_pk),
        "source_id": safe_metadata_value(row.source_id),
        "source_category": safe_metadata_value(row.source_category),
        "provider": safe_metadata_value(row.provider),
        "document_title": safe_metadata_value(row.document_title),
        "chunk_type": safe_metadata_value(row.chunk_type),
        "article_no": safe_metadata_value(row.article_no),
        "article_title": safe_metadata_value(row.article_title),
        "page_no": safe_metadata_value(row.page_no),
        "chunk_order": safe_metadata_value(row.chunk_order),
        "chunk_hash": safe_metadata_value(row.chunk_hash),
        "vector_collection": safe_metadata_value(row.vector_collection),
    }


def chunk_list(items, batch_size):
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def main():
    ensure_dirs()

    print("=" * 100)
    print("[Vector DB 적재 시작]")
    print(f"- Chroma path: {CHROMA_DIR}")
    print(f"- Embedding model: {MODEL_NAME}")
    print(f"- Batch size: {BATCH_SIZE}")
    print(f"- Max rows: {MAX_ROWS}")

    rows = load_pending_rows(limit=MAX_ROWS)

    print(f"\n[pending row 수] {len(rows)}")

    if not rows:
        print("- 적재할 pending chunk가 없습니다.")
        return

    print("\n[Embedding model 로드 중]")
    model = SentenceTransformer(MODEL_NAME)

    print("[Chroma client 초기화]")
    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )

    total_embedded = 0
    failed = []

    for collection_name in COLLECTION_MAP.values():
        collection_rows = [
            row for row in rows
            if row.vector_collection == collection_name
        ]

        if not collection_rows:
            continue

        print("\n" + "=" * 100)
        print(f"[Collection 처리] {collection_name}")
        print(f"- 대상 row 수: {len(collection_rows)}")

        collection = client.get_or_create_collection(
            name=collection_name,
            metadata={
                "description": f"실손보험 법률·규제 RAG collection: {collection_name}",
                "created_by": "silson-legal-data-pipeline",
            },
        )

        for batch_idx, batch_rows in enumerate(chunk_list(collection_rows, BATCH_SIZE), start=1):
            try:
                ids = [row.registry_id for row in batch_rows]
                documents = [row.chunk_text for row in batch_rows]
                metadatas = [build_metadata(row) for row in batch_rows]

                embeddings = model.encode(
                    documents,
                    batch_size=BATCH_SIZE,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                ).tolist()

                collection.upsert(
                    ids=ids,
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=metadatas,
                )

                update_embedding_status(ids, status="embedded")

                total_embedded += len(ids)

                print(
                    f"- batch {batch_idx} 완료 | "
                    f"{len(ids)}건 | 누적 {total_embedded}건"
                )

            except Exception as e:
                print(f"[ERROR] collection={collection_name}, batch={batch_idx}, error={e}")
                failed.append((collection_name, batch_idx, str(e)))

    print("\n" + "=" * 100)
    print("[Vector DB 적재 완료]")
    print(f"- embedded: {total_embedded}건")
    print(f"- failed batch: {len(failed)}건")
    print(f"- completed_at: {datetime.now()}")

    if failed:
        print("\n[실패 목록]")
        for item in failed:
            print(item)


if __name__ == "__main__":
    main()