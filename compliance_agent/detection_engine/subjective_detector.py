"""
Rule 2 – SUBJECTIVE 탐지기
탐지 레이어: Pattern Matching → LLM (맥락 판단)

주관적·모호한 표현 후보를 패턴으로 추출하고,
인근 문장에 구체적 기준이 명시되었는지를 LLM이 최종 판단한다.
근거: 보험업 감독업무 시행세칙 제5-17조 (보험약관 명확성 원칙)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import anthropic

from compliance_agent.models import DetectionInput, Severity, Violation, ViolationType

# LLM이 ```json ... ``` 으로 감싸서 응답하는 경우를 처리
_MD_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_llm_json(text: str) -> dict:
    """LLM 응답에서 JSON을 추출한다. ```json 펜스, 앞뒤 공백 등을 허용."""
    cleaned = _MD_JSON_FENCE.sub("", text).strip()
    # 만약 JSON 외 텍스트가 앞뒤에 섞여 있으면 첫 { ~ 마지막 } 만 추출
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)

# 주관적 표현 후보 패턴
_SUBJECTIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"상당한\s*사유"), "상당한 사유"),
    (re.compile(r"정당한\s*사유"), "정당한 사유"),
    (re.compile(r"합리적(?:인|으로)"), "합리적"),
    (re.compile(r"적절한"), "적절한"),
    (re.compile(r"충분한"), "충분한"),
    (re.compile(r"과도한"), "과도한"),
    (re.compile(r"상당(?:히|한)"), "상당히/상당한"),
    (re.compile(r"필요하다고\s*인정"), "필요하다고 인정"),
    (re.compile(r"인정(?:되는|할\s*수\s*있는)"), "인정되는"),
    (re.compile(r"불가피한\s*사유"), "불가피한 사유"),
    (re.compile(r"특별한\s*사정"), "특별한 사정"),
    (re.compile(r"통상적(?:인|으로)"), "통상적인"),
]

_CONTEXT_WINDOW = 200  # 전후 탐색 범위 (글자)

_LLM_SYSTEM_PROMPT = """\
당신은 보험 약관 법률 준수 검토 전문가입니다.
주어진 약관 문장에서 강조된 표현이 모호한지 판단하세요.

판단 기준:
- 구체적인 수치, 기간, 조건, 열거된 사례가 인근 문장에 명시된 경우 → 명확
- 기준 없이 추상적인 판단에 맡긴 경우 → 모호 (위반)

반드시 JSON으로만 응답하세요:
{"is_subjective": true, "reason": "한 문장 이유"}
또는
{"is_subjective": false, "reason": "한 문장 이유"}
"""

_LLM_USER_TEMPLATE = """\
약관 문맥:
\"\"\"
{context}
\"\"\"

검토 대상 표현: [{expression}]

이 표현이 구체적 기준 없이 모호하게 사용되었습니까?
"""


@dataclass
class _Candidate:
    pattern_label: str
    match_text: str
    context: str
    snippet: str
    idx: int
    seq: int


class SubjectiveDetector:
    """Rule 2: 주관적·모호한 표현 탐지 (Pattern + LLM)"""

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        # 클라이언트는 첫 호출 시점에 생성 (API 키 없는 환경에서도 인스턴스 생성 가능)
        self._client: anthropic.Anthropic | None = None
        self._model = model

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def detect(self, data: DetectionInput) -> list[Violation]:
        candidates = self._extract_candidates(data.content)
        violations: list[Violation] = []

        for candidate in candidates:
            if self._is_subjective_by_llm(candidate):
                violations.append(self._build_violation(candidate))

        return violations

    # ------------------------------------------------------------------

    def _extract_candidates(self, content: str) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for idx, (pattern, label) in enumerate(_SUBJECTIVE_PATTERNS, start=1):
            for seq, match in enumerate(pattern.finditer(content), start=1):
                ctx_start = max(0, match.start() - _CONTEXT_WINDOW)
                ctx_end = min(len(content), match.end() + _CONTEXT_WINDOW)
                context = content[ctx_start:ctx_end].replace("\n", " ").strip()

                snip_start = max(0, match.start() - 40)
                snip_end = min(len(content), match.end() + 40)
                snippet = content[snip_start:snip_end].replace("\n", " ").strip()

                candidates.append(
                    _Candidate(
                        pattern_label=label,
                        match_text=match.group(),
                        context=context,
                        snippet=snippet,
                        idx=idx,
                        seq=seq,
                    )
                )
        return candidates

    def _is_subjective_by_llm(self, candidate: _Candidate) -> bool:
        """LLM에게 모호성 여부를 판단시킨다. 오류 시 보수적으로 True 반환."""
        try:
            prompt = _LLM_USER_TEMPLATE.format(
                context=candidate.context,
                expression=candidate.pattern_label,
            )
            message = self.client.messages.create(
                model=self._model,
                max_tokens=256,
                temperature=0.1,
                system=_LLM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text
            result = _parse_llm_json(text)
            return bool(result.get("is_subjective", True))
        except Exception:
            # 불확실하면 위반으로 표기 (CLAUDE.md 원칙)
            return True

    def _build_violation(self, candidate: _Candidate) -> Violation:
        return Violation(
            violation_id=f"VIO_SUB_{candidate.idx:03d}_{candidate.seq:03d}",
            type=ViolationType.SUBJECTIVE,
            severity=Severity.MEDIUM,
            original_text=candidate.snippet,
            regulation="보험업 감독업무 시행세칙 제5-17조",
            reason=(
                f"'{candidate.pattern_label}' 표현은 구체적 판단 기준이 없는 "
                "주관적·모호한 표현으로, 계약자가 권리 범위를 예측하기 어렵습니다."
            ),
        )
