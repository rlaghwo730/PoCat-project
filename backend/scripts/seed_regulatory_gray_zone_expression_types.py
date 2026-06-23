"""Create and seed regulatory gray-zone expression type rows.

This script prints only aggregate verification data. It never prints DB URLs,
passwords, tokens, or row-level operational text.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
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


TABLE_NAME = "regulatory_gray_zone_expression_type"


SEED_ROWS: list[dict[str, Any]] = [
    {
        "risk_type": "INSURER_DISCRETION_EXPANSION",
        "risk_label": "보험사 재량 확대형",
        "risk_description": "보험금 지급 여부나 보장 판단을 회사의 추상적 판단에 좌우되게 할 수 있는 표현 유형",
        "document_scope": ["약관"],
        "trigger_patterns": ["회사가 필요하다고 인정", "회사의 판단에 따라", "회사가 정하는 기준", "상당하다고 인정하는 경우", "회사가 인정하는 경우"],
        "risky_expression_templates": ["회사가 필요하다고 인정하는 경우 추가 확인 후 지급 여부를 정할 수 있습니다.", "회사의 판단에 따라 보장 여부를 결정할 수 있습니다."],
        "safe_rewrite_guidelines": ["보험사의 추상적 재량 표현을 줄인다.", "지급 요건, 제출 서류, 심사 기준을 객관적으로 명시한다.", "회사 판단이 아니라 약관에서 정한 기준에 따라 지급된다는 점을 명확히 한다."],
        "example_source_sentence": "약관에서 정한 보장 대상 의료비에 대해 회사가 필요하다고 인정하는 경우 보험금을 지급합니다.",
        "example_risky_sentence": "회사가 필요하다고 인정하는 경우 추가 확인 후 지급 여부를 정할 수 있습니다.",
        "example_safe_sentence": "약관에서 정한 지급 사유와 제출 서류가 확인되면 정해진 심사 절차에 따라 보험금을 지급합니다.",
        "consumer_impact": "소비자가 보장 여부를 예측하기 어렵고 사후적으로 지급 거절 또는 지연을 경험할 수 있습니다.",
        "insurer_advantage_vector": "보험사가 사후 심사에서 지급 범위와 시점을 좁게 해석할 여지가 생길 수 있습니다.",
        "detection_note": "명시적 금지어가 없어 단순 금지어 탐지에서 누락될 수 있는 회색지대 유형입니다.",
        "severity": "high",
        "is_active": True,
    },
    {
        "risk_type": "PAYMENT_CONDITION_AMBIGUATION",
        "risk_label": "보험금 지급 조건 애매형",
        "risk_description": "보험금 지급 요건, 필요 서류, 심사 기준이 구체적으로 특정되지 않아 지급 가능성이 불명확해지는 표현 유형",
        "document_scope": ["약관"],
        "trigger_patterns": ["필요한 서류", "심사 절차", "합리적 확인", "회사가 요구하는 자료", "지급 심사 완료 후"],
        "risky_expression_templates": ["필요한 서류와 합리적 확인이 완료된 경우 보험금을 지급할 수 있습니다.", "회사가 요구하는 자료가 충분히 확인된 경우 지급 여부를 결정합니다."],
        "safe_rewrite_guidelines": ["제출 서류의 종류를 구체화한다.", "심사 기준과 처리 기한을 명시한다.", "지급 여부 판단 기준을 객관적으로 제시한다."],
        "example_source_sentence": "보험금 지급 사유에 해당하고 필요한 서류 제출 및 심사 절차를 거친 경우 보험금을 지급합니다.",
        "example_risky_sentence": "필요한 서류와 합리적 확인이 완료된 경우 보험금을 지급할 수 있습니다.",
        "example_safe_sentence": "보험금 지급 사유에 해당하고 약관에서 정한 진단서, 영수증, 진료비 세부내역서 등 제출 서류가 확인되면 정해진 기한 내 보험금을 지급합니다.",
        "consumer_impact": "소비자가 어떤 서류를 제출해야 하는지, 심사 기준이 무엇인지 알기 어려워 청구 지연이나 분쟁 가능성이 높아집니다.",
        "insurer_advantage_vector": "불명확한 자료 요구를 근거로 지급 심사를 연장하거나 보류할 여지가 생길 수 있습니다.",
        "detection_note": "일반적 절차 안내처럼 보이지만 기준이 불명확해 자동 탐지에서 누락될 수 있습니다.",
        "severity": "medium",
        "is_active": True,
    },
    {
        "risk_type": "LIMITATION_UNDER_SPECIFICATION",
        "risk_label": "보장한도·자기부담금 불명확형",
        "risk_description": "보장한도, 자기부담금, 공제 기준, 적용 범위가 구체적으로 특정되지 않아 실제 보장 수준을 예측하기 어렵게 만드는 표현 유형",
        "document_scope": ["약관"],
        "trigger_patterns": ["보장한도", "자기부담금", "일부 보장", "공제 후 지급", "한도 내 지급"],
        "risky_expression_templates": ["일부 비용은 보장한도와 자기부담금 기준에 따라 보장될 수 있습니다.", "보험금은 회사가 정한 한도와 공제 기준에 따라 지급됩니다."],
        "safe_rewrite_guidelines": ["보장한도 금액 또는 산정 기준을 명시한다.", "자기부담금 비율 또는 금액을 명시한다.", "공제 후 지급 방식과 예외를 구체적으로 설명한다."],
        "example_source_sentence": "보장한도 및 자기부담금 공제 후 보험금을 지급합니다.",
        "example_risky_sentence": "일부 비용은 보장한도와 자기부담금 기준에 따라 보장될 수 있습니다.",
        "example_safe_sentence": "보험금은 약관에 명시된 보장한도와 자기부담금 기준에 따라 산정하며, 적용 금액과 비율은 가입설계서 및 약관의 해당 조항에 따릅니다.",
        "consumer_impact": "소비자가 실제 수령 가능한 보험금 규모를 사전에 예측하기 어렵습니다.",
        "insurer_advantage_vector": "보험사가 실제 지급 단계에서 한도와 공제를 좁게 적용할 여지가 생길 수 있습니다.",
        "detection_note": "보장한도와 자기부담금이라는 단어 자체는 정상 표현이므로 구체성 부족을 탐지하기 어렵습니다.",
        "severity": "medium",
        "is_active": True,
    },
    {
        "risk_type": "OPEN_ENDED_EXCEPTION_EXPANSION",
        "risk_label": "면책·제외 사유 개방형",
        "risk_description": "면책 사유나 보장 제외 사유를 이에 준하는 사유, 기타 회사가 정하는 사유 등으로 개방적으로 확장하는 표현 유형",
        "document_scope": ["약관"],
        "trigger_patterns": ["이에 준하는 사유", "기타 회사가 정하는 사유", "그 밖의 사유", "유사한 경우", "회사가 인정하지 않는 경우"],
        "risky_expression_templates": ["약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않을 수 있습니다.", "기타 회사가 정하는 사유에 해당하는 경우 보장을 제한할 수 있습니다."],
        "safe_rewrite_guidelines": ["면책 사유를 열거식으로 구체화한다.", "기타, 이에 준하는 등 포괄적 표현을 제한한다.", "보장 제외 사유를 약관에 명확히 정해진 항목으로 한정한다."],
        "example_source_sentence": "약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않습니다.",
        "example_risky_sentence": "약관에서 정한 면책 사유 또는 이에 준하는 사유에 해당하는 경우 보험금을 지급하지 않을 수 있습니다.",
        "example_safe_sentence": "보험금을 지급하지 않는 사유는 본 약관의 면책 조항에 명시된 항목에 한정합니다.",
        "consumer_impact": "소비자는 어떤 경우에 보장이 제외되는지 명확히 알기 어렵고 사후적으로 제외 범위가 넓어질 위험이 있습니다.",
        "insurer_advantage_vector": "보험사가 보장 제외 사유를 넓게 해석할 여지가 생길 수 있습니다.",
        "detection_note": "포괄적 예외 표현은 명시적 금지어 없이도 보장 범위를 축소할 수 있습니다.",
        "severity": "high",
        "is_active": True,
    },
    {
        "risk_type": "CONSUMER_BURDEN_SOFTENING",
        "risk_label": "소비자 부담 완화 표현형",
        "risk_description": "소비자에게 불리한 부담, 제한, 공제, 예외를 부드럽게 표현해 실제 부담 수준을 낮게 인식하게 만들 수 있는 표현 유형",
        "document_scope": ["약관"],
        "trigger_patterns": ["일부 부담", "소정의 금액", "일정 부분", "제한될 수 있음", "부담이 발생할 수 있음"],
        "risky_expression_templates": ["일부 비용은 고객이 부담할 수 있습니다.", "소정의 자기부담금이 적용될 수 있습니다."],
        "safe_rewrite_guidelines": ["소비자가 부담해야 하는 금액, 비율, 조건을 명확히 제시한다.", "일부 부담, 소정의 등 불명확한 표현을 구체적 수치나 산정 기준으로 바꾼다.", "부담 발생 조건과 예외를 함께 설명한다."],
        "example_source_sentence": "일부 비용은 고객이 부담할 수 있습니다.",
        "example_risky_sentence": "소정의 자기부담금이 적용될 수 있습니다.",
        "example_safe_sentence": "고객은 약관에 명시된 자기부담금 비율 또는 금액을 부담하며, 적용 기준은 보장 항목별로 약관에 구체적으로 표시합니다.",
        "consumer_impact": "소비자가 실제 부담해야 할 비용을 과소평가할 수 있습니다.",
        "insurer_advantage_vector": "소비자가 부담 조건을 충분히 인식하지 못한 상태에서 계약을 이해할 가능성이 생길 수 있습니다.",
        "detection_note": "완화된 표현은 소비자에게 불리한 조건을 충분히 인식하지 못하게 할 수 있습니다.",
        "severity": "medium",
        "is_active": True,
    },
    {
        "risk_type": "PRODUCT_DESCRIPTION_COVERAGE_SUMMARY_AMBIGUITY",
        "risk_label": "보장내용 요약 불명확형",
        "risk_description": "상품설명서에서 보장내용을 요약하면서 실제 보장 조건, 한도, 제외사항을 충분히 설명하지 않아 소비자가 보장범위를 넓게 이해할 수 있는 유형",
        "document_scope": ["상품설명서"],
        "trigger_patterns": ["폭넓게 보장", "다양한 의료비", "주요 의료비", "보장받을 수 있습니다", "보장 내용"],
        "risky_expression_templates": ["다양한 의료비를 폭넓게 보장받을 수 있습니다.", "주요 의료비에 대해 보장받을 수 있습니다."],
        "safe_rewrite_guidelines": ["보장 대상과 보장 제외 항목, 보장 한도, 자기부담금 기준을 함께 명시한다.", "요약 표현 뒤에 적용 조건과 제한사항을 구체적으로 연결한다."],
        "example_source_sentence": "이 상품은 주요 의료비를 보장합니다.",
        "example_risky_sentence": "다양한 의료비를 폭넓게 보장받을 수 있습니다.",
        "example_safe_sentence": "이 상품은 약관에서 정한 급여 및 비급여 의료비 중 보장 대상 항목에 대해 보장하며, 보장 제외 항목과 자기부담금은 약관 및 상품설명서의 해당 항목을 따릅니다.",
        "consumer_impact": "소비자가 실제 보장범위를 실제보다 넓게 이해할 수 있습니다.",
        "insurer_advantage_vector": "보장범위 인식 확대 후 실제 지급 단계에서 제한 조건을 적용할 여지가 생길 수 있습니다.",
        "detection_note": "상품설명서 요약 문구에서 구체 조건 없이 보장 범위를 넓게 표현하는 경우입니다.",
        "severity": "medium",
        "is_active": True,
    },
    {
        "risk_type": "PRODUCT_DESCRIPTION_EXCLUSION_UNDERDISCLOSURE",
        "risk_label": "보장 제외사항 축소 설명형",
        "risk_description": "상품설명서에서 보장하지 않는 사항, 면책, 제외 사유를 작게 또는 모호하게 설명하는 유형",
        "document_scope": ["상품설명서"],
        "trigger_patterns": ["일부 항목은 보장하지 않을 수", "보장 제외", "면책", "제외될 수 있습니다", "유의하시기 바랍니다"],
        "risky_expression_templates": ["일부 항목은 보장하지 않을 수 있으니 유의하시기 바랍니다.", "보장 제외 사항이 있을 수 있습니다."],
        "safe_rewrite_guidelines": ["보장 제외 항목과 면책 사유를 구체적으로 열거한다.", "제외 사유의 적용 조건과 소비자 확인 필요 사항을 함께 제시한다."],
        "example_source_sentence": "일부 항목은 보장하지 않을 수 있습니다.",
        "example_risky_sentence": "보장 제외 사항이 있을 수 있으니 유의하시기 바랍니다.",
        "example_safe_sentence": "보장하지 않는 항목은 약관의 면책 및 보장 제외 조항에 열거된 항목으로 한정되며, 주요 제외 항목은 상품설명서의 보장 제외 항목 표를 확인해야 합니다.",
        "consumer_impact": "소비자가 보장 제외 범위를 충분히 인식하지 못할 수 있습니다.",
        "insurer_advantage_vector": "중요한 제외 조건이 사후 지급 단계에서만 부각될 여지가 생길 수 있습니다.",
        "detection_note": "상품설명서에서 제외·면책 내용을 추상적으로 줄여 설명하는 경우입니다.",
        "severity": "high",
        "is_active": True,
    },
    {
        "risk_type": "PRODUCT_DESCRIPTION_CONSUMER_COST_SOFTENING",
        "risk_label": "소비자 비용 부담 완화 설명형",
        "risk_description": "상품설명서에서 보험료, 자기부담금, 추가 부담, 갱신 시 보험료 변동 가능성을 완화해 설명하는 유형",
        "document_scope": ["상품설명서"],
        "trigger_patterns": ["부담을 줄일 수", "일부 비용만", "소정의 금액", "보험료가 변동될 수", "추가 부담"],
        "risky_expression_templates": ["부담을 줄일 수 있으며 일부 비용만 부담합니다.", "소정의 금액이 추가로 발생할 수 있습니다."],
        "safe_rewrite_guidelines": ["소비자가 부담하는 금액, 비율, 발생 조건을 구체적으로 설명한다.", "갱신형 상품은 보험료 변동 가능성과 변동 요인을 명확히 표시한다."],
        "example_source_sentence": "일부 비용만 부담하면 보장받을 수 있습니다.",
        "example_risky_sentence": "부담을 줄일 수 있으며 일부 비용만 부담합니다.",
        "example_safe_sentence": "소비자는 약관과 가입설계서에 명시된 자기부담금 비율 또는 금액을 부담하며, 갱신 시 보험료는 연령, 위험률, 손해율 등에 따라 변동될 수 있습니다.",
        "consumer_impact": "소비자가 실제 비용 부담이나 갱신 후 보험료 변동 가능성을 낮게 예상할 수 있습니다.",
        "insurer_advantage_vector": "비용 부담 조건에 대한 소비자 인식이 약한 상태에서 상품을 이해할 여지가 생길 수 있습니다.",
        "detection_note": "상품설명서에서 비용 부담을 완화된 표현으로 설명하는 경우입니다.",
        "severity": "medium",
        "is_active": True,
    },
    {
        "risk_type": "PRODUCT_DESCRIPTION_CANCELLATION_REFUND_AMBIGUITY",
        "risk_label": "해지·환급금 설명 불명확형",
        "risk_description": "상품설명서에서 해지, 환급금, 중도해지 시 손실 가능성을 불명확하게 설명하는 유형",
        "document_scope": ["상품설명서"],
        "trigger_patterns": ["환급금은 달라질 수", "해지환급금", "중도해지", "환급되지 않을 수", "손실이 발생할 수"],
        "risky_expression_templates": ["환급금은 달라질 수 있습니다.", "중도해지 시 환급금이 적을 수 있습니다."],
        "safe_rewrite_guidelines": ["해지환급금 산정 기준과 중도해지 시 손실 가능성을 구체적으로 설명한다.", "환급금 예시표 또는 확인 위치를 함께 안내한다."],
        "example_source_sentence": "중도해지 시 환급금은 달라질 수 있습니다.",
        "example_risky_sentence": "환급금은 달라질 수 있습니다.",
        "example_safe_sentence": "중도해지 시 해지환급금은 납입보험료보다 적거나 없을 수 있으며, 기간별 해지환급금 예시는 상품설명서의 해지환급금 예시표를 확인해야 합니다.",
        "consumer_impact": "소비자가 중도해지 시 손실 가능성을 충분히 이해하지 못할 수 있습니다.",
        "insurer_advantage_vector": "환급 조건에 대한 기대와 실제 환급금 간 차이가 사후 분쟁으로 이어질 수 있습니다.",
        "detection_note": "상품설명서에서 해지·환급 정보를 추상적으로 안내하는 경우입니다.",
        "severity": "high",
        "is_active": True,
    },
    {
        "risk_type": "PRODUCT_DESCRIPTION_IMPORTANT_NOTICE_WEAKENING",
        "risk_label": "중요 유의사항 약화형",
        "risk_description": "상품설명서에서 중요한 유의사항, 가입 전 확인사항, 소비자 불이익 가능성을 약하게 표현하는 유형",
        "document_scope": ["상품설명서"],
        "trigger_patterns": ["확인이 필요할 수", "유의하시기 바랍니다", "중요 사항", "가입 전 확인", "불이익이 발생할 수"],
        "risky_expression_templates": ["확인이 필요할 수 있으니 유의하시기 바랍니다.", "가입 전 일부 사항을 확인하시기 바랍니다."],
        "safe_rewrite_guidelines": ["소비자가 반드시 확인해야 하는 사항을 구체적으로 제시한다.", "미확인 시 발생 가능한 불이익을 명확히 설명한다."],
        "example_source_sentence": "가입 전 확인이 필요할 수 있습니다.",
        "example_risky_sentence": "확인이 필요할 수 있으니 유의하시기 바랍니다.",
        "example_safe_sentence": "가입 전 보장 제외 사항, 자기부담금, 보험료 변동 가능성, 해지환급금 예시를 반드시 확인해야 하며, 미확인 시 예상한 보장 또는 환급과 차이가 발생할 수 있습니다.",
        "consumer_impact": "소비자가 중요한 제한사항이나 불이익 가능성을 충분히 인식하지 못할 수 있습니다.",
        "insurer_advantage_vector": "중요 정보가 약하게 전달되어 상품 이해의 비대칭이 커질 수 있습니다.",
        "detection_note": "상품설명서의 중요 유의사항이 권고처럼 약하게 표현되는 경우입니다.",
        "severity": "medium",
        "is_active": True,
    },
    {
        "risk_type": "BUSINESS_METHOD_UNDERWRITING_DISCRETION_AMBIGUITY",
        "risk_label": "인수심사 재량 불명확형",
        "risk_description": "사업방법서에서 가입심사, 인수 제한, 조건부 인수 기준을 회사 판단에 과도하게 맡기는 유형",
        "document_scope": ["사업방법서"],
        "trigger_patterns": ["회사가 필요하다고 판단", "심사 결과에 따라", "인수 제한", "조건부 인수", "가입이 제한될 수"],
        "risky_expression_templates": ["회사가 필요하다고 판단하는 경우 가입이 제한될 수 있습니다.", "심사 결과에 따라 조건부 인수가 적용될 수 있습니다."],
        "safe_rewrite_guidelines": ["인수 제한 또는 조건부 인수의 판단 기준, 적용 사유, 고지 방식, 소비자 안내 절차를 구체화한다.", "회사 판단 표현을 사용할 경우 판단 기준과 절차를 함께 제시한다."],
        "example_source_sentence": "심사 결과에 따라 가입이 제한될 수 있습니다.",
        "example_risky_sentence": "회사가 필요하다고 판단하는 경우 가입이 제한될 수 있습니다.",
        "example_safe_sentence": "가입 제한 또는 조건부 인수는 고지사항, 병력, 직업위험 등 회사가 정한 인수심사 기준에 따라 적용하며, 적용 사유와 조건은 계약자에게 안내합니다.",
        "consumer_impact": "소비자가 가입 제한 사유와 판단 기준을 예측하기 어렵습니다.",
        "insurer_advantage_vector": "인수심사 재량이 넓게 해석될 여지가 생길 수 있습니다.",
        "detection_note": "사업방법서에서 회사 판단 또는 심사 결과 표현이 구체 기준 없이 쓰이는 경우입니다.",
        "severity": "medium",
        "is_active": True,
    },
    {
        "risk_type": "BUSINESS_METHOD_CLAIM_REVIEW_STANDARD_AMBIGUITY",
        "risk_label": "보험금 심사 기준 불명확형",
        "risk_description": "사업방법서에서 보험금 지급 심사 기준, 추가 확인, 지급 보류 기준이 불명확한 유형",
        "document_scope": ["사업방법서"],
        "trigger_patterns": ["추가 확인이 필요한 경우", "지급이 제한될 수", "지급 보류", "심사 기준", "회사가 요구하는 자료"],
        "risky_expression_templates": ["추가 확인이 필요한 경우 지급이 제한될 수 있습니다.", "심사 기준에 따라 지급을 보류할 수 있습니다."],
        "safe_rewrite_guidelines": ["추가 확인 사유, 요청 자료, 지급 보류 기준, 처리 기한을 구체적으로 명시한다.", "심사 절차와 소비자 안내 방식을 함께 설명한다."],
        "example_source_sentence": "추가 확인이 필요한 경우 지급이 제한될 수 있습니다.",
        "example_risky_sentence": "심사 기준에 따라 지급을 보류할 수 있습니다.",
        "example_safe_sentence": "추가 확인은 약관에서 정한 지급 사유 확인에 필요한 경우에 한하며, 요청 자료, 보류 사유, 예상 처리 기한을 계약자 또는 피보험자에게 안내합니다.",
        "consumer_impact": "소비자가 지급 보류나 추가 확인의 기준을 예측하기 어렵습니다.",
        "insurer_advantage_vector": "지급 심사와 보류 기간을 넓게 운영할 여지가 생길 수 있습니다.",
        "detection_note": "사업방법서에서 보험금 심사 기준이 추상적으로 표현되는 경우입니다.",
        "severity": "high",
        "is_active": True,
    },
    {
        "risk_type": "BUSINESS_METHOD_OPERATIONAL_EXCEPTION_EXPANSION",
        "risk_label": "운영상 예외 확장형",
        "risk_description": "사업방법서에서 운영상 예외, 특수 상황, 별도 기준 적용 가능성을 넓게 열어두는 유형",
        "document_scope": ["사업방법서"],
        "trigger_patterns": ["예외적으로 달리 적용", "특수한 경우", "별도 기준", "운영상 필요한 경우", "기타 사유"],
        "risky_expression_templates": ["예외적으로 달리 적용할 수 있습니다.", "운영상 필요한 경우 별도 기준을 적용할 수 있습니다."],
        "safe_rewrite_guidelines": ["예외 적용 사유와 범위를 구체적으로 제한한다.", "별도 기준 적용 시 승인 절차와 기록·고지 방식을 명확히 한다."],
        "example_source_sentence": "예외적으로 달리 적용할 수 있습니다.",
        "example_risky_sentence": "운영상 필요한 경우 별도 기준을 적용할 수 있습니다.",
        "example_safe_sentence": "예외 적용은 사업방법서에 명시된 사유에 한하며, 적용 사유와 승인 절차 및 계약자 안내 방법을 기록합니다.",
        "consumer_impact": "소비자가 업무 처리 기준이 언제 달라지는지 알기 어렵습니다.",
        "insurer_advantage_vector": "운영상 예외를 넓게 적용할 여지가 생길 수 있습니다.",
        "detection_note": "사업방법서에서 예외 적용 가능성이 포괄적으로 열려 있는 경우입니다.",
        "severity": "medium",
        "is_active": True,
    },
    {
        "risk_type": "BUSINESS_METHOD_INTERNAL_STANDARD_OPAQUENESS",
        "risk_label": "내부 기준 불투명형",
        "risk_description": "사업방법서에서 내부 기준, 별도 기준, 회사 기준을 언급하지만 구체 내용을 설명하지 않는 유형",
        "document_scope": ["사업방법서"],
        "trigger_patterns": ["내부 기준", "별도 기준", "회사 기준", "정한 기준에 따름", "세부 기준"],
        "risky_expression_templates": ["회사의 내부 기준에 따릅니다.", "별도 기준에 따라 처리할 수 있습니다."],
        "safe_rewrite_guidelines": ["내부 기준의 주요 판단 요소와 적용 절차를 문서 안에서 설명한다.", "소비자에게 영향을 주는 기준은 안내 가능 범위와 확인 절차를 제시한다."],
        "example_source_sentence": "회사의 내부 기준에 따릅니다.",
        "example_risky_sentence": "별도 기준에 따라 처리할 수 있습니다.",
        "example_safe_sentence": "업무 처리 기준은 사업방법서에 명시된 판단 요소와 절차에 따라 적용하며, 계약자에게 영향을 주는 사항은 안내 가능한 범위에서 설명합니다.",
        "consumer_impact": "소비자가 결정 기준을 알기 어려워 예측 가능성이 낮아집니다.",
        "insurer_advantage_vector": "공개되지 않은 기준에 의존해 업무 처리를 조정할 여지가 생길 수 있습니다.",
        "detection_note": "사업방법서에서 내부 기준을 언급하면서 구체 요소가 누락된 경우입니다.",
        "severity": "medium",
        "is_active": True,
    },
    {
        "risk_type": "BUSINESS_METHOD_RETROACTIVE_OR_CHANGEABLE_STANDARD",
        "risk_label": "기준 변경·사후 적용 가능성형",
        "risk_description": "사업방법서에서 기준 변경, 조정, 사후 적용 가능성을 불명확하게 열어두는 유형",
        "document_scope": ["사업방법서"],
        "trigger_patterns": ["향후 기준을 변경", "사후 적용", "변경될 수", "조정할 수", "필요 시 변경"],
        "risky_expression_templates": ["향후 기준을 변경할 수 있습니다.", "필요 시 기준을 조정하여 적용할 수 있습니다."],
        "safe_rewrite_guidelines": ["기준 변경 가능 사유, 적용 시점, 기존 계약에 대한 적용 여부, 고지 절차를 명확히 한다.", "사후 적용 여부를 제한적으로 설명한다."],
        "example_source_sentence": "향후 기준을 변경할 수 있습니다.",
        "example_risky_sentence": "필요 시 기준을 조정하여 적용할 수 있습니다.",
        "example_safe_sentence": "기준 변경은 관련 법령 또는 상품 운영 기준 변경 사유가 있는 경우에 한하며, 적용 시점과 기존 계약 적용 여부는 계약자에게 사전에 안내합니다.",
        "consumer_impact": "소비자가 계약 이후 기준 변경 영향을 예측하기 어렵습니다.",
        "insurer_advantage_vector": "기준 변경을 통해 업무 처리 결과를 사후적으로 조정할 여지가 생길 수 있습니다.",
        "detection_note": "사업방법서에서 변경 가능성을 열어두면서 적용 기준과 고지 절차가 부족한 경우입니다.",
        "severity": "high",
        "is_active": True,
    },
]


DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id SERIAL PRIMARY KEY,
    risk_type TEXT NOT NULL UNIQUE,
    risk_label TEXT NOT NULL,
    risk_description TEXT NOT NULL,
    document_scope TEXT[] DEFAULT ARRAY['약관', '상품설명서'],
    trigger_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
    risky_expression_templates JSONB NOT NULL DEFAULT '[]'::jsonb,
    safe_rewrite_guidelines JSONB NOT NULL DEFAULT '[]'::jsonb,
    example_source_sentence TEXT,
    example_risky_sentence TEXT,
    example_safe_sentence TEXT,
    consumer_impact TEXT,
    insurer_advantage_vector TEXT,
    detection_note TEXT,
    severity TEXT DEFAULT 'medium',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gray_zone_expression_type_active
ON {TABLE_NAME} (is_active);

CREATE INDEX IF NOT EXISTS idx_gray_zone_expression_type_risk_type
ON {TABLE_NAME} (risk_type);

CREATE INDEX IF NOT EXISTS idx_gray_zone_expression_type_trigger_patterns
ON {TABLE_NAME} USING GIN (trigger_patterns);
"""


