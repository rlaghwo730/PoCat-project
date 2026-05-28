import re
import zlib
import hashlib
from pathlib import Path
from datetime import datetime

import olefile
from pypdf import PdfReader
from sqlalchemy import text

from db import get_engine


EXTERNAL_DIR = Path("data/external")


EXTERNAL_DOCS = [
    {
        "external_doc_id": "EXTDOC_0001",
        "source_id": "EXT_0001",
        "source_category": "advertisement_guideline",
        "provider": "금융위원회·금융감독원",
        "title": "금융광고규제 가이드라인",
        "document_type": "가이드라인",
        "file_type": "pdf",
        "file_name": "EXT_0001_금융광고규제가이드라인.pdf",
        "collection_method": "local_fixed_file",
        "discovery_method": "manual_registry",
        "update_check_method": "file_hash",
    },
    {
        "external_doc_id": "EXTDOC_0002",
        "source_id": "EXT_0002",
        "source_category": "claim_adjustment_guideline",
        "provider": "한국손해사정사회",
        "title": "손해사정 업무위탁 및 손해사정사 선임 등에 관한 모범규준",
        "document_type": "모범규준",
        "file_type": "pdf",
        "file_name": "EXT_0002_손해사정_모범규준.pdf",
        "collection_method": "local_fixed_file",
        "discovery_method": "manual_registry",
        "update_check_method": "file_hash",
    },
    {
        "external_doc_id": "EXTDOC_0003",
        "source_id": "EXT_0003",
        "source_category": "supervisory_notice",
        "provider": "금융위원회·금융감독원",
        "title": "손해사정 공정성 제고 보도자료",
        "document_type": "보도자료",
        "file_type": "hwp",
        "file_name": "EXT_0003_손해사정_공정성제고_보도자료.hwp",
        "collection_method": "local_fixed_file",
        "discovery_method": "manual_registry",
        "update_check_method": "file_hash",
    },
]


