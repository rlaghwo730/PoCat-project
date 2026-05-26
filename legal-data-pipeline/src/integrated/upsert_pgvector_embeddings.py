import os
from datetime import datetime

import psycopg2
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from tqdm import tqdm


load_dotenv()

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5433")
DB_NAME = os.getenv("POSTGRES_DB", "silson_legal_db")
DB_USER = os.getenv("POSTGRES_USER", "silson")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "silson_pw")

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

EMBEDDING_DIM = 384
BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))


def connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def vector_to_pgvector(values):
    """
    pgvector 입력 형식: [0.1,0.2,0.3]
    """
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def fetch_embedding_targets(conn):
    """
    아직 embedding이 없거나, content_hash가 달라진 chunk만 가져온다.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.unified_chunk_id,
                r.content,
                r.content_hash
            FROM unified_retrieval_chunk r
            LEFT JOIN unified_chunk_embedding e
              ON r.unified_chunk_id = e.unified_chunk_id
             AND e.embedding_model = %s
            WHERE r.is_active = TRUE
              AND r.content IS NOT NULL
              AND LENGTH(TRIM(r.content)) > 0
              AND (
                    e.embedding_id IS NULL
                    OR e.content_hash IS DISTINCT FROM r.content_hash
                  )
            ORDER BY r.unified_chunk_id;
            """,
            (EMBEDDING_MODEL,),
        )
        return cur.fetchall()


def upsert_embeddings(conn, rows, embeddings):
    with conn.cursor() as cur:
        for (unified_chunk_id, content, content_hash), embedding in zip(rows, embeddings):
            vector_text = vector_to_pgvector(embedding)

            cur.execute(
                """
                INSERT INTO unified_chunk_embedding (
                    unified_chunk_id,
                    embedding_model,
                    embedding_dim,
                    embedding,
                    content_hash,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s, %s, %s, %s::vector, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                ON CONFLICT (unified_chunk_id, embedding_model)
                DO UPDATE SET
                    embedding_dim = EXCLUDED.embedding_dim,
                    embedding = EXCLUDED.embedding,
                    content_hash = EXCLUDED.content_hash,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (
                    unified_chunk_id,
                    EMBEDDING_MODEL,
                    EMBEDDING_DIM,
                    vector_text,
                    content_hash,
                ),
            )


def main():
    started_at = datetime.now()
    print("[INFO] embedding model:", EMBEDDING_MODEL)
    print("[INFO] batch size:", BATCH_SIZE)

    conn = connect()
    conn.autocommit = False

    try:
        targets = fetch_embedding_targets(conn)
        total = len(targets)

        print("[INFO] embedding targets:", total)

        if total == 0:
            print("[SUCCESS] no embedding targets. already up-to-date.")
            return

        model = SentenceTransformer(EMBEDDING_MODEL)

        for start in tqdm(range(0, total, BATCH_SIZE), desc="Embedding upsert"):
            batch_rows = targets[start:start + BATCH_SIZE]
            texts = [row[1] for row in batch_rows]

            embeddings = model.encode(
                texts,
                batch_size=BATCH_SIZE,
                show_progress_bar=False,
                normalize_embeddings=True,
            )

            upsert_embeddings(conn, batch_rows, embeddings)
            conn.commit()

        ended_at = datetime.now()
        print("[SUCCESS] pgvector embedding upsert complete")
        print("[INFO] total embedded:", total)
        print("[INFO] elapsed:", ended_at - started_at)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()