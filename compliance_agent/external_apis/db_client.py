"""
C파트 법령규제 파이프라인 산출물(ChromaDB / PostgreSQL)에 연결하는 RAG 클라이언트.

연결 우선순위: ChromaDB → PostgreSQL → 빈 리스트 반환(상위 호출부의 mock fallback 위임)
DB 연결이 불가한 경우 앱이 죽지 않도록 경고 로그와 빈 리스트를 반환한다.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from compliance_agent.models.violation import Severity

logger = logging.getLogger(__name__)

# ── 선택적 의존성 (설치 안 돼있어도 앱이 죽지 않는다) ──────────────────────────
try:
    import chromadb
    from chromadb.config import Settings as _ChromaSettings
    _CHROMADB_AVAILABLE = True
except ImportError:
    _CHROMADB_AVAILABLE = False
    logger.debug("chromadb 미설치 — ChromaDB 검색 비활성화")

try:
    from sentence_transformers import SentenceTransformer as _SentenceTransformer
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    logger.debug("sentence-transformers 미설치 — ChromaDB 검색 비활성화")

try:
    from sqlalchemy import create_engine as _create_engine, text as _sa_text
    _SQLALCHEMY_AVAILABLE = True
except ImportError:
    _SQLALCHEMY_AVAILABLE = False
    logger.debug("sqlalchemy 미설치 — PostgreSQL 검색 비활성화")

# ── 설정 상수 ─────────────────────────────────────────────────────────────────
_DEFAULT_CHROMA_PATH = "data/vector_store/chroma"
_DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
_TOP_K = 10

# section_type → ChromaDB 컬렉션 매핑
# 매핑이 불명확한 경우 _ALL_COLLECTIONS 전체를 대상으로 검색한다
_SECTION_TYPE_TO_COLLECTIONS: dict[str, list[str]] = {
    "legal_article":      ["law_regulation_vectors"],
    "약관":               ["law_regulation_vectors"],
    "legal_attachment":   ["law_attachment_vectors"],
    "external_reference": ["external_reference_vectors"],
    # 상품설명서는 법령 조문 + 외부 가이드라인 모두 참조
    "상품설명서":         ["law_regulation_vectors", "external_reference_vectors"],
}
_ALL_COLLECTIONS: list[str] = [
    "law_regulation_vectors",
    "law_attachment_vectors",
    "external_reference_vectors",
]

# section_type → PostgreSQL chunk_type 매핑
_SECTION_TYPE_TO_CHUNK_TYPES: dict[str, list[str]] = {
    "legal_article":      ["legal_article"],
    "약관":               ["legal_article"],
    "legal_attachment":   ["legal_attachment"],
    "external_reference": ["external_reference"],
    "상품설명서":         ["legal_article", "external_reference"],
}


# ── 반환 타입 ─────────────────────────────────────────────────────────────────
@dataclass
class LegalChunkItem:
    """
    C파트 파이프라인 검색 결과를 missing_req_detector._RequiredItem 인터페이스에 맞게 래핑.

    필수 속성 (missing_req_detector.py 에서 직접 접근):
        item_id, name, keywords, severity, section_types

    추가 속성:
        source, article_no, article_title, chunk_text, chunk_type, score
    """
    item_id: str
    name: str
    keywords: list[str]
    severity: Severity
    section_types: list[str]
    source: str = ""
    article_no: str = ""
    article_title: str = ""
    chunk_text: str = ""
    chunk_type: str = ""
    score: float = 0.0


# ── 환경 감지 ─────────────────────────────────────────────────────────────────
def _chroma_dir() -> Path:
    return Path(os.getenv("CHROMA_DB_PATH", _DEFAULT_CHROMA_PATH))


def _pg_url() -> str | None:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("PGHOST")
    port = os.getenv("PGPORT", "5432")
    db   = os.getenv("PGDATABASE")
    user = os.getenv("PGUSER")
    pw   = os.getenv("PGPASSWORD", "")
    if host and db and user:
        return f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{db}"
    return None


def _resolve_mock_mode() -> bool:
    """ChromaDB 경로 또는 PostgreSQL URL 중 하나라도 사용 가능하면 False."""
    if _CHROMADB_AVAILABLE and _ST_AVAILABLE and _chroma_dir().exists():
        return False
    if _SQLALCHEMY_AVAILABLE and _pg_url():
        return False
    return True


# missing_req_detector.py 가 직접 임포트하는 플래그 — 모듈 로드 시점에 1회 결정
MOCK_MODE: bool = _resolve_mock_mode()

# ── 임베딩 모델 캐시 (프로세스당 1회 로드) ────────────────────────────────────
_model_cache: dict[str, Any] = {}


def _get_model(name: str) -> Any:
    if name not in _model_cache:
        logger.info("SentenceTransformer 모델 로드 중: %s", name)
        _model_cache[name] = _SentenceTransformer(name)
    return _model_cache[name]


# ── 유틸 ──────────────────────────────────────────────────────────────────────
def _extract_keywords(article_title: str, chunk_text: str) -> list[str]:
    """조문 제목과 본문에서 검색 키워드를 추출한다.

    파이프라인에 keywords 필드가 없으므로 article_title + chunk_text에서 최소한으로 구성.
    """
    keywords: list[str] = []

    if article_title:
        keywords.append(article_title)

    # 법령 인용구 「...」 에서 추출 (예: 「보험업법」)
    keywords.extend(re.findall(r'「[^」]{2,20}」', chunk_text[:400])[:3])

    # 한글 4자 이상 단어 — 일반적 조사·어미 제외를 위한 최소 길이 기준
    tokens = re.findall(r'[가-힣]{4,}', chunk_text[:300])
    keywords.extend(tokens[:5])

    # 중복 제거 후 최대 8개
    seen: set[str] = set()
    result: list[str] = []
    for kw in keywords:
        kw = kw.strip()
        if kw and kw not in seen:
            seen.add(kw)
            result.append(kw)
        if len(result) >= 8:
            break
    return result


def _infer_section_types(chunk_type: str, vector_collection: str) -> list[str]:
    """chunk_type / vector_collection으로 section_types를 추론한다.

    법령 조문·별표·외부기준자료 모두 '약관'과 '상품설명서' 검토에 공통 적용된다.
    """
    return ["약관", "상품설명서"]


def _get_collections(section_type: str) -> list[str]:
    """section_type에 해당하는 ChromaDB 컬렉션 목록을 반환한다.

    매핑이 불명확하면 전체 컬렉션을 대상으로 한다 (보수적 탐색).
    """
    return _SECTION_TYPE_TO_COLLECTIONS.get(section_type, _ALL_COLLECTIONS)


# ── ChromaDB 검색 ─────────────────────────────────────────────────────────────
def _search_chroma(query: str, section_type: str) -> list[LegalChunkItem]:
    if not (_CHROMADB_AVAILABLE and _ST_AVAILABLE):
        return []

    chroma_path = _chroma_dir()
    if not chroma_path.exists():
        logger.warning("ChromaDB 경로 없음: %s", chroma_path)
        return []

    try:
        model_name = os.getenv("EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL)
        model = _get_model(model_name)

        client = chromadb.PersistentClient(
            path=str(chroma_path),
            settings=_ChromaSettings(anonymized_telemetry=False),
        )

        items: list[LegalChunkItem] = []

        for col_name in _get_collections(section_type):
            try:
                collection = client.get_collection(col_name)
            except Exception:
                logger.debug("ChromaDB 컬렉션 없음: %s", col_name)
                continue

            embedding = model.encode(
                [query], normalize_embeddings=True
            ).tolist()

            result = collection.query(
                query_embeddings=embedding,
                n_results=_TOP_K,
                include=["documents", "metadatas", "distances"],
            )

            ids       = result.get("ids", [[]])[0]
            documents = result.get("documents", [[]])[0]
            metadatas = result.get("metadatas", [[]])[0]
            distances = result.get("distances", [[]])[0]

            for i, rid in enumerate(ids):
                meta = metadatas[i] if i < len(metadatas) else {}
                doc  = documents[i] if i < len(documents) else ""
                dist = distances[i] if i < len(distances) else 1.0
                items.append(_chroma_to_item(rid, doc, meta, dist))

        return items

    except Exception as exc:
        logger.warning("ChromaDB 검색 실패: %s", exc)
        return []


def _chroma_to_item(
    registry_id: str,
    document: str,
    meta: dict,
    distance: float,
) -> LegalChunkItem:
    article_title    = str(meta.get("article_title", "") or "")
    article_no       = str(meta.get("article_no", "") or "")
    document_title   = str(meta.get("document_title", "") or "")
    chunk_type       = str(meta.get("chunk_type", "") or "")
    vector_collection = str(meta.get("vector_collection", "") or "")

    name = " ".join(filter(None, [document_title, article_no, article_title])) or registry_id

    return LegalChunkItem(
        item_id=registry_id,
        name=name,
        keywords=_extract_keywords(article_title, document),
        severity=Severity.MEDIUM,
        section_types=_infer_section_types(chunk_type, vector_collection),
        source=vector_collection,
        article_no=article_no,
        article_title=article_title,
        chunk_text=document,
        chunk_type=chunk_type,
        score=max(0.0, 1.0 - distance),
    )


# ── PostgreSQL 검색 ───────────────────────────────────────────────────────────
def _search_postgres(query: str, section_type: str) -> list[LegalChunkItem]:
    if not _SQLALCHEMY_AVAILABLE:
        return []

    db_url = _pg_url()
    if not db_url:
        return []

    try:
        engine = _create_engine(db_url, pool_pre_ping=True)

        chunk_types = _SECTION_TYPE_TO_CHUNK_TYPES.get(section_type)
        # 매핑이 없으면 전체 chunk_type 대상 검색 (보수적 탐색)
        if chunk_types:
            type_filter = "AND chunk_type = ANY(:ctypes)"
        else:
            type_filter = ""

        sql = _sa_text(f"""
            SELECT
                registry_id,
                source_id,
                vector_collection,
                document_title,
                chunk_type,
                article_no,
                article_title,
                LEFT(chunk_text, 500) AS chunk_text
            FROM retrieval_chunk_registry
            WHERE
                current_version_yn = 'Y'
                AND (
                    chunk_text    ILIKE :q
                    OR document_title ILIKE :q
                    OR article_title  ILIKE :q
                )
                {type_filter}
            ORDER BY
                CASE
                    WHEN article_title  ILIKE :q THEN 1
                    WHEN document_title ILIKE :q THEN 2
                    ELSE 3
                END
            LIMIT :lim
        """)

        params: dict[str, Any] = {"q": f"%{query}%", "lim": _TOP_K}
        if chunk_types:
            params["ctypes"] = chunk_types

        with engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [_pg_row_to_item(row) for row in rows]

    except Exception as exc:
        logger.warning("PostgreSQL 검색 실패: %s", exc)
        return []


def _pg_row_to_item(row: Any) -> LegalChunkItem:
    registry_id    = str(row.registry_id    or "")
    document_title = str(row.document_title or "")
    article_no     = str(row.article_no     or "")
    article_title  = str(row.article_title  or "")
    chunk_text     = str(row.chunk_text     or "")
    chunk_type     = str(row.chunk_type     or "")
    vector_coll    = str(row.vector_collection or "")

    name = " ".join(filter(None, [document_title, article_no, article_title])) or registry_id

    return LegalChunkItem(
        item_id=registry_id,
        name=name,
        keywords=_extract_keywords(article_title, chunk_text),
        severity=Severity.MEDIUM,
        section_types=_infer_section_types(chunk_type, vector_coll),
        source=vector_coll,
        article_no=article_no,
        article_title=article_title,
        chunk_text=chunk_text,
        chunk_type=chunk_type,
        score=0.0,
    )


# ── 공개 클라이언트 ───────────────────────────────────────────────────────────
class DBClient:
    def __init__(self) -> None:
        if not MOCK_MODE:
            self._base_url = os.environ.get("DB_API_URL", "")

    def search(self, query: str, section_type: str) -> list[LegalChunkItem]:
        """
        C파트 파이프라인 산출물에서 법령 청크를 검색한다.

        검색 우선순위:
          1. ChromaDB (의미 검색)
          2. PostgreSQL retrieval_chunk_registry (키워드 검색 보완)
          3. 둘 다 결과 없음 → 빈 리스트 반환
             → missing_req_detector._fetch_required_items 의 mock fallback 으로 위임

        기존 DBClient.search(query, section_type) 인터페이스를 유지한다.
        """
        items = _search_chroma(query, section_type)
        if items:
            return items

        items = _search_postgres(query, section_type)
        if items:
            return items

        logger.warning(
            "DBClient.search: 결과 없음 — mock fallback 위임 "
            "(query=%r, section_type=%r)",
            query,
            section_type,
        )
        return []
