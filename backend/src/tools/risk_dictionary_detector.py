"""Risk-expression dictionary detector for insurance compliance review.

Dictionary and pattern hits are review signals, not final legal conclusions.
DB failures return an empty list so the workflow can continue in offline or
mock environments.
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

TABLE_NAME = "risk_expression_dictionary_test"

_DEFAULT_COLUMNS = [
    "risk_id",
    "risk_expression_id",
    "expression",
    "normalized_pattern",
    "category",
    "risk_type",
    "semantic_intent",
    "severity",
    "reason",
    "regulatory_basis",
    "regulation",
    "recommended_action",
    "review_action",
    "replacement_guideline",
    "examples",
    "example_phrases",
    "semantic_patterns",
    "related_regex_expressions",
    "description",
    "version",
    "source",
    "source_file",
    "is_active",
]

_CONTEXT_REVIEW_TERMS = (
    "보장하지 않",
    "지급하지 않",
    "해당하지 않",
    "제외",
    "면책",
    "한도",
    "자기부담",
    "공제",
    "조건",
    "약관에서 정한",
)

_SEMANTIC_RULES: tuple[dict[str, Any], ...] = (
    {
        "risk_type": "MISLEADING_COVERAGE",
        "severity": "HIGH",
        "patterns": [
            r"모든\s*.{0,12}(치료비|의료비|진료비).{0,8}보장",
            r"(전부|전액|100\s*%).{0,8}보장",
            r"(제한|한도)\s*없이.{0,8}보장",
        ],
        "reason": "보장 범위를 과장하거나 소비자가 전면 보장으로 오인할 수 있는 표현입니다.",
        "basis": "보험업법 및 실손의료보험 표준약관의 명확한 보장범위 설명 원칙",
        "action": "보장 조건, 한도, 면책 및 자기부담금 적용 여부를 함께 명시하세요.",
    },
    {
        "risk_type": "GUARANTEED_PAYMENT",
        "severity": "HIGH",
        "patterns": [
            r"(반드시|무조건|즉시).{0,8}(지급|보상)",
            r"(청구|신청).{0,8}(즉시|바로).{0,8}(지급|보상)",
            r"어떤\s*경우.{0,8}(지급|보상)",
        ],
        "reason": "보험금 지급 심사와 지급 요건을 생략해 지급이 확정된 것처럼 보일 수 있습니다.",
        "basis": "보험업법상 허위ㆍ과장 설명 금지 및 보험금 지급요건 설명 의무",
        "action": "약관상 지급요건과 심사 절차에 따라 지급된다는 점을 명확히 하세요.",
    },
    {
        "risk_type": "MISSING_LIMIT",
        "severity": "MEDIUM",
        "patterns": [
            r"(부담|공제|한도|제한)\s*없이",
            r"조건\s*없이",
            r"제외\s*없(이|음)",
            r"상시\s*보장",
        ],
        "reason": "한도, 면책, 자기부담금 등 중요 제한사항이 누락된 것으로 오인될 수 있습니다.",
        "basis": "실손의료보험 표준약관 및 상품설명서 중요사항 설명 기준",
        "action": "보장한도, 자기부담금, 면책 및 제외 조건을 같은 문맥에서 설명하세요.",
    },
    {
        "risk_type": "UNSUPPORTED_COMPARATIVE_CLAIM",
        "severity": "MEDIUM",
        "patterns": [
            r"업계\s*최고",
            r"가장\s*유리",
            r"압도적",
            r"최고의\s*실손",
        ],
        "reason": "객관적 근거가 없는 비교ㆍ우월 표현으로 해석될 수 있습니다.",
        "basis": "금융소비자보호법상 부당권유 및 오인 유발 표현 제한",
        "action": "비교 근거와 기준 시점을 제시하거나 중립적인 설명으로 바꾸세요.",
    },
)


def _db_url() -> str | None:
    for key in ("DATABASE_URL", "NEON_DATABASE_URL", "POSTGRES_URL", "DB_API_URL"):
        value = os.getenv(key)
        if value:
            return value.replace("postgresql+psycopg2://", "postgresql://", 1)

    host = os.getenv("PGHOST")
    db = os.getenv("PGDATABASE")
    user = os.getenv("PGUSER")
    if host and db and user:
        port = os.getenv("PGPORT", "5432")
        password = quote(os.getenv("PGPASSWORD", ""), safe="")
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    host = os.getenv("POSTGRES_HOST")
    db = os.getenv("POSTGRES_DB")
    user = os.getenv("POSTGRES_USER")
    if host and db and user:
        port = os.getenv("POSTGRES_PORT", "5432")
        password = quote(os.getenv("POSTGRES_PASSWORD", ""), safe="")
        sslmode = os.getenv("POSTGRES_SSLMODE")
        url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
        return f"{url}?sslmode={sslmode}" if sslmode else url
    return None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _needs_context_review(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 60): min(len(text), end + 60)]
    return any(term in window for term in _CONTEXT_REVIEW_TERMS)


def _safe_jsonish(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)


def _is_active_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "t", "1", "y", "yes", "active"}


@lru_cache(maxsize=1)
def _load_dictionary_rows() -> tuple[dict[str, Any], ...]:
    db_url = _db_url()
    if not db_url:
        logger.warning("Risk dictionary DB URL is not configured; dictionary detector disabled.")
        return ()

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except Exception as exc:
        logger.warning("psycopg2 is unavailable; dictionary detector disabled: %s", exc)
        return ()

    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = %s
                    """,
                    (TABLE_NAME,),
                )
                available = {row[0] for row in cur.fetchall()}

            if not available or "expression" not in available:
                logger.warning(
                    "Risk dictionary table %s is missing or has no expression column.",
                    TABLE_NAME,
                )
                return ()

            selected = [col for col in _DEFAULT_COLUMNS if col in available]
            sql = f"""
                SELECT {", ".join(selected)}
                FROM {TABLE_NAME}
            """
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql)
                rows = [dict(row) for row in cur.fetchall()]

            if "is_active" in available:
                rows = [row for row in rows if _is_active_value(row.get("is_active"))]
            return tuple(rows)

    except Exception as exc:
        logger.warning("Risk dictionary DB lookup failed; falling back to empty findings: %s", exc)
        return ()


