"""Repository for regulatory gray-zone expression types.

The repository reuses the project's existing DB URL resolution and never logs
or prints secrets. DB failures return built-in fallback rows so Agent workflows
can keep their gray-zone simulation behavior.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env_file(path: Path) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
        return
    except Exception:
        pass

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(ROOT / ".env")

from backend.src.tools.risk_dictionary_detector import _db_url  # noqa: E402

logger = logging.getLogger(__name__)

TABLE_NAME = "regulatory_gray_zone_expression_type"

_SELECT_COLUMNS = [
    "risk_type",
    "risk_label",
    "risk_description",
    "document_scope",
    "trigger_patterns",
    "risky_expression_templates",
    "safe_rewrite_guidelines",
    "example_source_sentence",
    "example_risky_sentence",
    "example_safe_sentence",
    "consumer_impact",
    "insurer_advantage_vector",
    "detection_note",
    "severity",
]

_FALLBACK_ROWS: list[dict[str, Any]] = [
    {
        "risk_type": "INSURER_DISCRETION_EXPANSION",
        "risk_label": "보험사 재량 확대형",
        "risk_description": "보험금 지급 여부나 보장 판단을 회사의 추상적 판단에 좌우되게 할 수 있는 표현 유형",
        "document_scope": ["약관"],
        "trigger_patterns": ["회사가 필요하다고 인정", "회사의 판단에 따라", "회사가 정하는 기준"],
        "risky_expression_templates": ["회사가 필요하다고 인정하는 경우 추가 확인 후 지급 여부를 정할 수 있습니다."],
        "safe_rewrite_guidelines": ["지급 요건, 제출 서류, 심사 기준을 객관적으로 명시한다."],
        "example_source_sentence": "약관에서 정한 보장 대상 의료비에 대해 회사가 필요하다고 인정하는 경우 보험금을 지급합니다.",
        "example_risky_sentence": "회사가 필요하다고 인정하는 경우 추가 확인 후 지급 여부를 정할 수 있습니다.",
        "example_safe_sentence": "약관에서 정한 지급 사유와 제출 서류가 확인되면 정해진 심사 절차에 따라 보험금을 지급합니다.",
        "consumer_impact": "소비자가 보장 여부를 예측하기 어렵고 사후적으로 지급 거절 또는 지연을 경험할 수 있습니다.",
        "insurer_advantage_vector": "보험사가 지급 범위와 시점을 좁게 해석할 여지가 생길 수 있습니다.",
        "detection_note": "명시적 금지어가 없어 단순 탐지에서 누락될 수 있는 문장 명확성 평가 항목입니다.",
        "severity": "high",
    },
    {
        "risk_type": "PAYMENT_CONDITION_AMBIGUATION",
        "risk_label": "보험금 지급 조건 애매형",
        "risk_description": "보험금 지급 요건, 필요 서류, 심사 기준이 구체적으로 특정되지 않는 표현 유형",
        "document_scope": ["약관"],
        "trigger_patterns": ["필요한 서류", "심사 절차", "합리적 확인"],
        "risky_expression_templates": ["필요한 서류와 합리적 확인이 완료된 경우 보험금을 지급할 수 있습니다."],
        "safe_rewrite_guidelines": ["제출 서류의 종류와 심사 기준, 처리 기한을 명시한다."],
        "example_source_sentence": "보험금 지급 사유에 해당하고 필요한 서류 제출 및 심사 절차를 거친 경우 보험금을 지급합니다.",
        "example_risky_sentence": "필요한 서류와 합리적 확인이 완료된 경우 보험금을 지급할 수 있습니다.",
        "example_safe_sentence": "보험금 지급 사유에 해당하고 약관에서 정한 제출 서류가 확인되면 정해진 기한 내 보험금을 지급합니다.",
        "consumer_impact": "소비자가 제출 서류와 심사 기준을 알기 어려워 청구 지연이나 분쟁 가능성이 높아집니다.",
        "insurer_advantage_vector": "불명확한 자료 요구를 근거로 지급 심사를 연장하거나 보류할 여지가 생길 수 있습니다.",
        "detection_note": "일반적 절차 안내처럼 보이지만 기준이 불명확해 자동 탐지에서 누락될 수 있습니다.",
        "severity": "medium",
    },
    {
        "risk_type": "LIMITATION_UNDER_SPECIFICATION",
        "risk_label": "보장한도·자기부담금 불명확형",
        "risk_description": "보장한도, 자기부담금, 공제 기준, 적용 범위가 구체적으로 특정되지 않는 표현 유형",
        "document_scope": ["약관"],
        "trigger_patterns": ["보장한도", "자기부담금", "일부 보장"],
        "risky_expression_templates": ["일부 비용은 보장한도와 자기부담금 기준에 따라 보장될 수 있습니다."],
        "safe_rewrite_guidelines": ["보장한도 금액, 자기부담금 비율, 공제 후 지급 방식을 구체적으로 설명한다."],
        "example_source_sentence": "보장한도 및 자기부담금 공제 후 보험금을 지급합니다.",
        "example_risky_sentence": "일부 비용은 보장한도와 자기부담금 기준에 따라 보장될 수 있습니다.",
        "example_safe_sentence": "보험금은 약관에 명시된 보장한도와 자기부담금 기준에 따라 산정합니다.",
        "consumer_impact": "소비자가 실제 수령 가능한 보험금 규모를 사전에 예측하기 어렵습니다.",
        "insurer_advantage_vector": "보험사가 한도와 공제를 좁게 적용할 여지가 생길 수 있습니다.",
        "detection_note": "정상적인 용어 자체보다 구체성 부족을 살펴야 하는 유형입니다.",
        "severity": "medium",
    },
    {
        "risk_type": "OPEN_ENDED_EXCEPTION_EXPANSION",
        "risk_label": "면책·제외 사유 개방형",
        "risk_description": "면책 사유나 보장 제외 사유를 개방적으로 확장하는 표현 유형",
        "document_scope": ["약관"],
        "trigger_patterns": ["이에 준하는 사유", "기타 회사가 정하는 사유", "그 밖의 사유"],
        "risky_expression_templates": ["약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않을 수 있습니다."],
        "safe_rewrite_guidelines": ["면책 사유를 약관에 명시된 항목으로 한정한다."],
        "example_source_sentence": "약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않습니다.",
        "example_risky_sentence": "약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않을 수 있습니다.",
        "example_safe_sentence": "보험금을 지급하지 않는 사유는 본 약관의 면책 조항에 명시된 항목에 한정합니다.",
        "consumer_impact": "소비자는 어떤 경우에 보장이 제외되는지 명확히 알기 어렵습니다.",
        "insurer_advantage_vector": "보험사가 보장 제외 사유를 넓게 해석할 여지가 생길 수 있습니다.",
        "detection_note": "포괄적 예외 표현은 명시적 금지어 없이도 보장 범위를 축소할 수 있습니다.",
        "severity": "high",
    },
    {
        "risk_type": "CONSUMER_BURDEN_SOFTENING",
        "risk_label": "소비자 부담 완화 표현형",
        "risk_description": "소비자에게 불리한 부담, 제한, 공제, 예외를 부드럽게 표현하는 유형",
        "document_scope": ["약관"],
        "trigger_patterns": ["일부 부담", "소정의 금액", "일정 부분"],
        "risky_expression_templates": ["소정의 자기부담금이 적용될 수 있습니다."],
        "safe_rewrite_guidelines": ["소비자가 부담해야 하는 금액, 비율, 조건을 명확히 제시한다."],
        "example_source_sentence": "일부 비용은 고객이 부담할 수 있습니다.",
        "example_risky_sentence": "소정의 자기부담금이 적용될 수 있습니다.",
        "example_safe_sentence": "고객은 약관에 명시된 자기부담금 비율 또는 금액을 부담하며, 적용 기준은 보장 항목별로 표시합니다.",
        "consumer_impact": "소비자가 실제 부담해야 할 비용을 과소평가할 수 있습니다.",
        "insurer_advantage_vector": "소비자가 부담 조건을 충분히 인식하지 못할 가능성이 생길 수 있습니다.",
        "detection_note": "완화된 표현은 불리한 조건을 충분히 인식하지 못하게 할 수 있습니다.",
        "severity": "medium",
    },
]

try:
    from backend.scripts.seed_regulatory_gray_zone_expression_types import SEED_ROWS as _SEED_ROWS

    if len(_SEED_ROWS) >= len(_FALLBACK_ROWS):
        _FALLBACK_ROWS = [dict(row) for row in _SEED_ROWS]
except Exception as exc:
    logger.info("Seed rows unavailable for gray-zone fallback expansion: %s", exc)


def _fallback_rows(document_type: str | None = None) -> list[dict]:
    if not document_type:
        rows = [dict(row) for row in _FALLBACK_ROWS]
    else:
        rows = [
            dict(row)
            for row in _FALLBACK_ROWS
            if document_type in (row.get("document_scope") or [])
            or "all" in (row.get("document_scope") or [])
            or "공통" in (row.get("document_scope") or [])
        ]
    for row in rows:
        row["_source"] = "fallback"
    return rows


def _json_value(value: Any) -> Any:
    if value is None:
        return []
    return value


def normalize_gray_zone_type_row(row: Any) -> dict:
    """Normalize a DB row into a plain dict used by Agents."""
    item = dict(row)
    return {
        "risk_type": item.get("risk_type"),
        "risk_label": item.get("risk_label"),
        "risk_description": item.get("risk_description"),
        "document_scope": list(item.get("document_scope") or []),
        "trigger_patterns": _json_value(item.get("trigger_patterns")),
        "risky_expression_templates": _json_value(item.get("risky_expression_templates")),
        "safe_rewrite_guidelines": _json_value(item.get("safe_rewrite_guidelines")),
        "example_source_sentence": item.get("example_source_sentence"),
        "example_risky_sentence": item.get("example_risky_sentence"),
        "example_safe_sentence": item.get("example_safe_sentence"),
        "consumer_impact": item.get("consumer_impact"),
        "insurer_advantage_vector": item.get("insurer_advantage_vector"),
        "detection_note": item.get("detection_note"),
        "severity": item.get("severity"),
    }


def fetch_active_gray_zone_expression_types(document_type: str | None = None) -> list[dict]:
    """Fetch active gray-zone expression type rows.

    If *document_type* is provided, only rows whose document_scope contains the
    document type are returned. On DB/config/dependency failures, returns
    built-in fallback rows marked with ``_source == "fallback"``.
    """
    db_url = _db_url()
    if not db_url:
        logger.warning("Gray-zone expression repository DB URL is not configured.")
        return _fallback_rows(document_type)

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except Exception as exc:
        logger.warning("psycopg2 is unavailable; gray-zone repository disabled: %s", exc)
        return _fallback_rows(document_type)

    columns = ", ".join(_SELECT_COLUMNS)
    params: tuple[Any, ...] = ()
    where = "WHERE is_active = TRUE"
    if document_type:
        where += " AND (%s = ANY(document_scope) OR 'all' = ANY(document_scope) OR '공통' = ANY(document_scope))"
        params = (document_type,)

    sql = f"""
        SELECT {columns}
        FROM {TABLE_NAME}
        {where}
        ORDER BY risk_type;
    """

    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                return [normalize_gray_zone_type_row(row) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("Gray-zone expression lookup failed; using fallback: %s", exc)
        return _fallback_rows(document_type)


def main() -> None:
    rows = fetch_active_gray_zone_expression_types()
    print(f"loaded_count={len(rows)}")
    print(f"risk_types={[row.get('risk_type') for row in rows]}")


if __name__ == "__main__":
    main()