UPSERT_SQL = f"""
INSERT INTO {TABLE_NAME} (
    risk_type,
    risk_label,
    risk_description,
    document_scope,
    trigger_patterns,
    risky_expression_templates,
    safe_rewrite_guidelines,
    example_source_sentence,
    example_risky_sentence,
    example_safe_sentence,
    consumer_impact,
    insurer_advantage_vector,
    detection_note,
    severity,
    is_active
) VALUES (
    %(risk_type)s,
    %(risk_label)s,
    %(risk_description)s,
    %(document_scope)s,
    %(trigger_patterns)s,
    %(risky_expression_templates)s,
    %(safe_rewrite_guidelines)s,
    %(example_source_sentence)s,
    %(example_risky_sentence)s,
    %(example_safe_sentence)s,
    %(consumer_impact)s,
    %(insurer_advantage_vector)s,
    %(detection_note)s,
    %(severity)s,
    %(is_active)s
)
ON CONFLICT (risk_type) DO UPDATE SET
    risk_label = EXCLUDED.risk_label,
    risk_description = EXCLUDED.risk_description,
    document_scope = EXCLUDED.document_scope,
    trigger_patterns = EXCLUDED.trigger_patterns,
    risky_expression_templates = EXCLUDED.risky_expression_templates,
    safe_rewrite_guidelines = EXCLUDED.safe_rewrite_guidelines,
    example_source_sentence = EXCLUDED.example_source_sentence,
    example_risky_sentence = EXCLUDED.example_risky_sentence,
    example_safe_sentence = EXCLUDED.example_safe_sentence,
    consumer_impact = EXCLUDED.consumer_impact,
    insurer_advantage_vector = EXCLUDED.insurer_advantage_vector,
    detection_note = EXCLUDED.detection_note,
    severity = EXCLUDED.severity,
    is_active = EXCLUDED.is_active,
    updated_at = CURRENT_TIMESTAMP;
"""


