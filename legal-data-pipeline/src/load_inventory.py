from pathlib import Path
from datetime import datetime

import pandas as pd
from sqlalchemy import text

from db import get_engine


EXCEL_PATH = Path("data/input/legal_inventory.xlsx")


def clean_value(value):
    if pd.isna(value):
        return None
    return str(value).strip()


def infer_source_scope(collection_grade, collection_channel):
    grade = clean_value(collection_grade)
    channel = clean_value(collection_channel)

    if grade in ["A", "B", "A-LOADABLE", "B-LOADABLE", "B-LOADABLE-R"]:
        return "api_legal"

    if grade in ["D", "D-EXTERNAL"]:
        return "external_reference"

    if grade in ["C"]:
        return "external_or_attachment_candidate"

    if channel and ("협회" in channel or "금감원" in channel or "금융위" in channel or "웹" in channel):
        return "external_reference"

    return "candidate"


def infer_collection_channel(expected_channel):
    channel = clean_value(expected_channel)

    if not channel:
        return "unknown"

    if "법령 API" in channel or "국가법령정보센터 법령" in channel:
        return "law_api"

    if "행정규칙 API" in channel or "국가법령정보센터 행정규칙" in channel:
        return "admrul_api"

    if "PDF" in channel or "첨부" in channel:
        return "fixed_file_or_attachment"

    if "웹" in channel or "협회" in channel or "금감원" in channel or "금융위" in channel:
        return "manual_registry"

    return "manual_review"


def infer_target_type(source_type, expected_channel):
    source_type = clean_value(source_type)
    channel = clean_value(expected_channel)

    if channel and "행정규칙" in channel:
        return "admrul"

    if channel and "법령" in channel:
        return "law"

    if source_type in ["법률", "시행령", "시행규칙"]:
        return "law"

    if source_type in ["행정규칙", "고시"]:
        return "admrul"

    if source_type in ["표준문서", "서식/표준문서", "가이드라인", "보도자료", "외부자료"]:
        return "external"

    return "candidate"


def infer_status(collection_grade):
    grade = clean_value(collection_grade)

    if grade in ["A", "B", "A-LOADABLE", "B-LOADABLE", "B-LOADABLE-R"]:
        return "active"

    if grade in ["D", "D-EXTERNAL"]:
        return "external_active"

    if grade in ["C"]:
        return "hold"

    if grade in ["E", "EXCLUDED"]:
        return "excluded"

    return "review"


def normalize_load_status(collection_grade):
    grade = clean_value(collection_grade)

    mapping = {
        "A": "A-LOADABLE",
        "B": "B-LOADABLE",
        "C": "C-PARTIAL",
        "D": "D-EXTERNAL",
        "E": "EXCLUDED",
    }

    return mapping.get(grade, grade or "UNKNOWN")


