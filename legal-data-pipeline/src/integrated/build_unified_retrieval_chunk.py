import hashlib
import os
from urllib.parse import quote

import psycopg2
from psycopg2.extras import Json
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


def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def normalize_source_domain(source_table, chunk_type):
    source_table = source_table or ""
    chunk_type = chunk_type or ""

    if source_table == "legal_article":
        return "legal"
    if source_table == "legal_attachment":
        return "legal_attachment"
    if source_table == "external_reference_chunk":
        return "external_reference"

    chunk_type_lower = chunk_type.lower()

    if "article" in chunk_type_lower:
        return "legal"
    if "attachment" in chunk_type_lower:
        return "legal_attachment"
    if "external" in chunk_type_lower:
        return "external_reference"

    return "legal"


def build_law_source_url(document_title, source_name=None):
    """
    법령 URL은 제공기관명(source_name)이 아니라 실제 법령명(document_title)을 우선 사용한다.

    잘못된 예:
    - https://www.law.go.kr/법령/국가법령정보센터

    올바른 예:
    - https://www.law.go.kr/법령/민법
    - https://www.law.go.kr/법령/금융소비자 보호에 관한 감독규정
    """
    law_name = clean(document_title) or clean(source_name)

    if not law_name:
        return None

    if law_name == "국가법령정보센터":
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
            # ---------------------------------------------------------
            # 1. 기존 통합 검색 chunk 비활성화
            # ---------------------------------------------------------
            cur.execute(
                """
                UPDATE unified_retrieval_chunk
                SET is_active = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE source_domain IN (
                    'legal',
                    'legal_attachment',
                    'external_reference',
                    'insurance_policy',
                    'insurance_cited_law',
                    'insurance_product_doc'
                );
                """
            )

            # ---------------------------------------------------------
            # 2. 기존 C파트 retrieval_chunk_registry → unified_retrieval_chunk
            # ---------------------------------------------------------
            cur.execute(
                """
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
                    vector_collection,
                    embedding_status,
                    current_version_yn,
                    created_at
                FROM retrieval_chunk_registry
                WHERE COALESCE(current_version_yn, 'Y') = 'Y'
                  AND chunk_text IS NOT NULL
                  AND LENGTH(TRIM(chunk_text)) > 0
                ORDER BY source_table, document_title, article_no, chunk_order NULLS LAST;
                """
            )

            registry_rows = cur.fetchall()
            registry_count = 0

            for row in registry_rows:
                (
                    registry_id,
                    source_table,
                    source_pk,
                    legacy_source_id,
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
                    vector_collection,
                    embedding_status,
                    current_version_yn,
                    created_at,
                ) = row

                source_domain = normalize_source_domain(source_table, chunk_type)
                source_name = provider or source_category or document_title
                title = article_title or document_title
                content = (chunk_text or "").strip()
                content_hash = chunk_hash or sha256_text(content)

                # -----------------------------------------------------
                # URL / Citation 생성
                # -----------------------------------------------------
                if source_domain == "external_reference":
                    # 외부자료는 원문 URL이 명확하지 않으면 임의 URL을 만들지 않는다.
                    source_url = None
                    citation_label = citation(provider, document_title, article_title)

                elif source_domain == "legal":
                    # 법령 조문은 document_title, 즉 실제 법령명을 기준으로 law.go.kr URL 생성
                    source_url = build_law_source_url(document_title, source_name)
                    citation_label = citation(
                        document_title or source_name,
                        article_label(article_no),
                        article_title,
                    )

                elif source_domain == "legal_attachment":
                    # 별표/첨부자료는 document_title이 비어 있을 수 있다.
                    # source_name이 국가법령정보센터인 경우 가짜 URL을 만들지 않는다.
                    # 이후 backfill_source_urls.py에서 legal_attachment 원천 테이블과 조인해 보정한다.
                    source_url = build_law_source_url(document_title, None)
                    citation_label = citation(
                        document_title,
                        article_title,
                    )

                else:
                    source_url = build_law_source_url(document_title, source_name)
                    citation_label = citation(
                        document_title or source_name,
                        article_label(article_no),
                        article_title,
                    )

                if not citation_label:
                    citation_label = document_title or source_name or registry_id

                metadata = {
                    "source_category": source_category,
                    "provider": provider,
                    "chunk_type": chunk_type,
                    "page_no": page_no,
                    "chunk_order": chunk_order,
                    "vector_collection": vector_collection,
                    "embedding_status": embedding_status,
                    "legacy_registry_id": registry_id,
                    "legacy_source_pk": source_pk,
                    "legacy_source_id": legacy_source_id,
                }

                cur.execute(
                    """
                    INSERT INTO unified_retrieval_chunk (
                        source_domain,
                        source_table,
                        source_id,
                        source_name,
                        company_name,
                        product_name,
                        document_name,
                        document_type,
                        section,
                        article_no,
                        title,
                        content,
                        source_url,
                        api_lookup_template,
                        source_identifier,
                        citation_label,
                        version_date,
                        content_hash,
                        metadata_json,
                        is_active
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        NULL, NULL, %s, %s,
                        NULL, %s, %s, %s,
                        %s, NULL, %s, %s,
                        CURRENT_DATE, %s, %s, TRUE
                    )
                    ON CONFLICT (source_domain, source_table, source_id, content_hash)
                    DO UPDATE SET
                        source_name = EXCLUDED.source_name,
                        document_name = EXCLUDED.document_name,
                        document_type = EXCLUDED.document_type,
                        article_no = EXCLUDED.article_no,
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        source_url = EXCLUDED.source_url,
                        source_identifier = EXCLUDED.source_identifier,
                        citation_label = EXCLUDED.citation_label,
                        version_date = EXCLUDED.version_date,
                        metadata_json = EXCLUDED.metadata_json,
                        is_active = TRUE,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (
                        source_domain,
                        source_table,
                        str(registry_id),
                        source_name,
                        document_title,
                        chunk_type,
                        article_no,
                        title,
                        content,
                        source_url,
                        "registry_id={};source_pk={}".format(registry_id, source_pk),
                        citation_label,
                        content_hash,
                        Json(metadata),
                    ),
                )

                registry_count += 1

            # ---------------------------------------------------------
            # 3. A팀 보험사 데이터 insurance_text_unit → unified_retrieval_chunk
            # ---------------------------------------------------------
            cur.execute(
                """
                SELECT
                    itu.text_unit_id,
                    itu.source_domain,
                    itu.document_type,
                    itu.section,
                    itu.article_no,
                    itu.title,
                    itu.content,
                    itu.chunk_index,
                    itu.clause_group_key,
                    itu.source_url,
                    itu.citation_label,
                    itu.version_date,
                    itu.content_hash,
                    itu.metadata_json,
                    ic.company_name,
                    ip.product_name,
                    idoc.document_name
                FROM insurance_text_unit itu
                JOIN insurance_company ic
                  ON itu.company_id = ic.company_id
                LEFT JOIN insurance_product ip
                  ON itu.product_id = ip.product_id
                LEFT JOIN insurance_document idoc
                  ON itu.document_id = idoc.document_id
                WHERE itu.is_active = TRUE
                  AND itu.content IS NOT NULL
                  AND LENGTH(TRIM(itu.content)) > 0
                ORDER BY itu.document_type, itu.article_no, itu.chunk_index;
                """
            )

            insurance_rows = cur.fetchall()
            insurance_count = 0

            for row in insurance_rows:
                (
                    text_unit_id,
                    source_domain,
                    document_type,
                    section,
                    article_no,
                    title,
                    content,
                    chunk_index,
                    clause_group_key,
                    source_url,
                    citation_label,
                    version_date,
                    content_hash,
                    metadata_json,
                    company_name,
                    product_name,
                    document_name,
                ) = row

                content = (content or "").strip()
                content_hash = content_hash or sha256_text(content)

                if not citation_label:
                    citation_label = citation(
                        company_name,
                        "실손의료보험",
                        document_type,
                        article_label(article_no),
                        title,
                    )

                metadata = {
                    "chunk_index": chunk_index,
                    "clause_group_key": clause_group_key,
                    "original_metadata": metadata_json,
                }

                cur.execute(
                    """
                    INSERT INTO unified_retrieval_chunk (
                        source_domain,
                        source_table,
                        source_id,
                        source_name,
                        company_name,
                        product_name,
                        document_name,
                        document_type,
                        section,
                        article_no,
                        title,
                        content,
                        source_url,
                        api_lookup_template,
                        source_identifier,
                        citation_label,
                        version_date,
                        content_hash,
                        metadata_json,
                        is_active
                    )
                    VALUES (
                        %s, 'insurance_text_unit', %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, NULL, %s, %s,
                        %s, %s, %s, TRUE
                    )
                    ON CONFLICT (source_domain, source_table, source_id, content_hash)
                    DO UPDATE SET
                        source_name = EXCLUDED.source_name,
                        company_name = EXCLUDED.company_name,
                        product_name = EXCLUDED.product_name,
                        document_name = EXCLUDED.document_name,
                        document_type = EXCLUDED.document_type,
                        section = EXCLUDED.section,
                        article_no = EXCLUDED.article_no,
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        source_url = EXCLUDED.source_url,
                        source_identifier = EXCLUDED.source_identifier,
                        citation_label = EXCLUDED.citation_label,
                        version_date = EXCLUDED.version_date,
                        metadata_json = EXCLUDED.metadata_json,
                        is_active = TRUE,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (
                        source_domain,
                        str(text_unit_id),
                        company_name,
                        company_name,
                        product_name,
                        document_name,
                        document_type,
                        section,
                        article_no,
                        title,
                        content,
                        source_url,
                        "text_unit_id={};chunk_index={}".format(text_unit_id, chunk_index),
                        citation_label,
                        version_date,
                        content_hash,
                        Json(metadata),
                    ),
                )

                insurance_count += 1

        conn.commit()

        print("[SUCCESS] unified_retrieval_chunk build complete")
        print("  - registry rows upserted : {}".format(registry_count))
        print("  - insurance rows upserted: {}".format(insurance_count))
        print("  - expected total         : {}".format(registry_count + insurance_count))

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()