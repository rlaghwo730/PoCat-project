from pathlib import Path

import chromadb
from chromadb.config import Settings
from sqlalchemy import text

from db import get_engine


CHROMA_DIR = Path("data/vector_store/chroma")

COLLECTIONS = [
    "law_regulation_vectors",
    "law_attachment_vectors",
    "external_reference_vectors",
]


def check_db_status():
    engine = get_engine()

    queries = {
        "embedding_status별 건수": """
            SELECT embedding_status, COUNT(*)
            FROM retrieval_chunk_registry
            GROUP BY embedding_status
            ORDER BY embedding_status;
        """,
        "vector_collection별 embedding 상태": """
            SELECT
                vector_collection,
                embedding_status,
                COUNT(*)
            FROM retrieval_chunk_registry
            GROUP BY vector_collection, embedding_status
            ORDER BY vector_collection, embedding_status;
        """,
    }

    with engine.connect() as conn:
        for title, query in queries.items():
            print("\n" + "=" * 100)
            print(f"[{title}]")
            rows = conn.execute(text(query)).fetchall()
            for row in rows:
                print(row)


def check_chroma_status():
    print("\n" + "=" * 100)
    print("[Chroma collection 상태]")

    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )

    for name in COLLECTIONS:
        try:
            collection = client.get_collection(name)
            print(f"- {name}: {collection.count()}건")
        except Exception as e:
            print(f"- {name}: 없음 또는 오류 | {e}")


def main():
    check_db_status()
    check_chroma_status()


if __name__ == "__main__":
    main()