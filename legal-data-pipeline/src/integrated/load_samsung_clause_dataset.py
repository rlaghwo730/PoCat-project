import json
import hashlib
from pathlib import Path
from collections import defaultdict

import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv
import os


load_dotenv()

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5433")
DB_NAME = os.getenv("POSTGRES_DB", "silson_legal_db")
DB_USER = os.getenv("POSTGRES_USER", "silson")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "silson_pw")

JSON_PATH = Path("data/insurance/samsung/processed/samsung_insurance_clause_dataset.json")

COMPANY_NAME = "삼성화재"
COMPANY_CODE = "SAMSUNG_FIRE"

PRODUCT_NAME = "무배당 삼성화재 다이렉트 실손의료비보험(2605.1)"
PRODUCT_CATEGORY = "실손의료보험"
PRODUCT_VERSION = "2605.1"
SALES_CHANNEL = "다이렉트"

POLICY_DOCUMENT_NAME = "삼성화재_실손의료보험_약관.pdf"
POLICY_FILE_PATH = "data/insurance/samsung/raw/삼성화재_실손의료보험_약관.pdf"

SUMMARY_DOCUMENT_NAME = "삼성화재_실손의료보험_상품요약서.pdf"
SUMMARY_FILE_PATH = "data/insurance/samsung/raw/삼성화재_실손의료보험_상품요약서.pdf"

BUSINESS_DOCUMENT_NAME = "삼성화재_실손의료보험_사업방법서.pdf"
BUSINESS_FILE_PATH = "data/insurance/samsung/raw/삼성화재_실손의료보험_사업방법서.pdf"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_domain_from_document_type(document_type: str) -> str:
    if document_type == "법규":
        return "insurance_cited_law"
    return "insurance_policy"


def connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def main():
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"JSON file not found: {JSON_PATH}")

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    print(f"[INFO] loaded JSON rows: {len(data)}")

    conn = connect()
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # 1. company upsert
            cur.execute(
                """
                INSERT INTO insurance_company (company_name, company_code)
                VALUES (%s, %s)
                ON CONFLICT (company_name)
                DO UPDATE SET
                    company_code = EXCLUDED.company_code,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING company_id;
                """,
                (COMPANY_NAME, COMPANY_CODE),
            )
            company_id = cur.fetchone()[0]

            # 2. product upsert
            cur.execute(
                """
                INSERT INTO insurance_product (
                    company_id,
                    product_name,
                    product_category,
                    product_version,
                    sales_channel,
                    is_main_dataset,
                    metadata_json
                )
                VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                ON CONFLICT (company_id, product_name)
                DO UPDATE SET
                    product_category = EXCLUDED.product_category,
                    product_version = EXCLUDED.product_version,
                    sales_channel = EXCLUDED.sales_channel,
                    is_main_dataset = TRUE,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING product_id;
                """,
                (
                    company_id,
                    PRODUCT_NAME,
                    PRODUCT_CATEGORY,
                    PRODUCT_VERSION,
                    SALES_CHANNEL,
                    Json({"source": "A팀 보험사 약관 구조화 데이터"}),
                ),
            )
            product_id = cur.fetchone()[0]

            # 3. document upsert
            documents = [
                ("약관", POLICY_DOCUMENT_NAME, POLICY_FILE_PATH),
                ("상품요약서", SUMMARY_DOCUMENT_NAME, SUMMARY_FILE_PATH),
                ("사업방법서", BUSINESS_DOCUMENT_NAME, BUSINESS_FILE_PATH),
            ]

            document_ids = {}

            for doc_type, doc_name, file_path in documents:
                cur.execute(
                    """
                    INSERT INTO insurance_document (
                        company_id,
                        product_id,
                        document_type,
                        document_name,
                        file_path,
                        source_url,
                        metadata_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (company_id, product_id, document_type, document_name)
                    DO UPDATE SET
                        file_path = EXCLUDED.file_path,
                        source_url = EXCLUDED.source_url,
                        metadata_json = EXCLUDED.metadata_json,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING document_id;
                    """,
                    (
                        company_id,
                        product_id,
                        doc_type,
                        doc_name,
                        file_path,
                        file_path,
                        Json({"local_file_path": file_path}),
                    ),
                )
                document_ids[doc_type] = cur.fetchone()[0]

            policy_document_id = document_ids["약관"]

            # 기존 삼성화재 약관 text unit 비활성화
            cur.execute(
                """
                UPDATE insurance_text_unit
                SET is_active = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE company_id = %s
                  AND product_id = %s
                  AND document_id = %s;
                """,
                (company_id, product_id, policy_document_id),
            )

            group_counter = defaultdict(int)
            insert_count = 0

            for row in data:
                content = (row.get("page_content") or "").strip()
                metadata = row.get("metadata") or {}

                if not content:
                    continue

                company = metadata.get("company", COMPANY_NAME)
                document_type = metadata.get("document_type")
                section = metadata.get("section")
                article_no = metadata.get("article")
                title = metadata.get("title")

                source_domain = source_domain_from_document_type(document_type)

                group_key = "|".join(
                    [
                        company or "",
                        document_type or "",
                        section or "",
                        article_no or "",
                        title or "",
                    ]
                )

                chunk_index = group_counter[group_key]
                group_counter[group_key] += 1

                content_hash = sha256_text(content)

                citation_parts = [COMPANY_NAME, "실손의료보험 약관"]
                if document_type:
                    citation_parts.append(document_type)
                if article_no:
                    citation_parts.append(article_no)
                if title:
                    citation_parts.append(title)

                citation_label = " ".join(citation_parts)

                cur.execute(
                    """
                    INSERT INTO insurance_text_unit (
                        document_id,
                        company_id,
                        product_id,
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
                        is_active
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE, %s, %s, TRUE
                    )
                    ON CONFLICT (
                        company_id,
                        product_id,
                        document_type,
                        section,
                        article_no,
                        title,
                        chunk_index,
                        content_hash
                    )
                    DO UPDATE SET
                        document_id = EXCLUDED.document_id,
                        source_domain = EXCLUDED.source_domain,
                        content = EXCLUDED.content,
                        clause_group_key = EXCLUDED.clause_group_key,
                        source_url = EXCLUDED.source_url,
                        citation_label = EXCLUDED.citation_label,
                        version_date = EXCLUDED.version_date,
                        metadata_json = EXCLUDED.metadata_json,
                        is_active = TRUE,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (
                        policy_document_id,
                        company_id,
                        product_id,
                        source_domain,
                        document_type,
                        section,
                        article_no,
                        title,
                        content,
                        chunk_index,
                        group_key,
                        POLICY_FILE_PATH,
                        citation_label,
                        content_hash,
                        Json(metadata),
                    ),
                )
                insert_count += 1

        conn.commit()
        print(f"[SUCCESS] insurance_text_unit upsert complete: {insert_count} rows")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()