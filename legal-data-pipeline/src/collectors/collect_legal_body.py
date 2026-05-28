import os
import re
import json
import hashlib
from pathlib import Path
from datetime import datetime

import requests
from dotenv import load_dotenv, dotenv_values
from sqlalchemy import text

from db import get_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

LAW_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

OUTPUT_DIR = Path("data/output/legal_body")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_api_key():
    api_key = os.getenv("LAW_API_OC")

    if not api_key:
        env_values = dotenv_values(ENV_PATH)
        api_key = env_values.get("LAW_API_OC")

    if api_key:
        api_key = str(api_key).strip()

    if not api_key or api_key == "여기에_국가법령정보_API_KEY":
        raise ValueError(f"LAW_API_OC 값을 읽지 못했습니다. 확인 경로: {ENV_PATH}")

    return api_key


def make_hash(value):
    if value is None:
        value = ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def clean_text(value):
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value if text_value else None


def get_first_value(obj, keys):
    if not isinstance(obj, dict):
        return None

    for key in keys:
        if key in obj and obj.get(key) not in [None, ""]:
            return clean_text(obj.get(key))

    return None


def collect_text_fields(obj):
    """
    조문/별표 내부에 흩어진 '내용' 계열 텍스트를 재귀적으로 수집한다.
    """
    texts = []

    def walk(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, str):
                    if (
                        "내용" in k
                        or "본문" in k
                        or "제목" in k
                        or "항" in k
                        or "호" in k
                        or "목" in k
                    ):
                        cleaned = clean_text(v)
                        if cleaned:
                            texts.append(cleaned)
                else:
                    walk(v)

        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(obj)

    # 중복 제거, 순서 유지
    unique = []
    seen = set()

    for t in texts:
        if t not in seen:
            unique.append(t)
            seen.add(t)

    return "\n".join(unique)


