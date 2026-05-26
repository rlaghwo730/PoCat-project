import os
from urllib.parse import quote

import psycopg2
from dotenv import load_dotenv


load_dotenv()

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5433")
DB_NAME = os.getenv("POSTGRES_DB", "silson_legal_db")
DB_USER = os.getenv("POSTGRES_USER", "silson")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "silson_pw")


def connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def law_url(law_name):
    law_name = clean(law_name)
    if not law_name:
        return None
    return "https://www.law.go.kr/법령/" + quote(law_name)


def citation(*parts):
    values = []
    for part in parts:
        part = clean(part)
        if part:
            values.append(part)
    return " ".join(values) if values else None


def article_label(article_no):
    article_no = clean(article_no)
    if not article_no:
        return None
    if article_no.startswith("제") and article_no.endswith("조"):
        return article_no
    return "제{}조".format(article_no)


def main():
    conn = connect()
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # =========================================================
            # 1. legal_document 보정
            # =========================================================
            cur.execute(
                """
                SELECT
                    document_id,
                    source_id,
                    official_name,
                    source_name,
                    law_id,
                    mst,
                    admrul_serial,
                    admrul_id
                FROM legal_document;
                """
            )

            legal_documents = cur.fetchall()
            doc_count = 0

            for row in legal_documents:
                (
                    document_id,
                    source_id,
                    official_name,
                    source_name,
                    law_id,
                    mst,
                    admrul_serial,
                    admrul_id,
                ) = row

                law_name = clean(official_name) or clean(source_name)
                url = law_url(law_name)

                source_identifier = citation(
                    "document_id={}".format(document_id),
                    "source_id={}".format(source_id) if source_id else None,
                    "law_id={}".format(law_id) if law_id else None,
                    "mst={}".format(mst) if mst else None,
                    "admrul_serial={}".format(admrul_serial) if admrul_serial else None,
                    "admrul_id={}".format(admrul_id) if admrul_id else None,
                )

                cur.execute(
                    """
                    UPDATE legal_document
                    SET source_url = %s,
                        citation_label = %s,
                        source_identifier = %s
                    WHERE document_id = %s;
                    """,
                    (url, law_name, source_identifier, document_id),
                )
                doc_count += 1

            # =========================================================
            # 2. legal_article 보정
            # =========================================================
            cur.execute(
                """
                SELECT
                    a.article_id,
                    a.document_id,
                    a.source_id,
                    a.article_no,
                    a.article_title,
                    d.official_name,
                    d.source_name,
                    d.law_id,
                    d.mst,
                    d.admrul_serial,
                    d.admrul_id
                FROM legal_article a
                LEFT JOIN legal_document d
                  ON a.document_id = d.document_id;
                """
            )

            article_rows = cur.fetchall()
            article_count = 0

            for row in article_rows:
                (
                    article_id,
                    document_id,
                    source_id,
                    article_no,
                    article_title,
                    official_name,
                    source_name,
                    law_id,
                    mst,
                    admrul_serial,
                    admrul_id,
                ) = row

                law_name = clean(official_name) or clean(source_name)
                url = law_url(law_name)

                cite = citation(
                    law_name,
                    article_label(article_no),
                    article_title,
                )

                source_identifier = citation(
                    "article_id={}".format(article_id),
                    "document_id={}".format(document_id),
                    "source_id={}".format(source_id) if source_id else None,
                    "law_id={}".format(law_id) if law_id else None,
                    "mst={}".format(mst) if mst else None,
                    "admrul_serial={}".format(admrul_serial) if admrul_serial else None,
                    "admrul_id={}".format(admrul_id) if admrul_id else None,
                )

                cur.execute(
                    """
                    UPDATE legal_article
                    SET source_url = %s,
                        citation_label = %s,
                        source_identifier = %s
                    WHERE article_id = %s;
                    """,
                    (url, cite, source_identifier, article_id),
                )
                article_count += 1

            # =========================================================
            # 3. legal_attachment 보정
            # =========================================================
            cur.execute(
                """
                SELECT
                    la.attachment_id,
                    la.document_id,
                    la.source_id,
                    la.attachment_no,
                    la.attachment_type,
                    la.attachment_title,
                    la.pdf_link,
                    la.hwp_link,
                    la.image_link,
                    la.extra_file_link,
                    d.official_name,
                    d.source_name,
                    d.law_id,
                    d.mst,
                    d.admrul_serial,
                    d.admrul_id
                FROM legal_attachment la
                LEFT JOIN legal_document d
                  ON la.document_id = d.document_id;
                """
            )

            attachment_rows = cur.fetchall()
            attachment_count = 0

            for row in attachment_rows:
                (
                    attachment_id,
                    document_id,
                    source_id,
                    attachment_no,
                    attachment_type,
                    attachment_title,
                    pdf_link,
                    hwp_link,
                    image_link,
                    extra_file_link,
                    official_name,
                    source_name,
                    law_id,
                    mst,
                    admrul_serial,
                    admrul_id,
                ) = row

                law_name = clean(official_name) or clean(source_name)

                url = (
                    clean(pdf_link)
                    or clean(hwp_link)
                    or clean(image_link)
                    or clean(extra_file_link)
                    or law_url(law_name)
                )

                cite = citation(
                    law_name,
                    attachment_type,
                    "제{}호".format(attachment_no) if clean(attachment_no) else None,
                    attachment_title,
                )

                source_identifier = citation(
                    "attachment_id={}".format(attachment_id),
                    "document_id={}".format(document_id),
                    "source_id={}".format(source_id) if source_id else None,
                    "law_id={}".format(law_id) if law_id else None,
                    "mst={}".format(mst) if mst else None,
                    "admrul_serial={}".format(admrul_serial) if admrul_serial else None,
                    "admrul_id={}".format(admrul_id) if admrul_id else None,
                )

                cur.execute(
                    """
                    UPDATE legal_attachment
                    SET source_url = %s,
                        citation_label = %s,
                        source_identifier = %s
                    WHERE attachment_id = %s;
                    """,
                    (url, cite, source_identifier, attachment_id),
                )
                attachment_count += 1

            # =========================================================
            # 4. external_reference_chunk citation 보정
            # =========================================================
            cur.execute(
                """
                SELECT
                    external_chunk_id,
                    external_doc_id,
                    source_id,
                    provider,
                    title,
                    section_title,
                    page_no,
                    chunk_order
                FROM external_reference_chunk;
                """
            )

            external_rows = cur.fetchall()
            external_count = 0

            for row in external_rows:
                (
                    external_chunk_id,
                    external_doc_id,
                    source_id,
                    provider,
                    title,
                    section_title,
                    page_no,
                    chunk_order,
                ) = row

                cite = citation(
                    provider,
                    title,
                    section_title,
                    "p.{}".format(page_no) if page_no is not None else None,
                )

                cur.execute(
                    """
                    UPDATE external_reference_chunk
                    SET citation_label = %s
                    WHERE external_chunk_id = %s;
                    """,
                    (cite, external_chunk_id),
                )
                external_count += 1

            # =========================================================
            # 5. unified_retrieval_chunk - legal 보정
            # =========================================================
            cur.execute(
                """
                SELECT
                    unified_chunk_id,
                    document_name,
                    article_no,
                    title,
                    source_table,
                    source_id
                FROM unified_retrieval_chunk
                WHERE is_active = TRUE
                  AND source_domain = 'legal';
                """
            )

            unified_legal_rows = cur.fetchall()
            unified_legal_count = 0

            for row in unified_legal_rows:
                (
                    unified_chunk_id,
                    document_name,
                    article_no,
                    title,
                    source_table,
                    source_id,
                ) = row

                law_name = clean(document_name)
                url = law_url(law_name)

                cite = citation(
                    law_name,
                    article_label(article_no),
                    title,
                )

                source_identifier = citation(
                    "unified_chunk_id={}".format(unified_chunk_id),
                    "source_table={}".format(source_table),
                    "source_id={}".format(source_id),
                )

                cur.execute(
                    """
                    UPDATE unified_retrieval_chunk
                    SET source_url = %s,
                        citation_label = %s,
                        source_identifier = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE unified_chunk_id = %s;
                    """,
                    (url, cite, source_identifier, unified_chunk_id),
                )

                unified_legal_count += 1

            # =========================================================
            # 6. unified_retrieval_chunk - legal_attachment 보정
            #    metadata_json.legacy_source_pk = legal_attachment.attachment_id 기준 조인
            # =========================================================
            cur.execute(
                """
                SELECT
                    u.unified_chunk_id,
                    u.source_table,
                    u.source_id,
                    u.title,
                    u.metadata_json ->> 'legacy_source_pk' AS attachment_id,
                    la.attachment_no,
                    la.attachment_type,
                    la.attachment_title,
                    la.pdf_link,
                    la.hwp_link,
                    la.image_link,
                    la.extra_file_link,
                    d.official_name,
                    d.source_name
                FROM unified_retrieval_chunk u
                LEFT JOIN legal_attachment la
                  ON u.metadata_json ->> 'legacy_source_pk' = la.attachment_id
                LEFT JOIN legal_document d
                  ON la.document_id = d.document_id
                WHERE u.is_active = TRUE
                  AND u.source_domain = 'legal_attachment';
                """
            )

            unified_attachment_rows = cur.fetchall()
            unified_attachment_count = 0

            for row in unified_attachment_rows:
                (
                    unified_chunk_id,
                    source_table,
                    source_id,
                    title,
                    attachment_id,
                    attachment_no,
                    attachment_type,
                    attachment_title,
                    pdf_link,
                    hwp_link,
                    image_link,
                    extra_file_link,
                    official_name,
                    source_name,
                ) = row

                law_name = clean(official_name) or clean(source_name)

                url = (
                    clean(pdf_link)
                    or clean(hwp_link)
                    or clean(image_link)
                    or clean(extra_file_link)
                    or law_url(law_name)
                )

                cite = citation(
                    law_name,
                    attachment_type,
                    "제{}호".format(attachment_no) if clean(attachment_no) else None,
                    attachment_title or title,
                )

                source_identifier = citation(
                    "unified_chunk_id={}".format(unified_chunk_id),
                    "source_table={}".format(source_table),
                    "source_id={}".format(source_id),
                    "attachment_id={}".format(attachment_id) if attachment_id else None,
                )

                cur.execute(
                    """
                    UPDATE unified_retrieval_chunk
                    SET source_url = %s,
                        citation_label = %s,
                        source_identifier = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE unified_chunk_id = %s;
                    """,
                    (url, cite, source_identifier, unified_chunk_id),
                )

                unified_attachment_count += 1

        conn.commit()

        print("[SUCCESS] source URL / citation backfill complete")
        print("  - legal_document updated          :", doc_count)
        print("  - legal_article updated           :", article_count)
        print("  - legal_attachment updated        :", attachment_count)
        print("  - external_reference_chunk updated:", external_count)
        print("  - unified legal updated           :", unified_legal_count)
        print("  - unified attachment updated      :", unified_attachment_count)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()