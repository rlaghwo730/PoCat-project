"""1. 요청이해 — 필수 필드 검증 및 요청 파싱."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# 섹션별 필수 필드 정의
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "document_request": ["document_type", "product_name"],
    "coverage_conditions": ["coverage_limit"],
    "applicant_info": ["applicant_type"],
}

def validate(request: dict) -> None:
    """request 딕셔너리의 필수 필드 존재 여부를 검증한다.

    누락된 필드가 있으면 어떤 필드가 비어 있는지 명확히 명시한 ValueError를 발생시킨다.
    """
    for section, fields in _REQUIRED_FIELDS.items():
        if section not in request:
            raise ValueError(f"요청에 '{section}' 섹션이 없습니다.")
        for field_name in fields:
            if not request[section].get(field_name):
                raise ValueError(
                    f"'{section}.{field_name}' 필드가 비어 있거나 없습니다."
                )


def parse_document_type(request: dict) -> str:
    """요청에서 문서 유형(약관/상품설명서)을 추출한다."""
    return request.get("document_request", {}).get("document_type", "약관")


def parse_product_name(request: dict) -> str:
    """요청에서 상품명을 추출한다."""
    return request.get("document_request", {}).get("product_name", "")


def parse_coverage(request: dict) -> dict:
    """요청에서 보장 조건 섹션을 추출한다."""
    return request.get("coverage_conditions", {})


def check_environment() -> dict:
    """데이터 파이프라인 연결 상태를 점검하고 결과를 반환한다.

    DBClient는 DB_API_URL 환경변수가 없으면 MOCK_MODE로 동작한다.
    MOCK_MODE에서는 missing_req_detector가 실제 규제 DB를 조회하지 못하므로
    MISSING_REQUIREMENT 위반 탐지 정확도가 낮아진다.

    Returns:
        {
            "db_mode": "LIVE" | "MOCK",
            "db_api_url": str | None,
        }
    """
    db_api_url = os.getenv("DB_API_URL")
    db_mode = "LIVE" if db_api_url else "MOCK"

    if db_mode == "MOCK":
        logger.warning(
            "DB_API_URL 환경변수가 설정되지 않았습니다. "
            "DBClient가 MOCK_MODE로 동작하여 "
            "MISSING_REQUIREMENT 탐지 정확도가 낮아집니다."
        )
    else:
        logger.info("DB_API_URL 확인됨 — DBClient LIVE 모드로 동작합니다.")

    return {"db_mode": db_mode, "db_api_url": db_api_url}