def _row_to_finding(row: dict[str, Any], expression: str, needs_review: bool) -> dict:
    reason = row.get("reason") or row.get("description") or ""
    action = row.get("recommended_action") or row.get("review_action") or ""
    basis = row.get("regulatory_basis") or row.get("regulation") or ""
    return {
        "risk_id": str(row.get("risk_id") or row.get("risk_expression_id") or expression),
        "matched_expression": expression,
        "risk_type": str(row.get("risk_type") or row.get("category") or "UNKNOWN"),
        "severity": str(row.get("severity") or "MEDIUM").upper(),
        "reason": str(reason),
        "regulatory_basis": str(basis),
        "recommended_action": str(action),
        "replacement_guideline": str(row.get("replacement_guideline") or action),
        "examples": _safe_jsonish(row.get("examples") or row.get("example_phrases")),
        "semantic_patterns": _safe_jsonish(
            row.get("semantic_patterns")
            or row.get("related_regex_expressions")
            or row.get("normalized_pattern")
        ),
        "source": str(row.get("source") or row.get("source_file") or TABLE_NAME),
        "version": str(row.get("version") or ""),
        "detector_type": "risk_dictionary",
        "needs_context_review": needs_review,
    }


def detect_risk_expressions(text: str, limit: int | None = None) -> list[dict]:
    """Detect active dictionary expressions contained in *text*."""
    if not text:
        return []

    normalized_text = _normalize(text)
    compact_text = _compact(text)
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for row in _load_dictionary_rows():
        expression = str(row.get("expression") or "").strip()
        if not expression:
            continue

        normalized_expression = _normalize(expression)
        compact_expression = _compact(expression)
        matched = normalized_expression in normalized_text
        if not matched and compact_expression:
            matched = compact_expression in compact_text
        if not matched:
            continue

        start = normalized_text.find(normalized_expression)
        if start < 0:
            start = 0
        key = (str(row.get("risk_id") or expression), expression)
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            _row_to_finding(
                row,
                expression,
                _needs_context_review(text, start, start + len(expression)),
            )
        )
        if limit is not None and len(findings) >= limit:
            break

    return findings


def detect_semantic_risk_patterns(text: str) -> list[dict]:
    """Detect rule-based semantic risk patterns without embeddings."""
    if not text:
        return []

    findings: list[dict] = []
    for rule_index, rule in enumerate(_SEMANTIC_RULES, 1):
        for pattern_index, pattern in enumerate(rule["patterns"], 1):
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                matched_text = match.group(0)
                findings.append(
                    {
                        "risk_id": f"SEM_{rule_index:03d}_{pattern_index:03d}_{len(findings) + 1:03d}",
                        "matched_expression": matched_text,
                        "risk_type": rule["risk_type"],
                        "severity": rule["severity"],
                        "reason": rule["reason"],
                        "regulatory_basis": rule["basis"],
                        "recommended_action": rule["action"],
                        "replacement_guideline": rule["action"],
                        "source": "semantic_pattern_rules",
                        "version": "1",
                        "detector_type": "semantic_pattern",
                        "needs_context_review": _needs_context_review(
                            text, match.start(), match.end()
                        ),
                    }
                )
    return findings


def _summary(findings: list[dict]) -> dict:
    severities = [str(item.get("severity", "")).upper() for item in findings]
    risk_types = sorted({str(item.get("risk_type")) for item in findings if item.get("risk_type")})
    return {
        "total_count": len(findings),
        "high_count": severities.count("HIGH"),
        "critical_count": severities.count("CRITICAL"),
        "risk_types": risk_types,
    }


def detect_compliance_risks(text: str, limit: int | None = None) -> dict:
    """Run dictionary and semantic-pattern detectors together."""
    dictionary_findings = detect_risk_expressions(text, limit=limit)
    semantic_findings = detect_semantic_risk_patterns(text)
    if limit is not None:
        semantic_findings = semantic_findings[: max(0, limit - len(dictionary_findings))]
    total_findings = dictionary_findings + semantic_findings
    return {
        "dictionary_findings": dictionary_findings,
        "semantic_findings": semantic_findings,
        "total_findings": total_findings,
        "summary": _summary(total_findings),
    }
