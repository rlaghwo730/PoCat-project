import os
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
load_dotenv(dotenv_path=ENV_PATH)

LAW_SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"

OUTPUT_DIR = Path("data/output/legal_api")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


SEARCH_QUERY_OVERRIDE = {
    "상법 제4편 보험": "상법",
}


EXPECTED_OFFICIAL_NAME = {
    "상법 제4편 보험": "상법",
}


def get_api_key():
    # 1차: os 환경변수에서 확인
    api_key = os.getenv("LAW_API_OC")

    # 2차: .env 파일을 직접 읽어서 확인
    if not api_key:
        env_values = dotenv_values(ENV_PATH)
        api_key = env_values.get("LAW_API_OC")

    if api_key:
        api_key = str(api_key).strip()

    if not api_key or api_key == "여기에_국가법령정보_API_KEY":
        raise ValueError(
            f"LAW_API_OC 값을 읽지 못했습니다. 확인 경로: {ENV_PATH}"
        )

    return api_key

def make_hash(value):
    if value is None:
        value = ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def normalize(value):
    if value is None:
        return ""
    return (
        str(value)
        .replace(" ", "")
        .replace("ㆍ", "·")
        .replace("·", "")
        .replace("「", "")
        .replace("」", "")
        .strip()
    )


def get_first_value(item, keys):
    for key in keys:
        if key in item and item.get(key) not in [None, ""]:
            return str(item.get(key)).strip()
    return None