def build_inventory_dataframe():
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"엑셀 파일이 없습니다: {EXCEL_PATH}")

    df_inv = pd.read_excel(EXCEL_PATH, sheet_name="01. 데이터 인벤토리(안)")
    df_check = pd.read_excel(EXCEL_PATH, sheet_name="02. 수집가능성 점검")

    required_inv_cols = [
        "No",
        "그룹",
        "검토대상(안)",
        "유형",
        "관련성",
        "우선순위",
        "주요 활용 목적",
        "Agent 활용 기능",
        "왜 필요한가",
        "비고",
    ]

    required_check_cols = [
        "No",
        "검토대상(안)",
        "예상 수집 채널",
        "수집가능성 등급",
        "개정추적 가능성",
        "확인 필요 사항",
        "출처/조회 URL",
    ]

    for col in required_inv_cols:
        if col not in df_inv.columns:
            raise ValueError(f"01 시트에 필요한 컬럼이 없습니다: {col}")

    for col in required_check_cols:
        if col not in df_check.columns:
            raise ValueError(f"02 시트에 필요한 컬럼이 없습니다: {col}")

    df = df_inv.merge(
        df_check[
            [
                "No",
                "검토대상(안)",
                "예상 수집 채널",
                "수집가능성 등급",
                "개정추적 가능성",
                "확인 필요 사항",
                "출처/조회 URL",
            ]
        ],
        on=["No", "검토대상(안)"],
        how="left",
    )

    rows = []

    for _, row in df.iterrows():
        no = int(row["No"])
        source_name = clean_value(row["검토대상(안)"])
        source_type = clean_value(row["유형"])
        expected_channel = clean_value(row["예상 수집 채널"])
        collection_grade = clean_value(row["수집가능성 등급"])

        source_id = f"SRC_{no:04d}"

        note_parts = [
            f"관련성: {clean_value(row['관련성'])}",
            f"활용 목적: {clean_value(row['주요 활용 목적'])}",
            f"필요 사유: {clean_value(row['왜 필요한가'])}",
            f"확인 필요: {clean_value(row['확인 필요 사항'])}",
            f"원본 비고: {clean_value(row['비고'])}",
        ]

        note = " | ".join([part for part in note_parts if "None" not in part])

        rows.append(
            {
                "source_id": source_id,
                "source_name": source_name,
                "domain_group": clean_value(row["그룹"]),
                "source_scope": infer_source_scope(collection_grade, expected_channel),
                "collection_owner": "C",
                "collection_channel": infer_collection_channel(expected_channel),
                "target_type": infer_target_type(source_type, expected_channel),
                "source_category": source_type,
                "provider": clean_value(row["출처/조회 URL"]),
                "priority": int(row["우선순위"]) if not pd.isna(row["우선순위"]) else None,
                "status": infer_status(collection_grade),
                "load_status": normalize_load_status(collection_grade),
                "note": note,
                "updated_at": datetime.now(),
            }
        )

    return pd.DataFrame(rows)


def upsert_inventory(df):
    engine = get_engine()

    sql = text(
        """
        INSERT INTO legal_source_inventory (
            source_id,
            source_name,
            domain_group,
            source_scope,
            collection_owner,
            collection_channel,
            target_type,
            source_category,
            provider,
            priority,
            status,
            load_status,
            note,
            updated_at
        )
        VALUES (
            :source_id,
            :source_name,
            :domain_group,
            :source_scope,
            :collection_owner,
            :collection_channel,
            :target_type,
            :source_category,
            :provider,
            :priority,
            :status,
            :load_status,
            :note,
            :updated_at
        )
        ON CONFLICT (source_id)
        DO UPDATE SET
            source_name = EXCLUDED.source_name,
            domain_group = EXCLUDED.domain_group,
            source_scope = EXCLUDED.source_scope,
            collection_owner = EXCLUDED.collection_owner,
            collection_channel = EXCLUDED.collection_channel,
            target_type = EXCLUDED.target_type,
            source_category = EXCLUDED.source_category,
            provider = EXCLUDED.provider,
            priority = EXCLUDED.priority,
            status = EXCLUDED.status,
            load_status = EXCLUDED.load_status,
            note = EXCLUDED.note,
            updated_at = EXCLUDED.updated_at;
        """
    )

    records = df.to_dict(orient="records")

    with engine.begin() as conn:
        for record in records:
            conn.execute(sql, record)


def print_summary(df):
    print("[legal_source_inventory 적재 대상 요약]")
    print(f"- 총 대상 수: {len(df)}")

    print("\n[수집가능성 등급별]")
    print(df["load_status"].value_counts(dropna=False).to_string())

    print("\n[수집 채널별]")
    print(df["collection_channel"].value_counts(dropna=False).to_string())

    print("\n[상태별]")
    print(df["status"].value_counts(dropna=False).to_string())

    print("\n[상위 10개 샘플]")
    cols = [
        "source_id",
        "source_name",
        "source_scope",
        "collection_channel",
        "target_type",
        "load_status",
        "status",
    ]
    print(df[cols].head(10).to_string(index=False))


def main():
    df = build_inventory_dataframe()
    print_summary(df)
    upsert_inventory(df)
    print("\n[DB 적재 완료] legal_source_inventory")


if __name__ == "__main__":
    main()