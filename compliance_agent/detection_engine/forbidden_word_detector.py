"""
Rule 4 – FORBIDDEN_WORD 탐지기
탐지 레이어: 사전 매칭 (Regex, LLM 불필요)

금융감독원 및 감독업무 시행세칙 기준 금지어 사전과 대조한다.
근거: 보험업 감독업무 시행세칙 제5-18조, 금융감독원 보험약관 심사기준
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from compliance_agent.models import DetectionInput, Severity, Violation, ViolationType


@dataclass
class _ForbiddenEntry:
    word: str
    pattern: re.Pattern
    severity: Severity
    regulation: str
    reason: str


def _build_pattern(word: str) -> re.Pattern:
    """단어 사이 공백을 \\s* 로 치환해 띄어쓰기 변형까지 매칭하도록 한다.
    예: "원금 보장" → r"원금\\s*보장"  (원금보장 / 원금 보장 / 원금  보장 모두 매칭)
    """
    parts = [re.escape(p) for p in word.split()]
    return re.compile(r"\s*".join(parts))


def _entry(
    word: str,
    severity: Severity,
    regulation: str,
    reason: str,
) -> _ForbiddenEntry:
    return _ForbiddenEntry(
        word=word,
        pattern=_build_pattern(word),
        severity=severity,
        regulation=regulation,
        reason=reason,
    )


# 금지어 사전 – 현직자 검토 후 보완 필요 (CLAUDE.md 비고 참조)
FORBIDDEN_WORD_DICT: list[_ForbiddenEntry] = [
    # ── 절대적·확정적 표현 ──────────────────────────────────────────────
    _entry("반드시 보장", Severity.HIGH,
           "보험업 감독업무 시행세칙 제5-18조",
           "확정적 보장을 약속하는 표현으로 오인을 유발합니다."),
    _entry("절대 보장", Severity.HIGH,
           "보험업 감독업무 시행세칙 제5-18조",
           "절대적 표현은 예외 상황을 배제하는 것으로 오인될 수 있습니다."),
    _entry("무조건 지급", Severity.HIGH,
           "보험업 감독업무 시행세칙 제5-18조",
           "조건 없는 지급을 암시하여 소비자 오해를 유발합니다."),
    _entry("손해 없음", Severity.MEDIUM,
           "보험업 감독업무 시행세칙 제5-18조",
           "손해 발생 가능성을 부정하는 오해의 소지가 있습니다."),

    # ── 비교 우위·최상급 표현 ────────────────────────────────────────────
    _entry("최고의 보장", Severity.MEDIUM,
           "금융감독원 보험약관 심사기준 3조",
           "타 상품 대비 우위를 비교하는 표현은 사용 불가합니다."),
    _entry("업계 최초", Severity.MEDIUM,
           "금융감독원 보험약관 심사기준 3조",
           "객관적 근거 없는 최초·최고 표현은 금지됩니다."),
    _entry("가장 저렴", Severity.MEDIUM,
           "금융감독원 보험약관 심사기준 3조",
           "가격 비교 우위 표현은 근거 없이 사용 불가합니다."),
    _entry("타사 대비 유리", Severity.MEDIUM,
           "금융감독원 보험약관 심사기준 3조",
           "타사 비교 표현은 공정성 검증 없이 사용 불가합니다."),

    # ── 소비자 오인 유발 표현 ────────────────────────────────────────────
    _entry("원금 보장", Severity.CRITICAL,
           "보험업법 제95조의3",
           "실손보험은 원금 개념이 없어 소비자 오인을 유발합니다."),
    _entry("예금자보호", Severity.CRITICAL,
           "보험업법 제175조",
           "보험상품은 예금자보호법 적용 대상이 아닙니다."),
    _entry("원리금 보장", Severity.CRITICAL,
           "보험업법 제95조의3",
           "보험상품에 원리금 보장 표현은 사용 불가합니다."),

    # ── 특정 의료기관·브랜드 지정 ─────────────────────────────────────────
    _entry("지정병원에서만", Severity.HIGH,
           "보험업 감독업무 시행세칙 제5-19조",
           "특정 의료기관으로의 제한은 별도 심사 기준을 충족해야 합니다."),

    # ── 세제 혜택 단정 표현 ──────────────────────────────────────────────
    _entry("세금 면제", Severity.HIGH,
           "금융감독원 보험약관 심사기준 5조",
           "세제 혜택은 세법에 따라 달라지므로 단정 표현은 금지됩니다."),
    _entry("비과세 확정", Severity.HIGH,
           "금융감독원 보험약관 심사기준 5조",
           "비과세 여부는 세법 개정에 따라 변동 가능하므로 단정 표현은 금지됩니다."),
]


class ForbiddenWordDetector:
    """Rule 4: 금지어 사전 매칭"""

    def detect(self, data: DetectionInput) -> list[Violation]:
        violations: list[Violation] = []
        content = data.content

        for idx, entry in enumerate(FORBIDDEN_WORD_DICT, start=1):
            for seq, match in enumerate(entry.pattern.finditer(content), start=1):
                snip_start = max(0, match.start() - 40)
                snip_end = min(len(content), match.end() + 40)
                snippet = content[snip_start:snip_end].replace("\n", " ").strip()

                violations.append(
                    Violation(
                        violation_id=f"VIO_FBD_{idx:03d}_{seq:03d}",
                        type=ViolationType.FORBIDDEN_WORD,
                        severity=entry.severity,
                        original_text=snippet,
                        regulation=entry.regulation,
                        reason=f"금지어 '{entry.word}': {entry.reason}",
                    )
                )

        return violations