def fetch_active_api_sources():
    engine = get_engine()

    query = text("""
        SELECT
            source_id,
            source_name,
            domain_group,
            collection_channel,
            target_type,
            source_category,
            provider,
            priority,
            load_status
        FROM legal_source_inventory
        WHERE status = 'active'
          AND collection_channel IN ('law_api', 'admrul_api')
        ORDER BY source_id;
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()

    return [dict(row) for row in rows]


def call_law_search(source_name, target_type):
    api_key = get_api_key()
    query_name = SEARCH_QUERY_OVERRIDE.get(source_name, source_name)

    params = {
        "OC": api_key,
        "target": target_type,
        "type": "JSON",
        "query": query_name,
        "display": 100,
    }

    response = requests.get(LAW_SEARCH_URL, params=params, timeout=30)
    response.raise_for_status()

    try:
        return response.json()
    except Exception:
        print("[JSON 파싱 실패]")
        print(response.text[:1000])
        raise


def has_document_identity(obj):
    name_keys = [
        "법령명한글",
        "법령명",
        "행정규칙명",
        "행정규칙명칭",
        "admRulNm",
        "lawNm",
    ]

    id_keys = [
        "법령ID",
        "MST",
        "행정규칙일련번호",
        "행정규칙ID",
        "admrulSeq",
        "admrulId",
    ]

    return any(k in obj for k in name_keys) or any(k in obj for k in id_keys)


def extract_items_from_search_response(data):
    """
    핵심 보정:
    - 검색 결과가 list로 오든 dict 하나로 오든 모두 후보로 수집
    - dict 자체에 법령명/행정규칙명/ID가 있으면 그 dict를 후보로 추가
    """

    candidates = []

    def walk(obj):
        if isinstance(obj, dict):
            if has_document_identity(obj):
                candidates.append(obj)

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    # 중복 제거
    unique = []
    seen = set()

    for item in candidates:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            unique.append(item)
            seen.add(key)

    return unique


def get_candidate_name(item):
    return get_first_value(
        item,
        [
            "법령명한글",
            "법령명",
            "행정규칙명",
            "행정규칙명칭",
            "admRulNm",
            "lawNm",
        ],
    )


def pick_best_item(source_name, items):
    if not items:
        return None

    expected_name = EXPECTED_OFFICIAL_NAME.get(source_name, source_name)
    expected_norm = normalize(expected_name)

    # 짧은 법령명은 포함관계 매칭 금지
    # 예: "상법"이 "공무원 재해보상법"에 포함되어 잘못 매칭되는 문제 방지
    exact_only_names = {"상법", "민법", "의료법"}
    exact_only = expected_name in exact_only_names

    scored = []

    for item in items:
        candidate_name = get_candidate_name(item)
        candidate_norm = normalize(candidate_name)

        score = 0

        if candidate_norm == expected_norm:
            score = 100
        elif not exact_only and candidate_norm.startswith(expected_norm):
            score = 80
        elif not exact_only and expected_norm in candidate_norm:
            score = 60
        elif not exact_only and candidate_norm in expected_norm:
            score = 40

        scored.append((score, candidate_name, item))

    scored = sorted(scored, key=lambda x: x[0], reverse=True)

    best_score, best_name, best_item = scored[0]

    if exact_only:
        if best_score != 100:
            print("[WARN] 짧은 법령명 exact match 실패")
            print(f"- expected: {expected_name}")
            print("- 후보명:")
            for score, name, _ in scored[:10]:
                print(f"  score={score} | {name}")
            return None
        return best_item

    if best_score < 60:
        print("[WARN] 신뢰 가능한 매칭 후보 없음")
        print(f"- expected: {expected_name}")
        print("- 후보명:")
        for score, name, _ in scored[:10]:
            print(f"  score={score} | {name}")
        return None

    return best_item


def build_document_record(source, selected_item, raw_response):
    official_name = get_candidate_name(selected_item) or source["source_name"]

    law_id = get_first_value(selected_item, ["법령ID", "lawId", "ID"])
    mst = get_first_value(selected_item, ["MST", "mst"])

    admrul_serial = get_first_value(
        selected_item,
        ["행정규칙일련번호", "admrulSeq", "ADM_RUL_SEQ"],
    )

    admrul_id = get_first_value(
        selected_item,
        ["행정규칙ID", "admrulId", "ADM_RUL_ID"],
    )

    ministry = get_first_value(
        selected_item,
        ["소관부처명", "소관부처", "부처명", "orgName"],
    )

    effective_date = get_first_value(
        selected_item,
        ["시행일자", "시행일", "efYd"],
    )

    promulgation_date = get_first_value(
        selected_item,
        ["공포일자", "발령일자", "ancYd"],
    )

    revision_type = get_first_value(
        selected_item,
        ["제개정구분명", "개정구분", "revisionType"],
    )

    document_id = f"DOC_{source['source_id']}"

    if source["target_type"] == "law":
        body_fetch_method = "lawService_MST_or_ID"
    else:
        body_fetch_method = "admrulService_ID_or_LID"

    raw_for_hash = json.dumps(raw_response, ensure_ascii=False, sort_keys=True)

    return {
        "document_id": document_id,
        "source_id": source["source_id"],
        "source_name": source["source_name"],
        "official_name": official_name,
        "domain_group": source["domain_group"],
        "target_type": source["target_type"],
        "law_id": law_id,
        "mst": mst,
        "admrul_serial": admrul_serial,
        "admrul_id": admrul_id,
        "law_or_rule_type": source["source_category"],
        "ministry": ministry,
        "effective_date": effective_date,
        "promulgation_date": promulgation_date,
        "issue_date": promulgation_date,
        "revision_type": revision_type,
        "body_fetch_method": body_fetch_method,
        "source_url": LAW_SEARCH_URL,
        "document_hash": make_hash(raw_for_hash),
        "current_version_yn": "Y",
        "collected_at": datetime.now(),
        "run_id": None,
    }


def upsert_legal_document(records):
    if not records:
        print("[WARN] upsert 대상 legal_document 레코드가 없습니다.")
        return

    engine = get_engine()

    sql = text("""
        INSERT INTO legal_document (
            document_id,
            source_id,
            source_name,
            official_name,
            domain_group,
            target_type,
            law_id,
            mst,
            admrul_serial,
            admrul_id,
            law_or_rule_type,
            ministry,
            effective_date,
            promulgation_date,
            issue_date,
            revision_type,
            body_fetch_method,
            source_url,
            document_hash,
            current_version_yn,
            collected_at,
            run_id
        )
        VALUES (
            :document_id,
            :source_id,
            :source_name,
            :official_name,
            :domain_group,
            :target_type,
            :law_id,
            :mst,
            :admrul_serial,
            :admrul_id,
            :law_or_rule_type,
            :ministry,
            :effective_date,
            :promulgation_date,
            :issue_date,
            :revision_type,
            :body_fetch_method,
            :source_url,
            :document_hash,
            :current_version_yn,
            :collected_at,
            :run_id
        )
        ON CONFLICT (document_id)
        DO UPDATE SET
            source_id = EXCLUDED.source_id,
            source_name = EXCLUDED.source_name,
            official_name = EXCLUDED.official_name,
            domain_group = EXCLUDED.domain_group,
            target_type = EXCLUDED.target_type,
            law_id = EXCLUDED.law_id,
            mst = EXCLUDED.mst,
            admrul_serial = EXCLUDED.admrul_serial,
            admrul_id = EXCLUDED.admrul_id,
            law_or_rule_type = EXCLUDED.law_or_rule_type,
            ministry = EXCLUDED.ministry,
            effective_date = EXCLUDED.effective_date,
            promulgation_date = EXCLUDED.promulgation_date,
            issue_date = EXCLUDED.issue_date,
            revision_type = EXCLUDED.revision_type,
            body_fetch_method = EXCLUDED.body_fetch_method,
            source_url = EXCLUDED.source_url,
            document_hash = EXCLUDED.document_hash,
            current_version_yn = EXCLUDED.current_version_yn,
            collected_at = EXCLUDED.collected_at,
            run_id = EXCLUDED.run_id;
    """)

    with engine.begin() as conn:
        for record in records:
            conn.execute(sql, record)


def save_raw_response(source_id, source_name, data):
    safe_name = (
        source_name
        .replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
        .replace("·", "_")
        .replace("ㆍ", "_")
    )

    path = OUTPUT_DIR / f"{source_id}_{safe_name}.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return path


def main():
    sources = fetch_active_api_sources()

    print("[API 수집 대상]")
    print(f"- 총 대상 수: {len(sources)}")
    print(f"- law_api: {sum(1 for s in sources if s['collection_channel'] == 'law_api')}")
    print(f"- admrul_api: {sum(1 for s in sources if s['collection_channel'] == 'admrul_api')}")

    records = []
    failed = []

    for idx, source in enumerate(sources, start=1):
        source_id = source["source_id"]
        source_name = source["source_name"]
        target_type = source["target_type"]

        print("\n" + "=" * 80)
        print(f"[{idx}/{len(sources)}] {source_id} | {source_name} | target={target_type}")

        try:
            data = call_law_search(source_name, target_type)
            raw_path = save_raw_response(source_id, source_name, data)

            items = extract_items_from_search_response(data)
            selected = pick_best_item(source_name, items)

            print(f"- 검색 후보 수: {len(items)}")
            print(f"- raw 저장: {raw_path}")

            if selected is None:
                print("[WARN] 선택된 검색 결과 없음")
                failed.append((source_id, source_name, "NO_RELIABLE_SEARCH_RESULT"))
                continue

            record = build_document_record(source, selected, data)
            records.append(record)

            print(f"- official_name: {record['official_name']}")
            print(f"- law_id: {record['law_id']}")
            print(f"- mst: {record['mst']}")
            print(f"- admrul_serial: {record['admrul_serial']}")
            print(f"- admrul_id: {record['admrul_id']}")

        except Exception as e:
            print(f"[ERROR] {source_id} | {source_name} | {e}")
            failed.append((source_id, source_name, str(e)))

    upsert_legal_document(records)

    print("\n" + "=" * 80)
    print("[수집 완료 요약]")
    print(f"- legal_document 적재 성공: {len(records)}건")
    print(f"- 실패: {len(failed)}건")

    if failed:
        print("\n[실패 목록]")
        for item in failed:
            print(item)


if __name__ == "__main__":
    main()