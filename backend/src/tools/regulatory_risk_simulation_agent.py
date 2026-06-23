"""DB-backed gray-zone expression simulation for generated insurance drafts.

This module sits after GenerationAgent. It is not a ComplianceAgent validation
layer and it does not judge legal safety. It matches generated draft sentences
against gray-zone expression types stored in Neon PostgreSQL, then returns short
non-operational ambiguous excerpts and strengthened safe sentence examples.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "solar-pro"
DEFAULT_LLM_PROVIDER = "upstage"
MAX_AMBIGUOUS_EXPRESSION_CHARS = 220
MAX_RISKY_EXCERPT_CHARS = MAX_AMBIGUOUS_EXPRESSION_CHARS
MAX_REPORT_PREVIEW_CHARS = 1500
FINAL_GRAY = "REGULATORY_GRAY_AREA_NOT_FLAGGED"
FINAL_SAFE = "LOW_RISK_OR_NO_TYPE_MATCH"
FINAL_EXPLICIT = "EXPLICIT_RISK_OR_REVIEW_REQUIRED"
GRAY_MATCHED = "GRAY_ZONE_EXPRESSION_TYPE_MATCHED"
GRAY_NO_MATCH = "LOW_RISK_OR_NO_TYPE_MATCH"
WARNING = (
    "본 결과는 문장 명확성 평가를 위한 참고용이며 실제 약관, 상품설명서, "
    "사업방법서, 판매자료로 사용할 수 없습니다."
)

REPORT_HEADER = (
    "[문장 명확성 평가 보고서]\n\n"
    "본 문서는 실제 약관, 상품설명서, 사업방법서, 판매자료로 사용할 수 없습니다.\n"
    "본 문서는 생성된 보험 문서 초안에서 소비자보호 관점상 불명확하게 해석될 수 있는 표현을 DB 기준으로 살펴보고,\n"
    "각 평가 항목별 불명확성 사유와 명확한 문장 제안을 제공하기 위한 참고 결과입니다.\n"
    "본 결과는 법적 적법성 판단이나 Compliance 검증 결과가 아닙니다."
)

SAFE_REPORT_HEADER = "[명확한 문장 제안 보고서]\n\n"

SYSTEM_PROMPT = """\
너는 보험 문서의 법적 적법성을 판정하는 도구가 아니다.
너는 DB에 정의된 문장 명확성 평가 항목을 기준으로 문장의 불명확성을 설명하고,
소비자보호 관점에서 더 명확한 문장 예시를 작성하는 보조 도구다.

금지:
- 실제 운영 가능한 약관/상품설명서/사업방법서 전문 작성 금지
- 규제 회피 전략 작성 금지
- 보험사 이익 극대화 목적 문서 작성 금지
- 위험 표현만 단독 출력 금지

허용:
- 짧은 비운영용 ambiguous excerpt
- 왜 애매모호한지 설명
- 소비자 혼동 지점 설명
- 명확한 문장 제안

