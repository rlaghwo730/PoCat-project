import os
import json
from pathlib import Path

import requests
from dotenv import load_dotenv, dotenv_values
from sqlalchemy import text

from db import get_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

LAW_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

OUTPUT_DIR = Path("data/output/legal_body_sample")
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


def fetch_sample_documents():
    """
    law 1건 + admrul 1건만 먼저 상세 조회한다.
    - SRC_0006: 보험업법
    - SRC_0001: 보험업감독규정
    """
    engine = get_engine()

    query = text("""
        SELECT
            document_id,
            source_id,
            source_name,
            official_name,
            target_type,
            law_id,
            mst,
            admrul_serial,
            admrul_id
        FROM legal_document
        WHERE source_id IN ('SRC_0006', 'SRC_0001')
        ORDER BY source_id;
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()

    return [dict(row) for row in rows]


def call_law_body(doc):
    api_key = get_api_key()

    target_type = doc["target_type"]

    params = {
        "OC": api_key,
        "target": target_type,
        "type": "JSON",
    }

    if target_type == "law":
        # 법령 상세는 MST 우선, 없으면 ID 사용
        if doc.get("mst"):
            params["MST"] = doc["mst"]
        elif doc.get("law_id"):
            params["ID"] = doc["law_id"]
        else:
            raise ValueError(f"law 식별자 없음: {doc}")

    elif target_type == "admrul":
        # 행정규칙 상세는 ID 또는 LID 후보가 필요
        # 이전 검색에서 admrul_serial/admrul_id를 확보했으므로 둘 다 테스트 가능
        if doc.get("admrul_serial"):
            params["ID"] = doc["admrul_serial"]
        elif doc.get("admrul_id"):
            params["LID"] = doc["admrul_id"]
        else:
            raise ValueError(f"admrul 식별자 없음: {doc}")

    else:
        raise ValueError(f"지원하지 않는 target_type: {target_type}")

    print("\n" + "=" * 80)
    print(f"[상세 API 호출] {doc['source_id']} | {doc['source_name']} | target={target_type}")
    print(f"- params: {params}")

    response = requests.get(LAW_SERVICE_URL, params=params, timeout=30)
    print(f"- status_code: {response.status_code}")
    print(f"- url: {response.url}")

    response.raise_for_status()

    try:
        data = response.json()
    except Exception:
        print("[JSON 파싱 실패]")
        print(response.text[:1000])
        raise

    return data


def save_response(doc, data):
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

    print(f"- 저장 완료: {path}")

    return path


def print_response_summary(data):
    print("[응답 구조 요약]")
    print(f"- 최상위 타입: {type(data).__name__}")

    if isinstance(data, dict):
        print(f"- 최상위 key: {list(data.keys())}")

        for key, value in data.items():
            if isinstance(value, dict):
                print(f"  - {key}: dict keys={list(value.keys())[:20]}")
            elif isinstance(value, list):
                print(f"  - {key}: list len={len(value)}")
            else:
                print(f"  - {key}: {str(value)[:100]}")


def main():
    docs = fetch_sample_documents()

    print("[샘플 상세 조회 대상]")
    for doc in docs:
        print(
            doc["source_id"],
            doc["source_name"],
            doc["target_type"],
            "law_id=",
            doc["law_id"],
            "mst=",
            doc["mst"],
            "admrul_serial=",
            doc["admrul_serial"],
            "admrul_id=",
            doc["admrul_id"],
        )

    if len(docs) == 0:
        raise RuntimeError("샘플 문서가 없습니다. legal_document 적재 상태를 확인하세요.")

    for doc in docs:
        data = call_law_body(doc)
        save_response(doc, data)
        print_response_summary(data)

    print("\n[샘플 상세 API 호출 완료]")


if __name__ == "__main__":
    main()