def _json_ready_rows() -> list[dict[str, Any]]:
    from psycopg2.extras import Json

    rows: list[dict[str, Any]] = []
    for row in SEED_ROWS:
        item = dict(row)
        item["trigger_patterns"] = Json(item["trigger_patterns"])
        item["risky_expression_templates"] = Json(item["risky_expression_templates"])
        item["safe_rewrite_guidelines"] = Json(item["safe_rewrite_guidelines"])
        rows.append(item)
    return rows


def seed() -> dict[str, Any]:
    db_url = _db_url()
    if not db_url:
        raise RuntimeError("DB connection is not configured.")

    import psycopg2
    from psycopg2.extras import execute_batch

    with psycopg2.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            execute_batch(cur, UPSERT_SQL, _json_ready_rows())
            cur.execute(
                f"""
                SELECT
                    COUNT(*)::int AS row_count,
                    COUNT(*) FILTER (WHERE is_active = TRUE)::int AS active_count,
                    ARRAY_AGG(risk_type ORDER BY risk_type) AS risk_types
                FROM {TABLE_NAME}
                WHERE risk_type = ANY(%s);
                """,
                ([row["risk_type"] for row in SEED_ROWS],),
            )
            row_count, active_count, risk_types = cur.fetchone()
        conn.commit()

    return {
        "row_count": row_count,
        "active_count": active_count,
        "risk_types": list(risk_types or []),
    }


def main() -> None:
    result = seed()
    print(f"row_count={result['row_count']}")
    print(f"active_count={result['active_count']}")
    print(f"risk_types={result['risk_types']}")


if __name__ == "__main__":
    main()