def fetch_documents():
    engine = get_engine()

    query = text("""
        SELECT
            document_id,
            source_id,
            source_name,
            official_name,
            domain_group,
            target_type,
            law_id,
            mst,
            admrul_serial,
            admrul_id
        FROM legal_document
        WHERE current_version_yn = 'Y'
        ORDER BY source_id;
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()

    return [dict(row) for row in rows]


def call_body_api(doc):
    api_key = get_api_key()

    params = {
        "OC": api_key,
        "target": doc["target_type"],
        "type": "JSON",
    }

    if doc["target_type"] == "law":
        if doc.get("mst"):
            params["MST"] = doc["mst"]
        elif doc.get("law_id"):
            params["ID"] = doc["law_id"]
        else:
            raise ValueError(f"law 식별자 없음: {doc}")

    elif doc["target_type"] == "admrul":
        if doc.get("admrul_serial"):
            params["ID"] = doc["admrul_serial"]
        elif doc.get("admrul_id"):
            params["LID"] = doc["admrul_id"]
        else:
            raise ValueError(f"admrul 식별자 없음: {doc}")

    else:
        raise ValueError(f"지원하지 않는 target_type: {doc['target_type']}")

    response = requests.get(LAW_SERVICE_URL, params=params, timeout=40)
    response.raise_for_status()

    try:
        return response.json()
    except Exception:
        print("[JSON 파싱 실패]")
        print(response.text[:1000])
        raise


def save_raw_body(doc, data):
    safe_name = (
        doc["source_name"]
        .replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
        .replace("·", "_")
        .replace("ㆍ", "_")
    )

    path = OUTPUT_DIR / f"{doc['source_id']}_{safe_name}_body.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return path


def is_article_candidate(obj):
    if not isinstance(obj, dict):
        return False

    article_keys = [
        "조문번호",
        "조문가지번호",
        "조문제목",
        "조문내용",
        "조문여부",
        "조문키",
    ]

    return any(k in obj for k in article_keys)


def find_article_candidates(obj):
    candidates = []

    def walk(value):
        if isinstance(value, dict):
            if is_article_candidate(value):
                candidates.append(value)
                return

            for v in value.values():
                walk(v)

        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(obj)
    return candidates


def extract_articles_from_law(doc, data):
    root = data.get("법령", {})
    article_root = root.get("조문", {})

    if isinstance(article_root, dict):
        candidates = article_root.get("조문단위")
        if candidates is None:
            candidates = find_article_candidates(article_root)
    else:
        candidates = find_article_candidates(article_root)

    return build_article_records(doc, ensure_list(candidates))

def split_admrul_article_text(full_text):
    """
    행정규칙 조문내용이 str 또는 list[str]로 내려오는 경우 조문 단위로 분리한다.

    보정 원칙:
    - list[str] 구조: 각 줄의 시작에 있는 '제n조'만 조문으로 인정
    - str 구조: '제n조(제목)'처럼 제목 괄호가 있는 경우만 조문으로 인정
    - 본문 중간의 '법 제176조', '영 제87조' 같은 참조 조문은 제외
    """
    if not full_text:
        return []

    if isinstance(full_text, list):
        text_value = "\n".join([str(x).strip() for x in full_text if str(x).strip()])

        pattern = re.compile(
            r"(?m)^\s*제\s*(?P<article_no>\d+(?:-\d+)?)\s*조"
            r"(?:\s*의\s*(?P<branch_no>\d+))?"
            r"(?:\s*\((?P<title>[^)]{1,100})\))?"
        )

    else:
        text_value = str(full_text).strip()

        pattern = re.compile(
            r"제\s*(?P<article_no>\d+(?:-\d+)?)\s*조"
            r"(?:\s*의\s*(?P<branch_no>\d+))?"
            r"\s*\((?P<title>[^)]{1,100})\)"
        )

    matches = list(pattern.finditer(text_value))

    if not matches:
        return []

    article_items = []

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text_value)

        article_text = text_value[start:end].strip()

        title = match.group("title")
        if title:
            title = title.strip()

        article_items.append(
            {
                "조문번호": match.group("article_no"),
                "조문가지번호": match.group("branch_no"),
                "조문제목": title,
                "조문내용": article_text,
            }
        )

    return article_items

def extract_articles_from_admrul(doc, data):
    root = data.get("AdmRulService", {})
    article_root = root.get("조문내용")

    # Case 1. 조문내용이 str 또는 list[str]로 내려오는 경우
    if isinstance(article_root, (str, list)):
        candidates = split_admrul_article_text(article_root)
        print(f"  [admrul 조문 문자열/list 분리] {doc['source_id']} 후보 {len(candidates)}건")
        return build_article_records(doc, candidates)

    # Case 2. 조문내용이 dict/list[dict] 구조로 내려오는 경우
    candidates = find_article_candidates(article_root)

    if not candidates and isinstance(article_root, dict):
        candidates = [article_root]

    print(f"  [admrul 조문 구조 분리] {doc['source_id']} 후보 {len(candidates)}건")
    return build_article_records(doc, ensure_list(candidates))


def build_article_records(doc, article_items):
    records = []
    now = datetime.now()

    for idx, item in enumerate(article_items, start=1):
        if not isinstance(item, dict):
            continue

        article_no = get_first_value(
            item,
            ["조문번호", "조번호", "articleNo"],
        )

        article_branch_no = get_first_value(
            item,
            ["조문가지번호", "가지번호", "articleBranchNo"],
        )

        article_title = get_first_value(
            item,
            ["조문제목", "조제목", "articleTitle"],
        )

        article_text = get_first_value(
            item,
            ["조문내용", "본문", "articleText"],
        )

        if not article_text:
            article_text = collect_text_fields(item)

        if not article_text:
            continue

        article_id = f"ART_{doc['document_id']}_{idx:04d}"

        records.append(
            {
                "article_id": article_id,
                "document_id": doc["document_id"],
                "source_id": doc["source_id"],
                "source_name": doc["source_name"],
                "official_name": doc["official_name"],
                "target_type": doc["target_type"],
                "article_no": article_no,
                "article_branch_no": article_branch_no,
                "article_title": article_title,
                "article_text": article_text,
                "article_effective_date": None,
                "article_revision_type": None,
                "article_change_yn": None,
                "article_order": idx,
                "article_hash": make_hash(article_text),
                "current_version_yn": "Y",
                "collected_at": now,
                "run_id": None,
            }
        )

    return records


def is_attachment_candidate(obj):
    if not isinstance(obj, dict):
        return False

    attachment_keys = [
        "별표번호",
        "별표가지번호",
        "별표구분",
        "별표제목",
        "별표서식파일링크",
        "별표PDF파일링크",
        "첨부파일명",
        "첨부파일링크",
        "서식파일링크",
        "pdf",
        "hwp",
    ]

    return any(k in obj for k in attachment_keys)


def find_attachment_candidates(obj):
    candidates = []

    def walk(value):
        if isinstance(value, dict):
            if is_attachment_candidate(value):
                candidates.append(value)

            for v in value.values():
                walk(v)

        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(obj)
    return candidates


def extract_attachments_from_law(doc, data):
    root = data.get("법령", {})

    candidates = []
    for key in ["별표", "첨부파일", "서식"]:
        if key in root:
            candidates.extend(find_attachment_candidates(root.get(key)))

    return build_attachment_records(doc, candidates)


def extract_attachments_from_admrul(doc, data):
    root = data.get("AdmRulService", {})

    candidates = []
    for key in ["별표", "첨부파일"]:
        if key in root:
            candidates.extend(find_attachment_candidates(root.get(key)))

    return build_attachment_records(doc, candidates)


def build_attachment_records(doc, attachment_items):
    records = []
    now = datetime.now()

    for idx, item in enumerate(attachment_items, start=1):
        if not isinstance(item, dict):
            continue

        attachment_title = get_first_value(
            item,
            [
                "별표제목",
                "첨부파일명",
                "파일명",
                "서식명",
                "attachmentTitle",
            ],
        )

        hwp_link = get_first_value(
            item,
            [
                "별표서식파일링크",
                "서식파일링크",
                "hwp_link",
                "hwpLink",
            ],
        )

        pdf_link = get_first_value(
            item,
            [
                "별표PDF파일링크",
                "PDF파일링크",
                "pdf_link",
                "pdfLink",
            ],
        )

        extra_file_link = get_first_value(
            item,
            [
                "첨부파일링크",
                "파일링크",
                "link",
                "url",
            ],
        )

        attachment_text = collect_text_fields(item)

        if not attachment_title and not hwp_link and not pdf_link and not extra_file_link:
            continue

        attachment_id = f"ATT_{doc['document_id']}_{idx:04d}"

        hash_base = json.dumps(item, ensure_ascii=False, sort_keys=True)

        records.append(
            {
                "attachment_id": attachment_id,
                "document_id": doc["document_id"],
                "source_id": doc["source_id"],
                "source_name": doc["source_name"],
                "official_name": doc["official_name"],
                "target_type": doc["target_type"],
                "attachment_no": get_first_value(item, ["별표번호", "첨부번호"]),
                "attachment_branch_no": get_first_value(item, ["별표가지번호", "첨부가지번호"]),
                "attachment_type": get_first_value(item, ["별표구분", "첨부구분", "파일구분"]),
                "attachment_title": attachment_title,
                "hwp_link": hwp_link,
                "pdf_link": pdf_link,
                "image_link": get_first_value(item, ["이미지파일링크", "imageLink"]),
                "extra_file_name": get_first_value(item, ["첨부파일명", "파일명"]),
                "extra_file_link": extra_file_link,
                "attachment_text": attachment_text,
                "attachment_hash": make_hash(hash_base),
                "file_path": None,
                "download_status": "metadata_only",
                "current_version_yn": "Y",
                "collected_at": now,
                "run_id": None,
            }
        )

    return records


def upsert_articles(records):
    if not records:
        return

    engine = get_engine()

    sql = text("""
        INSERT INTO legal_article (
            article_id,
            document_id,
            source_id,
            source_name,
            official_name,
            target_type,
            article_no,
            article_branch_no,
            article_title,
            article_text,
            article_effective_date,
            article_revision_type,
            article_change_yn,
            article_order,
            article_hash,
            current_version_yn,
            collected_at,
            run_id
        )
        VALUES (
            :article_id,
            :document_id,
            :source_id,
            :source_name,
            :official_name,
            :target_type,
            :article_no,
            :article_branch_no,
            :article_title,
            :article_text,
            :article_effective_date,
            :article_revision_type,
            :article_change_yn,
            :article_order,
            :article_hash,
            :current_version_yn,
            :collected_at,
            :run_id
        )
        ON CONFLICT (article_id)
        DO UPDATE SET
            article_no = EXCLUDED.article_no,
            article_branch_no = EXCLUDED.article_branch_no,
            article_title = EXCLUDED.article_title,
            article_text = EXCLUDED.article_text,
            article_hash = EXCLUDED.article_hash,
            collected_at = EXCLUDED.collected_at;
    """)

    with engine.begin() as conn:
        for record in records:
            conn.execute(sql, record)


def upsert_attachments(records):
    if not records:
        return

    engine = get_engine()

    sql = text("""
        INSERT INTO legal_attachment (
            attachment_id,
            document_id,
            source_id,
            source_name,
            official_name,
            target_type,
            attachment_no,
            attachment_branch_no,
            attachment_type,
            attachment_title,
            hwp_link,
            pdf_link,
            image_link,
            extra_file_name,
            extra_file_link,
            attachment_text,
            attachment_hash,
            file_path,
            download_status,
            current_version_yn,
            collected_at,
            run_id
        )
        VALUES (
            :attachment_id,
            :document_id,
            :source_id,
            :source_name,
            :official_name,
            :target_type,
            :attachment_no,
            :attachment_branch_no,
            :attachment_type,
            :attachment_title,
            :hwp_link,
            :pdf_link,
            :image_link,
            :extra_file_name,
            :extra_file_link,
            :attachment_text,
            :attachment_hash,
            :file_path,
            :download_status,
            :current_version_yn,
            :collected_at,
            :run_id
        )
        ON CONFLICT (attachment_id)
        DO UPDATE SET
            attachment_title = EXCLUDED.attachment_title,
            hwp_link = EXCLUDED.hwp_link,
            pdf_link = EXCLUDED.pdf_link,
            image_link = EXCLUDED.image_link,
            extra_file_name = EXCLUDED.extra_file_name,
            extra_file_link = EXCLUDED.extra_file_link,
            attachment_text = EXCLUDED.attachment_text,
            attachment_hash = EXCLUDED.attachment_hash,
            download_status = EXCLUDED.download_status,
            collected_at = EXCLUDED.collected_at;
    """)

    with engine.begin() as conn:
        for record in records:
            conn.execute(sql, record)


def clear_existing_body_tables():
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM legal_article;"))
        conn.execute(text("DELETE FROM legal_attachment;"))

    print("[초기화 완료] legal_article / legal_attachment")


def main():
    clear_existing_body_tables()

    docs = fetch_documents()

    print("[상세 본문 수집 대상]")
    print(f"- 총 문서 수: {len(docs)}")
    print(f"- law: {sum(1 for d in docs if d['target_type'] == 'law')}")
    print(f"- admrul: {sum(1 for d in docs if d['target_type'] == 'admrul')}")

    total_articles = 0
    total_attachments = 0
    failed = []

    for idx, doc in enumerate(docs, start=1):
        print("\n" + "=" * 80)
        print(f"[{idx}/{len(docs)}] {doc['source_id']} | {doc['source_name']} | {doc['target_type']}")

        try:
            data = call_body_api(doc)
            raw_path = save_raw_body(doc, data)

            if doc["target_type"] == "law":
                articles = extract_articles_from_law(doc, data)
                attachments = extract_attachments_from_law(doc, data)
            elif doc["target_type"] == "admrul":
                articles = extract_articles_from_admrul(doc, data)
                attachments = extract_attachments_from_admrul(doc, data)
            else:
                articles = []
                attachments = []

            upsert_articles(articles)
            upsert_attachments(attachments)

            total_articles += len(articles)
            total_attachments += len(attachments)

            print(f"- raw 저장: {raw_path}")
            print(f"- 조문 적재: {len(articles)}건")
            print(f"- 첨부/별표 적재: {len(attachments)}건")

        except Exception as e:
            print(f"[ERROR] {doc['source_id']} | {doc['source_name']} | {e}")
            failed.append((doc["source_id"], doc["source_name"], str(e)))

    print("\n" + "=" * 80)
    print("[상세 본문 수집 완료]")
    print(f"- 총 조문 적재: {total_articles}건")
    print(f"- 총 첨부/별표 적재: {total_attachments}건")
    print(f"- 실패: {len(failed)}건")

    if failed:
        print("\n[실패 목록]")
        for row in failed:
            print(row)


if __name__ == "__main__":
    main()