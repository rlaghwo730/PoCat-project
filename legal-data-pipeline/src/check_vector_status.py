import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        sslmode=os.getenv("POSTGRES_SSLMODE", "require"),
    )


def main():
    conn = get_conn()
    cur = conn.cursor()

    print("=" * 100)
    print("[PGVECTOR STATUS]")
    print("=" * 100)

    cur.execute("""
        SELECT COUNT(*)
        FROM unified_retrieval_chunk
        WHERE is_active = TRUE;
    """)
    active_chunks = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM unified_chunk_embedding;
    """)
    embeddings = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM unified_chunk_embedding e
        JOIN unified_retrieval_chunk r
          ON e.unified_chunk_id = r.unified_chunk_id
        WHERE r.is_active = TRUE;
    """)
    active_joined_embeddings = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM unified_chunk_embedding e
        LEFT JOIN unified_retrieval_chunk r
          ON e.unified_chunk_id = r.unified_chunk_id
        WHERE r.unified_chunk_id IS NULL
           OR r.is_active = FALSE;
    """)
    orphan_embeddings = cur.fetchone()[0]

    print(f"active chunks             : {active_chunks}")
    print(f"embeddings                : {embeddings}")
    print(f"active joined embeddings  : {active_joined_embeddings}")
    print(f"orphan embeddings         : {orphan_embeddings}")

    print()
    print("=" * 100)
    print("[SOURCE DOMAIN STATUS]")
    print("=" * 100)

    cur.execute("""
        SELECT source_domain, COUNT(*)
        FROM unified_retrieval_chunk
        WHERE is_active = TRUE
        GROUP BY source_domain
        ORDER BY source_domain;
    """)
    rows = cur.fetchall()

    for source_domain, count in rows:
        print(f"{source_domain}: {count}")

    print()
    print("=" * 100)
    print("[SOURCE DOMAIN EMBEDDING STATUS]")
    print("=" * 100)

    cur.execute("""
        SELECT
            r.source_domain,
            COUNT(*) AS embedding_count
        FROM unified_chunk_embedding e
        JOIN unified_retrieval_chunk r
          ON e.unified_chunk_id = r.unified_chunk_id
        WHERE r.is_active = TRUE
        GROUP BY r.source_domain
        ORDER BY r.source_domain;
    """)
    rows = cur.fetchall()

    for source_domain, count in rows:
        print(f"{source_domain}: {count}")

    print()
    print("=" * 100)
    print("[VALIDATION RESULT]")
    print("=" * 100)

    if active_chunks == active_joined_embeddings and orphan_embeddings == 0:
        print("[OK] pgvector embedding status is valid.")
    else:
        print("[WARN] pgvector embedding status needs review.")
        if active_chunks != active_joined_embeddings:
            print(f"- Missing active embeddings: {active_chunks - active_joined_embeddings}")
        if orphan_embeddings > 0:
            print(f"- Orphan embeddings: {orphan_embeddings}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()