반드시 JSON 객체만 반환하라.
"""

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_ARTICLE_RE = re.compile(r"제\s*\d+\s*조|Article\s+\d+", re.IGNORECASE)
_BODY_PREDICATES = (
    "지급합니다",
    "지급됩니다",
    "지급하지 않습니다",
    "보장합니다",
    "보장됩니다",
    "보장하지 않습니다",
    "차감합니다",
    "공제합니다",
    "공제 후 지급합니다",
    "제출해야 합니다",
    "제출하여야 합니다",
    "제한합니다",
    "적용합니다",
    "산정합니다",
    "따릅니다",
    "요청할 수 있습니다",
)
_BODY_ENDING_RE = re.compile(r"(합니다|됩니다|않습니다|따릅니다|있습니다|수 있습니다)[.!?。！？]?$")


@dataclass(frozen=True)
class FallbackGrayZoneType:
    risk_type: str
    risk_label: str
    risk_description: str
    trigger_patterns: tuple[str, ...]
    risky_expression_templates: tuple[str, ...]
    safe_rewrite_guidelines: tuple[str, ...]
    example_source_sentence: str
    example_risky_sentence: str
    example_safe_sentence: str
    consumer_impact: str
    insurer_advantage_vector: str
    detection_note: str
    severity: str = "medium"
    document_scope: tuple[str, ...] = ("약관", "상품설명서")

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_type": self.risk_type,
            "risk_label": self.risk_label,
            "risk_description": self.risk_description,
            "document_scope": list(self.document_scope),
            "trigger_patterns": list(self.trigger_patterns),
            "risky_expression_templates": list(self.risky_expression_templates),
            "safe_rewrite_guidelines": list(self.safe_rewrite_guidelines),
            "example_source_sentence": self.example_source_sentence,
            "example_risky_sentence": self.example_risky_sentence,
            "example_safe_sentence": self.example_safe_sentence,
            "consumer_impact": self.consumer_impact,
            "insurer_advantage_vector": self.insurer_advantage_vector,
            "detection_note": self.detection_note,
            "severity": self.severity,
        }


DEFAULT_GRAY_ZONE_TYPES: list[dict[str, Any]] = [
    FallbackGrayZoneType(
        risk_type="INSURER_DISCRETION_EXPANSION",
        risk_label="보험사 재량 확대형",
        risk_description="보험금 지급 여부나 보장 판단을 회사의 추상적 판단에 좌우되게 할 수 있는 표현 유형",
        trigger_patterns=("회사가 필요하다고 인정", "회사의 판단에 따라", "회사가 정하는 기준", "상당하다고 인정", "회사가 인정하는 경우"),
        risky_expression_templates=("회사가 필요하다고 인정하는 경우 추가 확인 후 지급 여부를 정할 수 있습니다.",),
        safe_rewrite_guidelines=("지급 요건, 제출 서류, 심사 기준을 객관적으로 명시한다.",),
        example_source_sentence="약관에서 정한 보장 대상 의료비에 대해 회사가 필요하다고 인정하는 경우 보험금을 지급합니다.",
        example_risky_sentence="회사가 필요하다고 인정하는 경우 추가 확인 후 지급 여부를 정할 수 있습니다.",
        example_safe_sentence="약관에서 정한 지급 사유와 제출 서류가 확인되면 정해진 심사 절차에 따라 보험금을 지급합니다.",
        consumer_impact="소비자가 보장 여부를 예측하기 어렵고 사후적으로 지급 거절 또는 지연을 경험할 수 있습니다.",
        insurer_advantage_vector="보험사가 사후 심사에서 지급 범위와 시점을 좁게 해석할 여지가 생길 수 있습니다.",
        detection_note="명시적 금지어가 없어 단순 탐지에서 누락될 수 있는 문장 명확성 평가 항목입니다.",
        severity="high",
    ).as_dict(),
    FallbackGrayZoneType(
        risk_type="PAYMENT_CONDITION_AMBIGUATION",
        risk_label="보험금 지급 조건 애매형",
        risk_description="보험금 지급 요건, 필요 서류, 심사 기준이 구체적으로 특정되지 않아 지급 가능성이 불명확해지는 표현 유형",
        trigger_patterns=("필요한 서류", "심사 절차", "합리적 확인", "회사가 요구하는 자료", "지급 심사 완료 후"),
        risky_expression_templates=("필요한 서류와 합리적 확인이 완료된 경우 보험금을 지급할 수 있습니다.",),
        safe_rewrite_guidelines=("제출 서류의 종류와 심사 기준, 처리 기한을 명시한다.",),
        example_source_sentence="보험금 지급 사유에 해당하고 필요한 서류 제출 및 심사 절차를 거친 경우 보험금을 지급합니다.",
        example_risky_sentence="필요한 서류와 합리적 확인이 완료된 경우 보험금을 지급할 수 있습니다.",
        example_safe_sentence="보험금 지급 사유에 해당하고 약관에서 정한 제출 서류가 확인되면 정해진 기한 내 보험금을 지급합니다.",
        consumer_impact="소비자가 제출 서류와 심사 기준을 알기 어려워 청구 지연이나 분쟁 가능성이 높아집니다.",
        insurer_advantage_vector="불명확한 자료 요구를 근거로 지급 심사를 연장하거나 보류할 여지가 생길 수 있습니다.",
        detection_note="일반적 절차 안내처럼 보이지만 기준이 불명확해 자동 탐지에서 누락될 수 있습니다.",
    ).as_dict(),
    FallbackGrayZoneType(
        risk_type="LIMITATION_UNDER_SPECIFICATION",
        risk_label="보장한도·자기부담금 불명확형",
        risk_description="보장한도, 자기부담금, 공제 기준, 적용 범위가 구체적으로 특정되지 않아 실제 보장 수준을 예측하기 어렵게 만드는 표현 유형",
        trigger_patterns=("보장한도", "자기부담금", "일부 보장", "공제 후 지급", "한도 내 지급"),
        risky_expression_templates=("일부 비용은 보장한도와 자기부담금 기준에 따라 보장될 수 있습니다.",),
        safe_rewrite_guidelines=("보장한도 금액, 자기부담금 비율, 공제 후 지급 방식을 구체적으로 설명한다.",),
        example_source_sentence="보장한도 및 자기부담금 공제 후 보험금을 지급합니다.",
        example_risky_sentence="일부 비용은 보장한도와 자기부담금 기준에 따라 보장될 수 있습니다.",
        example_safe_sentence="보험금은 약관에 명시된 보장한도와 자기부담금 기준에 따라 산정합니다.",
        consumer_impact="소비자가 실제 수령 가능한 보험금 규모를 사전에 예측하기 어렵습니다.",
        insurer_advantage_vector="보험사가 실제 지급 단계에서 한도와 공제를 좁게 적용할 여지가 생길 수 있습니다.",
        detection_note="정상적인 용어 자체보다 구체성 부족을 살펴야 하는 유형입니다.",
    ).as_dict(),
    FallbackGrayZoneType(
        risk_type="OPEN_ENDED_EXCEPTION_EXPANSION",
        risk_label="면책·제외 사유 개방형",
        risk_description="면책 사유나 보장 제외 사유를 이에 준하는 사유, 기타 회사가 정하는 사유 등으로 개방적으로 확장하는 표현 유형",
        trigger_patterns=("이에 준하는 사유", "기타 회사가 정하는 사유", "그 밖의 사유", "유사한 경우", "회사가 인정하지 않는 경우"),
        risky_expression_templates=("약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않을 수 있습니다.",),
        safe_rewrite_guidelines=("면책 사유를 약관에 명시된 항목으로 한정한다.",),
        example_source_sentence="약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않습니다.",
        example_risky_sentence="약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않을 수 있습니다.",
        example_safe_sentence="보험금을 지급하지 않는 사유는 본 약관의 면책 조항에 명시된 항목에 한정합니다.",
        consumer_impact="소비자는 어떤 경우에 보장이 제외되는지 명확히 알기 어렵습니다.",
        insurer_advantage_vector="보험사가 보장 제외 사유를 넓게 해석할 여지가 생길 수 있습니다.",
        detection_note="포괄적 예외 표현은 명시적 금지어 없이도 보장 범위를 축소할 수 있습니다.",
        severity="high",
    ).as_dict(),
    FallbackGrayZoneType(
        risk_type="CONSUMER_BURDEN_SOFTENING",
        risk_label="소비자 부담 완화 표현형",
        risk_description="소비자에게 불리한 부담, 제한, 공제, 예외를 부드럽게 표현해 실제 부담 수준을 낮게 인식하게 만들 수 있는 표현 유형",
        trigger_patterns=("일부 부담", "소정의 금액", "일정 부분", "제한될 수 있음", "부담이 발생할 수 있음"),
        risky_expression_templates=("소정의 자기부담금이 적용될 수 있습니다.",),
        safe_rewrite_guidelines=("소비자가 부담해야 하는 금액, 비율, 조건을 명확히 제시한다.",),
        example_source_sentence="일부 비용은 고객이 부담할 수 있습니다.",
        example_risky_sentence="소정의 자기부담금이 적용될 수 있습니다.",
        example_safe_sentence="고객은 약관에 명시된 자기부담금 비율 또는 금액을 부담하며, 적용 기준은 보장 항목별로 표시합니다.",
        consumer_impact="소비자가 실제 부담해야 할 비용을 과소평가할 수 있습니다.",
        insurer_advantage_vector="소비자가 부담 조건을 충분히 인식하지 못한 상태에서 계약을 이해할 가능성이 생길 수 있습니다.",
        detection_note="완화된 표현은 불리한 조건을 충분히 인식하지 못하게 할 수 있습니다.",
    ).as_dict(),
]


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\r\n?", "\n", text or "").strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", normalized)
    return [part.strip() for part in parts if part.strip()]


def _excerpt(text: str, max_len: int = MAX_AMBIGUOUS_EXPRESSION_CHARS) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 1].rstrip() + "..."


def normalize_for_matching(text: str) -> str:
    if not text:
        return ""
    value = text.lower()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[·ㆍ•\-\_\(\)\[\]\{\},.;:!?\"'“”‘’`~]", "", value)
    value = value.replace("쨌", "").replace("??", "")
    return value


def _compact(value: str) -> str:
    return normalize_for_matching(value)


def _is_body_sentence_like(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    compact = normalize_for_matching(stripped)
    modern_predicates = (
        "지급합니다", "지급됩니다", "지급하지 않습니다", "보장합니다", "보장하지 않습니다",
        "차감합니다", "공제합니다", "제출해야 합니다", "제출합니다", "제한합니다",
        "적용합니다", "산정합니다", "따릅니다", "정합니다", "포함합니다",
        "제외합니다", "해당합니다",
    )
    predicates = _BODY_PREDICATES + modern_predicates
    return any(normalize_for_matching(predicate) in compact for predicate in predicates) or bool(
        _BODY_ENDING_RE.search(stripped)
    )


def _is_heading_like(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", text or "").strip()
    if not stripped:
        return False
    if _is_body_sentence_like(stripped):
        return False
    if re.search(
        r"(합니다|됩니다|않습니다|하여야 합니다|해야 합니다|따릅니다|정합니다|포함합니다|제외합니다|해당합니다)[.!?。！？]?$",
        stripped,
    ):
        return False
    if re.match(r"^제\s*\d+\s*(장|절|관)\b", stripped):
        return True
    if re.match(r"^제\s*\d+\s*조\s*(\([^)]*\))?\s*$", stripped):
        return True
    if re.match(r"^제\s*\d+\s*조\s*(\([^)]*\))?\s*.+$", stripped) and len(stripped) <= 45:
        return True
    if re.match(r"^(chapter|section)\s+[\w\d]+", stripped, re.IGNORECASE):
        return True
    if re.match(r"^\s*\[?\s*별표\s*\d*\s*\]?.*$", stripped) and len(stripped) <= 40:
        return True
    if re.match(r"^\d+\s*[.)]\s*[^.!?。！？]*$", stripped) and len(stripped) <= 60:
        return True
    heading_keywords = (
        "보장 한도", "보장한도", "자기부담금", "면책", "보험금 지급", "보장내용",
        "상품 개요", "보장 내용", "보험료 및 납입", "해지 및 환급금",
        "보험금 지급 제한사항", "가입 전 유의사항", "주요 유의사항",
        "사업방법서", "보험종목", "보험기간", "보험료 산출", "계약 인수",
        "계약 관리", "준용 규정",
    )
    if any(keyword in stripped for keyword in heading_keywords) and len(stripped) <= 45:
        return True
    return len(stripped) <= 18 and not re.search(r"[.!?。！？]$", stripped)


def _split_document_into_candidate_sentences(text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    excluded_heading_count = 0
    nearest_heading = ""
    raw_lines = [line for line in re.split(r"\r\n?|\n", text or "")]
    raw_sentence_count = 0
    sample_excluded_headings: list[str] = []
    sample_body_candidates: list[str] = []

    for line_index, raw_line in enumerate(raw_lines):
        line = raw_line.strip()
        if not line:
            continue
        line_sentences = _split_sentences(line)
        raw_sentence_count += len(line_sentences)
        if _is_heading_like(line):
            nearest_heading = line
            excluded_heading_count += 1
            if len(sample_excluded_headings) < 5:
                sample_excluded_headings.append(_excerpt(line, 200))
            continue

        for sentence in line_sentences:
            if _is_heading_like(sentence):
                nearest_heading = sentence
                excluded_heading_count += 1
                if len(sample_excluded_headings) < 5:
                    sample_excluded_headings.append(_excerpt(sentence, 200))
                continue
            if len(sample_body_candidates) < 5:
                sample_body_candidates.append(_excerpt(sentence, 200))
            candidates.append(
                {
                    "text": sentence,
                    "source_text_type": "body_sentence",
                    "excluded_heading_like": False,
                    "nearest_heading": nearest_heading,
                    "line_index": line_index,
                }
            )

    diagnostics = {
        "raw_line_count": len([line for line in raw_lines if line.strip()]),
        "raw_sentence_count": raw_sentence_count,
        "candidate_sentence_count": len(candidates),
        "excluded_heading_count": excluded_heading_count,
        "body_candidate_count": len(candidates),
        "sample_excluded_headings": sample_excluded_headings,
        "sample_body_candidates": sample_body_candidates,
    }
    return candidates, diagnostics


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = _JSON_FENCE_RE.sub("", text or "").strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    return data if isinstance(data, dict) else {}


def _safe_short_excerpt(value: str, fallback: str) -> str:
    candidate = _excerpt(value or fallback, MAX_AMBIGUOUS_EXPRESSION_CHARS)
    if _ARTICLE_RE.search(candidate) or candidate.count("\n") > 2:
        return _excerpt(fallback, MAX_AMBIGUOUS_EXPRESSION_CHARS)
    return candidate


def load_gray_zone_expression_types(document_type: str | None = None) -> tuple[list[dict], str]:
    """Load gray-zone expression types from DB, falling back to built-in rows."""
    try:
        from .gray_zone_expression_repository import fetch_active_gray_zone_expression_types

        rows = fetch_active_gray_zone_expression_types(document_type)
        if rows:
            if all(row.get("_source") == "fallback" for row in rows):
                return rows, "fallback"
            return rows, "db"
    except Exception as exc:
        logger.info("[regulatory_risk_simulation] DB gray-zone type fallback: %s", exc)

    if document_type:
        filtered = [
            row
            for row in DEFAULT_GRAY_ZONE_TYPES
            if document_type in (row.get("document_scope") or [])
        ]
        return filtered or DEFAULT_GRAY_ZONE_TYPES, "fallback"
    return DEFAULT_GRAY_ZONE_TYPES, "fallback"


def _contains_patterns(sentence: str, patterns: list[str]) -> list[str]:
    compact_sentence = normalize_for_matching(sentence)
    return [
        pattern
        for pattern in patterns
        if pattern and normalize_for_matching(pattern) in compact_sentence
    ]


def _restore_source_phrase_for_pattern(source_text: str, pattern: str) -> str:
    normalized_pattern = normalize_for_matching(pattern)
    if not normalized_pattern:
        return ""
    source = source_text or ""
    best: str = ""
    for start in range(len(source)):
        for end in range(start + 1, len(source) + 1):
            candidate = source[start:end].strip()
            if not candidate:
                continue
            normalized_candidate = normalize_for_matching(candidate)
            if normalized_candidate == normalized_pattern:
                if not best or len(candidate) < len(best):
                    best = candidate
                break
            if len(normalized_candidate) > len(normalized_pattern) + 2:
                break
    return best


def _unclear_points_from_source(source_text: str, matched_patterns: list[str]) -> list[str]:
    points: list[str] = []
    seen: set[str] = set()
    for pattern in matched_patterns:
        restored = _restore_source_phrase_for_pattern(source_text, pattern)
        point = restored or pattern
        key = normalize_for_matching(point)
        if key and key not in seen:
            seen.add(key)
            points.append(point)
    return points


def _first_text(values: Any, fallback: str = "") -> str:
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(values, str) and values.strip():
        return values.strip()
    return fallback


def _guideline_text(row: dict[str, Any]) -> str:
    guidelines = row.get("safe_rewrite_guidelines") or []
    if isinstance(guidelines, list):
        return " / ".join(str(item) for item in guidelines if str(item).strip())
    return str(guidelines or "")


def _fallback_finding(sentence: str, row: dict[str, Any], matched_patterns: list[str], source: str) -> dict[str, Any]:
    risk_type = str(row.get("risk_type") or "UNKNOWN_GRAY_ZONE_TYPE")
    risk_label = str(row.get("risk_label") or risk_type)
    ambiguous = _first_text(
        row.get("risky_expression_templates"),
        row.get("example_risky_sentence") or sentence,
    )
    safe_sentence = _first_text(
        row.get("example_safe_sentence"),
        "조건, 한도, 지급 요건, 면책 사유를 약관 기준에 따라 구체적으로 명시합니다.",
    )
    guideline = _guideline_text(row)
    why = str(row.get("detection_note") or row.get("risk_description") or "DB에 정의된 문장 명확성 평가 항목과 매칭되었습니다.")
    consumer_point = str(row.get("consumer_impact") or "소비자가 보장 조건이나 부담 조건을 명확히 예측하기 어려울 수 있습니다.")
    finding = {
        "source_text": _excerpt(sentence),
        "gray_zone_type_source": source,
        "gray_zone_risk_type": risk_type,
        "gray_zone_risk_label": risk_label,
        "risk_description": row.get("risk_description") or "",
        "detection_note": row.get("detection_note") or "",
        "insurer_advantage_vector": row.get("insurer_advantage_vector") or "",
        "matched_patterns": matched_patterns,
        "severity": row.get("severity") or "medium",
        "document_scope": list(row.get("document_scope") or []),
        "risk_vector": risk_type,
        "risk_label": risk_label,
        "_db_ambiguous_template": _safe_short_excerpt(ambiguous, row.get("example_risky_sentence") or sentence),
        "unclear_points_in_source": _unclear_points_from_source(sentence, matched_patterns),
        "ambiguous_expression_example": _safe_short_excerpt(ambiguous, row.get("example_risky_sentence") or sentence),
        "risky_variant_example": "",
        "why_ambiguous": _excerpt(why, 500),
        "consumer_confusion_point": _excerpt(consumer_point, 500),
        "safe_rewrite_guideline": _excerpt(guideline, 500),
        "strengthened_safe_sentence": _excerpt(safe_sentence, 500),
        "safe_rewrite_example": "",
        "gray_zone_classification": GRAY_MATCHED,
        "classification_basis": f"{source}_gray_zone_expression_type",
        "final_classification": FINAL_GRAY,
        "requires_human_review": True,
        "demo_only": True,
        "operational_use_allowed": False,
        "warning": WARNING,
        "llm_judgement": {
            "used": False,
            "provider": DEFAULT_LLM_PROVIDER,
            "model": DEFAULT_MODEL,
            "fallback_used": True,
            "reason": "DB template 기반 fallback을 사용했습니다.",
        },
        "compliance_judgement": {
            "checked": False,
            "checker": "not_used",
            "reason": "이번 Agent는 ComplianceAgent 검증이 아니라 DB 기반 문장 명확성 평가 항목 매칭을 사용합니다.",
        },
        "full_compliance_judgement": {
            "checked": False,
            "checker": "ComplianceAgent.validate",
            "reason": "요구사항에 따라 본 단계에서는 사용하지 않습니다.",
        },
    }
    finding["risky_variant_example"] = finding["ambiguous_expression_example"]
    finding["safe_rewrite_example"] = finding["strengthened_safe_sentence"]
    return finding


def _detect_candidates(
    draft_content: str,
    max_findings: int,
    *,
    document_type: str | None = None,
    gray_zone_types: list[dict] | None = None,
    gray_zone_type_source: str = "fallback",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    del document_type
    rows = gray_zone_types or DEFAULT_GRAY_ZONE_TYPES
    candidates, diagnostics = _split_document_into_candidate_sentences(draft_content)
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    sample_matched_candidates: list[str] = []
    sample_unmatched_body_candidates: list[str] = []
    heading_context_match_count = 0
    for candidate in candidates:
        sentence = candidate["text"]
        candidate_matched = False
        for row in rows:
            matched_patterns = _contains_patterns(sentence, list(row.get("trigger_patterns") or []))
            matched_from_heading_context = False
            if not matched_patterns and candidate.get("nearest_heading") and _is_body_sentence_like(sentence):
                matched_patterns = _contains_patterns(
                    candidate["nearest_heading"],
                    list(row.get("trigger_patterns") or []),
                )
                matched_from_heading_context = bool(matched_patterns)
            if not matched_patterns:
                continue
            risk_type = str(row.get("risk_type") or "")
            key = (_excerpt(sentence), risk_type)
            if key in seen:
                continue
            seen.add(key)
            candidate_matched = True
            finding = _fallback_finding(sentence, row, matched_patterns, gray_zone_type_source)
            finding["source_text_type"] = candidate["source_text_type"]
            finding["excluded_heading_like"] = candidate["excluded_heading_like"]
            finding["nearest_heading"] = candidate["nearest_heading"]
            finding["matched_from_heading_context"] = matched_from_heading_context
            if matched_from_heading_context:
                heading_context_match_count += 1
            if len(sample_matched_candidates) < 5:
                sample_matched_candidates.append(_excerpt(sentence, 200))
            findings.append(finding)
            if len(findings) >= max_findings:
                diagnostics.update({
                    "matched_candidate_count": len(findings),
                    "unmatched_body_candidate_count": max(0, diagnostics["body_candidate_count"] - len(findings)),
                    "heading_context_match_count": heading_context_match_count,
                    "sample_matched_candidates": sample_matched_candidates,
                    "sample_unmatched_body_candidates": sample_unmatched_body_candidates,
                })
                return findings, diagnostics
        if not candidate_matched and len(sample_unmatched_body_candidates) < 5:
            sample_unmatched_body_candidates.append(_excerpt(sentence, 200))
    diagnostics.update({
        "matched_candidate_count": len(findings),
        "unmatched_body_candidate_count": max(0, diagnostics["body_candidate_count"] - len(findings)),
        "heading_context_match_count": heading_context_match_count,
        "sample_matched_candidates": sample_matched_candidates,
        "sample_unmatched_body_candidates": sample_unmatched_body_candidates,
    })
    return findings, diagnostics


def _build_llm_prompt(
    finding: dict[str, Any],
    document_type: str | None = None,
    request_context: dict | None = None,
) -> str:
    payload = {
        "document_type": document_type or "",
        "source_text": finding.get("source_text", ""),
        "gray_zone_risk_type": finding.get("gray_zone_risk_type", ""),
        "gray_zone_risk_label": finding.get("gray_zone_risk_label", ""),
        "risk_description": finding.get("risk_description", ""),
        "matched_patterns": finding.get("matched_patterns", []),
        "unclear_points_in_source": finding.get("unclear_points_in_source", []),
        "db_ambiguous_template": finding.get("ambiguous_expression_example", ""),
        "safe_rewrite_guideline": finding.get("safe_rewrite_guideline", ""),
        "strengthened_safe_sentence": finding.get("strengthened_safe_sentence", ""),
        "request_context": request_context or {},
        "output_json_schema": {
            "unclear_points_in_source": ["..."],
            "ambiguous_expression_example": "...",
            "why_ambiguous": "...",
            "consumer_confusion_point": "...",
            "strengthened_safe_sentence": "...",
            "safe_rewrite_guideline": "...",
        },
    }
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "분석 대상 JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "예시의 역할은 실제 운영 가능한 약관 문구를 작성하는 것이 아니다. "
        "문장 명확성 평가를 위해 원문이 불명확하게 해석될 수 있는 형태를 짧은 예시로 보여준다. "
        "ambiguous_expression_example은 반드시 짧은 비운영용 excerpt로 작성하라. "
        "불명확한 표현 예시는 반드시 불명확성 사유와 명확한 문장 제안과 함께 반환하라. "
        "규제 회피 전략, 보험사 이익 극대화 문구, 실제 사용 가능한 약관 전문은 작성하지 않는다. "
        "JSON 객체만 반환하고, 항상 strengthened_safe_sentence를 함께 작성하라."
    )


def _invoke_upstage_json(prompt: str, model: str) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_upstage import ChatUpstage

    api_key = os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        raise ValueError("UPSTAGE_API_KEY is not configured.")
    llm = ChatUpstage(model=model or DEFAULT_MODEL, api_key=api_key)
    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    return _parse_json_object(getattr(response, "content", ""))


def _enhance_with_llm(
    finding: dict[str, Any],
    *,
    document_type: str | None,
    request_context: dict | None,
    model_override: str,
) -> bool:
    model = model_override or DEFAULT_MODEL
    parsed = _invoke_upstage_json(
        _build_llm_prompt(finding, document_type, request_context),
        model,
    )
    unclear_points = parsed.get("unclear_points_in_source")
    if isinstance(unclear_points, list):
        cleaned_points = [
            _excerpt(str(point), 120)
            for point in unclear_points
            if isinstance(point, str) and point.strip()
        ]
        if cleaned_points:
            finding["unclear_points_in_source"] = cleaned_points
    db_ambiguous_template = finding.get("_db_ambiguous_template") or finding.get("risky_variant_example", "")
    for key in (
        "why_ambiguous",
        "consumer_confusion_point",
        "strengthened_safe_sentence",
        "safe_rewrite_guideline",
    ):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            finding[key] = _excerpt(value, 500)
    ambiguous_value = parsed.get("ambiguous_expression_example")
    if isinstance(ambiguous_value, str) and ambiguous_value.strip():
        candidate = _safe_short_excerpt(ambiguous_value, db_ambiguous_template)
        if normalize_for_matching(candidate) != normalize_for_matching(finding.get("source_text", "")):
            finding["ambiguous_expression_example"] = candidate
    finding["ambiguous_expression_example"] = _safe_short_excerpt(
        finding.get("ambiguous_expression_example", ""),
        db_ambiguous_template,
    )
    finding["risky_variant_example"] = finding["ambiguous_expression_example"]
    finding["safe_rewrite_example"] = _excerpt(finding.get("strengthened_safe_sentence", ""), 500)
    finding["llm_judgement"] = {
        "used": True,
        "provider": DEFAULT_LLM_PROVIDER,
        "model": model,
        "fallback_used": False,
    }
    return True


def _llm_enhance_finding(
    finding: dict[str, Any],
    *,
    document_type: str | None,
    request_context: dict | None,
    model_override: str,
) -> bool:
    return _enhance_with_llm(
        finding,
        document_type=document_type,
        request_context=request_context,
        model_override=model_override,
    )


def _safe_finding_for_output(finding: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in finding.items() if not key.startswith("_")}


def _empty_result(
    *,
    gray_zone_type_source: str = "fallback",
    gray_zone_type_count: int = 0,
    fallback_used: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_count": 0,
        "gray_zone_type_source": gray_zone_type_source,
        "gray_zone_type_count": gray_zone_type_count,
        "matched_risk_types": [],
        "llm_provider": DEFAULT_LLM_PROVIDER,
        "llm_model": DEFAULT_MODEL,
        "llm_used": False,
        "fallback_used": fallback_used,
        "demo_only": True,
        "operational_use_allowed": False,
        "classifications": {FINAL_SAFE: 1},
        "raw_line_count": 0,
        "raw_sentence_count": 0,
        "candidate_sentence_count": 0,
        "excluded_heading_count": 0,
        "body_candidate_count": 0,
        "matched_candidate_count": 0,
        "unmatched_body_candidate_count": 0,
        "heading_context_match_count": 0,
        "sample_excluded_headings": [],
        "sample_body_candidates": [],
        "sample_matched_candidates": [],
        "sample_unmatched_body_candidates": [],
        "warning": WARNING,
    }
    if error:
        summary["error"] = _excerpt(error, 300)
    return {
        "findings": [],
        "summary": summary,
        "regulatory_risk_simulation_report": "",
        "safe_alternative_report": "",
    }


def _build_reports(findings: list[dict[str, Any]]) -> tuple[str, str]:
    if not findings:
        return (
            f"{REPORT_HEADER}\n\nDB 평가 항목과 매칭된 본문 문장이 없습니다.\n"
            f"demo_only=True\noperational_use_allowed=False\nfinal_classification={FINAL_SAFE}\nwarning: {WARNING}",
            f"{SAFE_REPORT_HEADER}\n\n별도 명확한 문장 제안이 필요한 DB 평가 항목 매칭 결과가 없습니다.\n"
            f"demo_only=True\noperational_use_allowed=False\nfinal_classification={FINAL_SAFE}\nwarning: {WARNING}",
        )

    risk_items = []
    safe_items = []
    for index, item in enumerate(findings, 1):
        matched_patterns = ", ".join(item.get("matched_patterns", [])) or "-"
        unclear_points = ", ".join(item.get("unclear_points_in_source", [])) or matched_patterns
        risk_items.append(
            f"## 평가 결과 {index}. {item['gray_zone_risk_label']}\n\n"
            f"[원문 문장]\n{item['source_text']}\n\n"
            f"[원문 내 불명확 가능 지점]\n{unclear_points}\n\n"
            f"[평가 유형]\n{item['gray_zone_risk_type']}\n\n"
            f"[DB 매칭 패턴]\n{matched_patterns}\n\n"
            f"[불명확하게 해석될 수 있는 표현 예시]\n{item['ambiguous_expression_example']}\n\n"
            f"[불명확성 사유]\n{item['why_ambiguous']}\n\n"
            f"[소비자 오해 가능성]\n{item['consumer_confusion_point']}\n\n"
            f"[명확화 기준]\n{item['safe_rewrite_guideline']}\n\n"
            f"[탐지 근거]\n{item.get('detection_note', '-')}\n\n"
            f"[비운영 사용 제한]\n"
            f"demo_only=True\noperational_use_allowed=False\n"
            f"gray_zone_classification={item['gray_zone_classification']}\n"
            f"classification_basis={item['classification_basis']}\nwarning: {item['warning']}\n\n"
            f"[명확한 문장 제안]\n{item['strengthened_safe_sentence']}"
        )
        safe_items.append(
            f"## {index}. {item['gray_zone_risk_label']}\n"
            f"- 원문: {item['source_text']}\n"
            f"- 원문 내 불명확 가능 지점: {unclear_points}\n"
            f"- 평가 유형: {item['gray_zone_risk_type']}\n"
            f"- 불명확하게 해석될 수 있는 표현 예시: {item['ambiguous_expression_example']}\n"
            f"- 명확화 기준: {item['safe_rewrite_guideline']}\n"
            f"- 명확한 문장 제안: {item['strengthened_safe_sentence']}\n"
        )
    return (
        f"{REPORT_HEADER}\n\n" + "\n\n".join(risk_items),
        f"{SAFE_REPORT_HEADER}\n" + "\n".join(safe_items),
    )


def simulate_regulatory_risks(
    draft_content: str,
    document_type: str | None = None,
    request_context: dict | None = None,
    max_findings: int = 5,
    use_llm: bool = True,
    model_override: str | None = DEFAULT_MODEL,
    use_full_compliance_agent: bool = False,
) -> dict[str, Any]:
    """Simulate DB-backed gray-zone expression risks and safe rewrites."""
    del use_full_compliance_agent
    try:
        gray_zone_types, type_source = load_gray_zone_expression_types(document_type)
        if not draft_content or max_findings <= 0:
            report, safe_report = _build_reports([])
            result = _empty_result(
                gray_zone_type_source=type_source,
                gray_zone_type_count=len(gray_zone_types),
            )
            result["regulatory_risk_simulation_report"] = report
            result["safe_alternative_report"] = safe_report
            return result

        findings, diagnostics = _detect_candidates(
            draft_content,
            max_findings,
            document_type=document_type,
            gray_zone_types=gray_zone_types,
            gray_zone_type_source=type_source,
        )
        llm_used = False
        fallback_used = type_source == "fallback"
        llm_model = model_override or DEFAULT_MODEL

        if findings and use_llm:
            for finding in findings:
                try:
                    llm_used = _llm_enhance_finding(
                        finding,
                        document_type=document_type,
                        request_context=request_context,
                        model_override=llm_model,
                    ) or llm_used
                except Exception as exc:
                    fallback_used = True
                    finding["llm_judgement"] = {
                        "used": False,
                        "provider": DEFAULT_LLM_PROVIDER,
                        "model": llm_model,
                        "fallback_used": True,
                        "reason": _excerpt(str(exc), 300),
                    }
                    logger.info(
                        "[regulatory_risk_simulation] Upstage fallback for %s: %s",
                        finding.get("gray_zone_risk_type"),
                        exc,
                    )

        matched_risk_types = sorted({
            finding.get("gray_zone_risk_type")
            for finding in findings
            if finding.get("gray_zone_risk_type")
        })
        classifications: dict[str, int] = {}
        for finding in findings:
            cls = finding.get("final_classification", FINAL_GRAY)
            classifications[cls] = classifications.get(cls, 0) + 1

        report, safe_report = _build_reports(findings)
        return {
            "findings": [_safe_finding_for_output(finding) for finding in findings],
            "summary": {
                "total_count": len(findings),
                "gray_zone_type_source": type_source,
                "gray_zone_type_count": len(gray_zone_types),
                "matched_risk_types": matched_risk_types,
                "llm_provider": DEFAULT_LLM_PROVIDER,
                "llm_model": llm_model,
                "llm_used": llm_used,
                "fallback_used": fallback_used,
                "demo_only": True,
                "operational_use_allowed": False,
                "classifications": classifications or {FINAL_SAFE: 1},
                "raw_line_count": diagnostics.get("raw_line_count", 0),
                "raw_sentence_count": diagnostics.get("raw_sentence_count", 0),
                "candidate_sentence_count": diagnostics.get("candidate_sentence_count", 0),
                "excluded_heading_count": diagnostics.get("excluded_heading_count", 0),
                "body_candidate_count": diagnostics.get("body_candidate_count", 0),
                "matched_candidate_count": diagnostics.get("matched_candidate_count", 0),
                "unmatched_body_candidate_count": diagnostics.get("unmatched_body_candidate_count", 0),
                "heading_context_match_count": diagnostics.get("heading_context_match_count", 0),
                "sample_excluded_headings": diagnostics.get("sample_excluded_headings", []),
                "sample_body_candidates": diagnostics.get("sample_body_candidates", []),
                "sample_matched_candidates": diagnostics.get("sample_matched_candidates", []),
                "sample_unmatched_body_candidates": diagnostics.get("sample_unmatched_body_candidates", []),
                "warning": WARNING,
                "document_type": document_type or "",
            },
            "regulatory_risk_simulation_report": report,
            "safe_alternative_report": safe_report,
        }
    except Exception as exc:
        logger.exception("[regulatory_risk_simulation] failed")
        return _empty_result(fallback_used=True, error=str(exc))


def _sample_text() -> str:
    return (
        "약관에서 정한 보장 대상 의료비에 대해 회사가 필요하다고 인정하는 경우 보험금을 지급합니다.\n"
        "보험금 지급 사유에 해당하고 필요한 서류 제출 및 심사 절차를 거친 경우 보험금을 지급합니다.\n"
        "보장한도 및 자기부담금 공제 후 보험금을 지급합니다.\n"
        "약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않습니다."
    )


def build_az_output(result: dict[str, Any], sample_text: str) -> str:
    sentences = _split_sentences(sample_text)
    findings = result.get("findings", [])
    first = findings[0] if findings else {}
    llm = first.get("llm_judgement", {})
    summary = result.get("summary", {})
    lines = [
        "[A] 입력 초안",
        _excerpt(sample_text, 600),
        "",
        "[B] DB 평가 항목 로드 결과",
        f"- source: {summary.get('gray_zone_type_source')}",
        f"- count: {summary.get('gray_zone_type_count')}",
        f"- matched_risk_types: {summary.get('matched_risk_types', [])}",
        f"- excluded_heading_count: {summary.get('excluded_heading_count', 0)}",
        "",
        "[C] 문장 분리 결과",
        *[f"- 문장 {idx}: {_excerpt(sentence, 180)}" for idx, sentence in enumerate(sentences, 1)],
        "",
        "[D] DB trigger pattern 매칭 결과",
        f"- gray_zone_risk_type: {first.get('gray_zone_risk_type', '')}",
        f"- matched_patterns: {first.get('matched_patterns', [])}",
        "",
        "[E] 불명확하게 해석될 수 있는 표현 예시",
        first.get("ambiguous_expression_example", ""),
        "",
        "[F] Upstage Solar Pro 보강 결과 또는 fallback",
        f"- used: {llm.get('used', False)}",
        f"- provider: {llm.get('provider', DEFAULT_LLM_PROVIDER)}",
        f"- model: {llm.get('model', DEFAULT_MODEL)}",
        f"- fallback_used: {llm.get('fallback_used', False)}",
        "",
        "[G] 불명확성 사유",
        first.get("why_ambiguous", ""),
        "",
        "[H] 소비자 오해 가능성",
        first.get("consumer_confusion_point", ""),
        "",
        "[I] 명확한 문장 제안",
        first.get("strengthened_safe_sentence", ""),
        "",
        "[J] 문장 명확성 평가 보고서 미리보기",
        result.get("regulatory_risk_simulation_report", "")[:MAX_REPORT_PREVIEW_CHARS],
        "",
        "[K] 명확한 문장 제안 보고서 미리보기",
        result.get("safe_alternative_report", "")[:MAX_REPORT_PREVIEW_CHARS],
    ]
    return "\n".join(lines)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Show DB-backed gray-zone simulation sample output.")
    parser.add_argument("--use-llm", action="store_true", help="Attempt Upstage Solar Pro enhancement.")
    args = parser.parse_args()
    sample = _sample_text()
    result = simulate_regulatory_risks(
        sample,
        document_type="약관",
        request_context={"product_name": "실손의료보험", "purpose": "local_show_output"},
        max_findings=5,
        use_llm=args.use_llm,
        model_override=DEFAULT_MODEL,
    )
    print(build_az_output(result, sample))


if __name__ == "__main__":
    _main()