def make_hash(value):
    if value is None:
        value = ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def file_hash(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_text(text_value):
    if not text_value:
        return ""

    text_value = str(text_value)
    text_value = re.sub(r"\s+", " ", text_value)
    text_value = text_value.replace("\x00", " ")
    return text_value.strip()


def extract_pdf_text(path: Path):
    reader = PdfReader(str(path))
    pages = []

    for idx, page in enumerate(reader.pages, start=1):
        text_value = page.extract_text() or ""
        text_value = clean_text(text_value)

        if text_value:
            pages.append(
                {
                    "page_no": idx,
                    "text": text_value,
                }
            )

    return pages


def extract_hwp_text(path: Path):
    """
    HWP 5.x 파일의 BodyText/Section 스트림을 읽어 텍스트를 추출한다.
    완벽한 HWP 파서는 아니지만, 보도자료 텍스트 추출 MVP에는 충분한 경우가 많다.
    """
    if not olefile.isOleFile(str(path)):
        raise ValueError(f"HWP OLE 파일이 아닙니다: {path}")

    hwp = olefile.OleFileIO(str(path))
    body_sections = [
        stream
        for stream in hwp.listdir()
        if stream[0] == "BodyText" and stream[1].startswith("Section")
    ]

    texts = []

    for section in sorted(body_sections, key=lambda x: x[1]):
        raw = hwp.openstream(section).read()

        try:
            unpacked = zlib.decompress(raw, -15)
        except Exception:
            unpacked = raw

        text_value = unpacked.decode("utf-16", errors="ignore")
        text_value = clean_text(text_value)

        if text_value:
            texts.append(text_value)

    merged = "\n".join(texts)

    return [
        {
            "page_no": None,
            "text": merged,
        }
    ]


def split_into_chunks(text_value, max_chars=1200, overlap=150):
    text_value = clean_text(text_value)

    if not text_value:
        return []

    chunks = []
    start = 0
    n = len(text_value)

    while start < n:
        end = min(start + max_chars, n)
        chunk = text_value[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= n:
            break

        start = max(end - overlap, 0)

    return chunks


def build_document_record(meta, path: Path):
    now = datetime.now()

    return {
        "external_doc_id": meta["external_doc_id"],
        "source_id": meta["source_id"],
        "source_category": meta["source_category"],
        "provider": meta["provider"],
        "title": meta["title"],
        "document_type": meta["document_type"],
        "file_type": meta["file_type"],
        "source_url": None,
        "file_url": None,
        "file_path": str(path),
        "published_date": None,
        "effective_date": None,
        "collection_method": meta["collection_method"],
        "discovery_method": meta["discovery_method"],
        "update_check_method": meta["update_check_method"],
        "document_hash": file_hash(path),
        "collection_status": "loaded",
        "collected_at": now,
        "run_id": None,
    }


def build_chunk_records(meta, pages):
    records = []
    now = datetime.now()
    chunk_order = 1

    for page in pages:
        page_no = page.get("page_no")
        text_value = page.get("text", "")

        chunks = split_into_chunks(text_value)

        for chunk in chunks:
            records.append(
                {
                    "external_chunk_id": f"EXTCHUNK_{meta['external_doc_id']}_{chunk_order:04d}",
                    "external_doc_id": meta["external_doc_id"],
                    "source_id": meta["source_id"],
                    "source_category": meta["source_category"],
                    "provider": meta["provider"],
                    "title": meta["title"],
                    "section_title": None,
                    "chunk_order": chunk_order,
                    "page_no": page_no,
                    "chunk_text": chunk,
                    "chunk_hash": make_hash(chunk),
                    "current_version_yn": "Y",
                    "collected_at": now,
                    "run_id": None,
                }
            )
            chunk_order += 1

    return records


def upsert_external_document(record):
    engine = get_engine()

    sql = text("""
        INSERT INTO external_reference_document (
            external_doc_id,
            source_id,
            source_category,
            provider,
            title,
            document_type,
            file_type,
            source_url,
            file_url,
            file_path,
            published_date,
            effective_date,
            collection_method,
            discovery_method,
            update_check_method,
            document_hash,
            collection_status,
            collected_at,
            run_id
        )
        VALUES (
            :external_doc_id,
            :source_id,
            :source_category,
            :provider,
            :title,
            :document_type,
            :file_type,
            :source_url,
            :file_url,
            :file_path,
            :published_date,
            :effective_date,
            :collection_method,
            :discovery_method,
            :update_check_method,
            :document_hash,
            :collection_status,
            :collected_at,
            :run_id
        )
        ON CONFLICT (external_doc_id)
        DO UPDATE SET
            source_id = EXCLUDED.source_id,
            source_category = EXCLUDED.source_category,
            provider = EXCLUDED.provider,
            title = EXCLUDED.title,
            document_type = EXCLUDED.document_type,
            file_type = EXCLUDED.file_type,
            file_path = EXCLUDED.file_path,
            document_hash = EXCLUDED.document_hash,
            collection_status = EXCLUDED.collection_status,
            collected_at = EXCLUDED.collected_at;
    """)

    with engine.begin() as conn:
        conn.execute(sql, record)


def upsert_external_chunks(records):
    if not records:
        return

    engine = get_engine()

    sql = text("""
        INSERT INTO external_reference_chunk (
            external_chunk_id,
            external_doc_id,
            source_id,
            source_category,
            provider,
            title,
            section_title,
            chunk_order,
            page_no,
            chunk_text,
            chunk_hash,
            current_version_yn,
            collected_at,
            run_id
        )
        VALUES (
            :external_chunk_id,
            :external_doc_id,
            :source_id,
            :source_category,
            :provider,
            :title,
            :section_title,
            :chunk_order,
            :page_no,
            :chunk_text,
            :chunk_hash,
            :current_version_yn,
            :collected_at,
            :run_id
        )
        ON CONFLICT (external_chunk_id)
        DO UPDATE SET
            chunk_text = EXCLUDED.chunk_text,
            chunk_hash = EXCLUDED.chunk_hash,
            collected_at = EXCLUDED.collected_at;
    """)

    with engine.begin() as conn:
        for record in records:
            conn.execute(sql, record)


def clear_external_tables():
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM external_reference_chunk;"))
        conn.execute(text("DELETE FROM external_reference_document;"))

    print("[초기화 완료] external_reference_document / external_reference_chunk")


def main():
    clear_external_tables()

    total_chunks = 0
    failed = []

    for meta in EXTERNAL_DOCS:
        path = EXTERNAL_DIR / meta["file_name"]

        print("\n" + "=" * 80)
        print(f"[외부 문서 처리] {meta['source_id']} | {meta['title']}")
        print(f"- 파일 경로: {path}")

        try:
            if not path.exists():
                raise FileNotFoundError(f"파일 없음: {path}")

            if meta["file_type"] == "pdf":
                pages = extract_pdf_text(path)
            elif meta["file_type"] == "hwp":
                pages = extract_hwp_text(path)
            else:
                raise ValueError(f"지원하지 않는 file_type: {meta['file_type']}")

            doc_record = build_document_record(meta, path)
            chunk_records = build_chunk_records(meta, pages)

            upsert_external_document(doc_record)
            upsert_external_chunks(chunk_records)

            total_chunks += len(chunk_records)

            print(f"- 텍스트 페이지/단위 수: {len(pages)}")
            print(f"- chunk 적재 수: {len(chunk_records)}")
            print(f"- document_hash: {doc_record['document_hash'][:12]}...")

        except Exception as e:
            print(f"[ERROR] {meta['source_id']} | {e}")
            failed.append((meta["source_id"], meta["title"], str(e)))

    print("\n" + "=" * 80)
    print("[외부 문서 적재 완료]")
    print(f"- 대상 문서 수: {len(EXTERNAL_DOCS)}")
    print(f"- 총 chunk 수: {total_chunks}")
    print(f"- 실패: {len(failed)}건")

    if failed:
        print("\n[실패 목록]")
        for row in failed:
            print(row)


if __name__ == "__main__":
    main()