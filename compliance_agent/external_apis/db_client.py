"""
DB팀 RAG API 클라이언트.
실제 API 엔드포인트가 제공되면 MOCK_MODE = False로 전환한다.
"""
from __future__ import annotations

import os

MOCK_MODE = os.getenv("DB_API_URL") is None


class DBClient:
    def __init__(self) -> None:
        if not MOCK_MODE:
            self._base_url = os.environ["DB_API_URL"]

    def search(self, query: str, section_type: str) -> list:
        """
        표준약관 벡터DB를 검색해 필수 기재사항 목록을 반환한다.
        MOCK_MODE일 때는 빈 리스트를 반환해 missing_req_detector의 mock을 사용하게 한다.
        """
        if MOCK_MODE:
            return []

        import httpx
        response = httpx.post(
            f"{self._base_url}/search",
            json={"query": query, "section_type": section_type},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json().get("items", [])
