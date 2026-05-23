from sqlalchemy import text
from db import get_engine


DDL = """
CREATE TABLE IF NOT EXISTS legal_source_inventory (
    source_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    domain_group TEXT,
    source_scope TEXT,
    collection_owner TEXT,
    collection_channel TEXT,
    target_type TEXT,
    source_category TEXT,
    provider TEXT,
    priority INTEGER,
    status TEXT,
    load_status TEXT,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS collection_run (
    run_id TEXT PRIMARY KEY,
    dag_id TEXT,
    task_group TEXT,
    run_type TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    run_status TEXT,
    total_sources INTEGER,
    success_count INTEGER,
    fail_count INTEGER,
    changed_count INTEGER,
    note TEXT
);

CREATE TABLE IF NOT EXISTS legal_document (
    document_id TEXT PRIMARY KEY,
    source_id TEXT REFERENCES legal_source_inventory(source_id),
    source_name TEXT,
    official_name TEXT,
    domain_group TEXT,
    target_type TEXT,
    law_id TEXT,
    mst TEXT,
    admrul_serial TEXT,
    admrul_id TEXT,
    law_or_rule_type TEXT,
    ministry TEXT,
    effective_date TEXT,
    promulgation_date TEXT,
    issue_date TEXT,
    revision_type TEXT,
    body_fetch_method TEXT,
    source_url TEXT,
    document_hash TEXT,
    current_version_yn TEXT DEFAULT 'Y',
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    run_id TEXT REFERENCES collection_run(run_id)
);

CREATE TABLE IF NOT EXISTS legal_article (
    article_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES legal_document(document_id),
    source_id TEXT REFERENCES legal_source_inventory(source_id),
    source_name TEXT,
    official_name TEXT,
    target_type TEXT,
    article_no TEXT,
    article_branch_no TEXT,
    article_title TEXT,
    article_text TEXT,
    article_effective_date TEXT,
    article_revision_type TEXT,
    article_change_yn TEXT,
    article_order INTEGER,
    article_hash TEXT,
    current_version_yn TEXT DEFAULT 'Y',
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    run_id TEXT REFERENCES collection_run(run_id)
);

CREATE TABLE IF NOT EXISTS legal_attachment (
    attachment_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES legal_document(document_id),
    source_id TEXT REFERENCES legal_source_inventory(source_id),
    source_name TEXT,
    official_name TEXT,
    target_type TEXT,
    attachment_no TEXT,
    attachment_branch_no TEXT,
    attachment_type TEXT,
    attachment_title TEXT,
    hwp_link TEXT,
    pdf_link TEXT,
    image_link TEXT,
    extra_file_name TEXT,
    extra_file_link TEXT,
    attachment_text TEXT,
    attachment_hash TEXT,
    file_path TEXT,
    download_status TEXT,
    current_version_yn TEXT DEFAULT 'Y',
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    run_id TEXT REFERENCES collection_run(run_id)
);

CREATE TABLE IF NOT EXISTS external_reference_document (
    external_doc_id TEXT PRIMARY KEY,
    source_id TEXT REFERENCES legal_source_inventory(source_id),
    source_category TEXT,
    provider TEXT,
    title TEXT,
    document_type TEXT,
    file_type TEXT,
    source_url TEXT,
    file_url TEXT,
    file_path TEXT,
    published_date TEXT,
    effective_date TEXT,
    collection_method TEXT,
    discovery_method TEXT,
    update_check_method TEXT,
    document_hash TEXT,
    collection_status TEXT,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    run_id TEXT REFERENCES collection_run(run_id)
);

CREATE TABLE IF NOT EXISTS external_reference_chunk (
    external_chunk_id TEXT PRIMARY KEY,
    external_doc_id TEXT NOT NULL REFERENCES external_reference_document(external_doc_id),
    source_id TEXT REFERENCES legal_source_inventory(source_id),
    source_category TEXT,
    provider TEXT,
    title TEXT,
    section_title TEXT,
    chunk_order INTEGER,
    page_no INTEGER,
    chunk_text TEXT,
    chunk_hash TEXT,
    current_version_yn TEXT DEFAULT 'Y',
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    run_id TEXT REFERENCES collection_run(run_id)
);

CREATE TABLE IF NOT EXISTS legal_revision_history (
    revision_id TEXT PRIMARY KEY,
    source_id TEXT REFERENCES legal_source_inventory(source_id),
    document_id TEXT REFERENCES legal_document(document_id),
    change_target_type TEXT,
    change_target_id TEXT,
    change_type TEXT,
    previous_hash TEXT,
    current_hash TEXT,
    previous_effective_date TEXT,
    current_effective_date TEXT,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    run_id TEXT REFERENCES collection_run(run_id),
    note TEXT
);

CREATE TABLE IF NOT EXISTS retrieval_chunk_registry (
    retrieval_chunk_id TEXT PRIMARY KEY,
    source_table TEXT,
    source_pk TEXT,
    source_id TEXT REFERENCES legal_source_inventory(source_id),
    source_name TEXT,
    source_type TEXT,
    source_category TEXT,
    domain_group TEXT,
    chunk_text TEXT,
    chunk_hash TEXT,
    vector_collection TEXT,
    embedding_model TEXT,
    embedding_status TEXT,
    last_embedded_at TIMESTAMP,
    current_version_yn TEXT DEFAULT 'Y',
    run_id TEXT REFERENCES collection_run(run_id)
);

CREATE TABLE IF NOT EXISTS review_basis_mapping (
    mapping_id TEXT PRIMARY KEY,
    review_task_type TEXT,
    source_id TEXT REFERENCES legal_source_inventory(source_id),
    source_name TEXT,
    source_table TEXT,
    source_pk TEXT,
    basis_role TEXT,
    priority INTEGER,
    active_yn TEXT DEFAULT 'Y',
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_legal_document_source_id
ON legal_document(source_id);

CREATE INDEX IF NOT EXISTS idx_legal_article_document_id
ON legal_article(document_id);

CREATE INDEX IF NOT EXISTS idx_legal_article_source_id
ON legal_article(source_id);

CREATE INDEX IF NOT EXISTS idx_legal_attachment_document_id
ON legal_attachment(document_id);

CREATE INDEX IF NOT EXISTS idx_external_chunk_doc_id
ON external_reference_chunk(external_doc_id);

CREATE INDEX IF NOT EXISTS idx_retrieval_chunk_source
ON retrieval_chunk_registry(source_id, source_table);

CREATE INDEX IF NOT EXISTS idx_review_basis_task
ON review_basis_mapping(review_task_type);
"""


def main():
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text(DDL))

    print("[스키마 생성 완료]")
    print("생성 대상 테이블:")
    tables = [
        "legal_source_inventory",
        "collection_run",
        "legal_document",
        "legal_article",
        "legal_attachment",
        "external_reference_document",
        "external_reference_chunk",
        "legal_revision_history",
        "retrieval_chunk_registry",
        "review_basis_mapping",
    ]

    for table in tables:
        print(f" - {table}")


if __name__ == "__main__":
    main()