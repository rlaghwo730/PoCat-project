import os
import sys

import psycopg2
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer


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


def connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def vector_to_pgvector(values):
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def search(query, top_k=10):
    model = SentenceTransformer(EMBEDDING_MODEL)
    query_embedding = model.encode([query], normalize_embeddings=True)[0]
    vector_text = vector_to_pgvector(query_embedding)

    conn = connect()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    r.source_domain,
                    r.citation_label,
                    r.source_url,
                    LEFT(r.content, 250) AS content_preview,
                    1 - (e.embedding <=> %s::vector) AS similarity
                FROM unified_chunk_embedding e
                JOIN unified_retrieval_chunk r
                  ON e.unified_chunk_id = r.unified_chunk_id
                WHERE r.is_active = TRUE
                  AND e.embedding_model = %s
                ORDER BY e.embedding <=> %s::vector
                LIMIT %s;
                """,
                (vector_text, EMBEDDING_MODEL, vector_text, top_k),
            )

            rows = cur.fetchall()

        for idx, row in enumerate(rows, start=1):
            source_domain, citation_label, source_url, content_preview, similarity = row

            print("=" * 80)
            print("Rank:", idx)
            print("Source Domain:", source_domain)
            print("Similarity:", round(float(similarity), 4))
            print("Citation:", citation_label)
            print("URL:", source_url)
            print("Preview:", content_preview)

    finally:
        conn.close()


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]).strip()

    if not query:
        query = "비급여 치료비는 전액 보장합니다."

    search(query=query, top_k=10)