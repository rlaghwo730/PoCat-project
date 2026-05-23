from datetime import datetime
from sqlalchemy import text
from db import get_engine


UPDATE_SQL = text("""
UPDATE legal_source_inventory
SET
    status = :status,
    source_scope = :source_scope,
    collection_channel = :collection_channel,
    target_type = :target_type,
    load_status = :load_status,
    note = CONCAT(COALESCE(note, ''), ' | 최종 MVP 판단: ', :decision_note),
    updated_at = :updated_at
WHERE source_id = :source_id;
""")


INSERT_SQL = text("""
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
    created_at,
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
    :created_at,
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
""")


def main():
    now = datetime.now()
    engine = get_engine()

    status_updates = [
        {
            "source_id": "SRC_0034",
            "status": "hold",
            "source_scope": "excluded_or_hold",
            "collection_channel": "manual_review",
            "target_type": "external",
            "load_status": "HOLD",
            "decision_note": "국가법령정보 API 조회 실패 및 MVP 수집대상 제외/보류",
            "updated_at": now,
        },
        {
            "source_id": "SRC_0036",
            "status": "excluded",
            "source_scope": "excluded",
            "collection_channel": "excluded",
            "target_type": "external",
            "load_status": "EXCLUDED",
            "decision_note": "분쟁조정례는 비정형성이 높아 MVP 자동수집 대상에서 제외",
            "updated_at": now,
        },
        {
            "source_id": "SRC_0054",
            "status": "excluded",
            "source_scope": "excluded",
            "collection_channel": "excluded",
            "target_type": "external",
            "load_status": "EXCLUDED",
            "decision_note": "판례 데이터는 MVP 범위에서 제외",
            "updated_at": now,
        },
        {
            "source_id": "SRC_0055",
            "status": "excluded",
            "source_scope": "excluded",
            "collection_channel": "excluded",
            "target_type": "external",
            "load_status": "EXCLUDED",
            "decision_note": "민원 사례는 키워드 기반 탐색이 필요하므로 MVP 범위에서 제외",
            "updated_at": now,
        },
        {
            "source_id": "SRC_0056",
            "status": "excluded",
            "source_scope": "excluded",
            "collection_channel": "excluded",
            "target_type": "external",
            "load_status": "EXCLUDED",
            "decision_note": "실손의료보험은 손해보험 중심으로 보고 생명보험협회 자료는 후순위 제외",
            "updated_at": now,
        },
        {
            "source_id": "SRC_0057",
            "status": "hold",
            "source_scope": "external_reference",
            "collection_channel": "manual_registry",
            "target_type": "external",
            "load_status": "HOLD",
            "decision_note": "공식 PDF가 아닌 HTML 안내 페이지이므로 PDF 수집 MVP에서는 보류",
            "updated_at": now,
        },
        {
            "source_id": "SRC_0058",
            "status": "hold",
            "source_scope": "external_reference",
            "collection_channel": "manual_registry",
            "target_type": "external",
            "load_status": "HOLD",
            "decision_note": "키워드 기반 검색을 배제하므로 사전 선정 URL만 향후 등록",
            "updated_at": now,
        },
    ]

    external_sources = [
        {
            "source_id": "EXT_0001",
            "source_name": "금융광고규제 가이드라인",
            "domain_group": "9. 표시·광고·온라인 판매 소비자보호",
            "source_scope": "external_reference",
            "collection_owner": "C",
            "collection_channel": "fixed_file_or_attachment",
            "target_type": "external",
            "source_category": "가이드라인",
            "provider": "금융위원회·금융감독원",
            "priority": 1,
            "status": "external_active",
            "load_status": "D-EXTERNAL-FIXED",
            "note": "업로드 PDF 기준 외부 기준자료. 상품설명서·광고성 표현 검토에 활용.",
            "created_at": now,
            "updated_at": now,
        },
        {
            "source_id": "EXT_0002",
            "source_name": "손해사정 업무위탁 및 손해사정사 선임 등에 관한 모범규준",
            "domain_group": "6. 보험금 청구·지급·손해사정·분쟁",
            "source_scope": "external_reference",
            "collection_owner": "C",
            "collection_channel": "fixed_file_or_attachment",
            "target_type": "external",
            "source_category": "모범규준",
            "provider": "한국손해사정사회",
            "priority": 1,
            "status": "external_active",
            "load_status": "D-EXTERNAL-FIXED",
            "note": "업로드 PDF 기준 외부 기준자료. 손해사정사 선임, 위탁, 보험금 지급 절차 검토에 활용.",
            "created_at": now,
            "updated_at": now,
        },
        {
            "source_id": "EXT_0003",
            "source_name": "손해사정 공정성 제고 보도자료",
            "domain_group": "6. 보험금 청구·지급·손해사정·분쟁",
            "source_scope": "external_reference",
            "collection_owner": "C",
            "collection_channel": "fixed_file_or_attachment",
            "target_type": "external",
            "source_category": "보도자료",
            "provider": "금융위원회·금융감독원",
            "priority": 2,
            "status": "external_active",
            "load_status": "D-EXTERNAL-FIXED",
            "note": "업로드 HWP 기준 외부 보조자료. 손해사정 제도개선 배경 설명자료로 활용.",
            "created_at": now,
            "updated_at": now,
        },
    ]

    with engine.begin() as conn:
        for item in status_updates:
            conn.execute(UPDATE_SQL, item)

        for item in external_sources:
            conn.execute(INSERT_SQL, item)

    print("[인벤토리 최종 상태 정정 완료]")
    print(f"- 상태 정정: {len(status_updates)}건")
    print(f"- 외부 고정자료 추가: {len(external_sources)}건")


if __name__ == "__main__":
    main()