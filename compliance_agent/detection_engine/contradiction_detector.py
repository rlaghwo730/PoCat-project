"""
Rule 3 – CONTRADICTION 탐지기
탐지 레이어: 구조 분석 → LLM (조항 간 충돌 판단)

조항을 분리한 뒤 보장/면책 조항 쌍을 LLM이 비교하여
동일 대상에 대해 상충하는 내용이 있는지 판단한다.
근거: 보험업 감독업무 시행세칙 제5-17조 (약관 명확성·일관성 원칙)
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

import anthropic

from compliance_agent.models import DetectionInput, Severity, Violation, ViolationType
from .subjective_detector import _parse_llm_json  # JSON 파싱 헬퍼 재사용

# 조항 구분자 – "제N조", "제N항", "①②", "가. 나.", "1.", "(1)", "[N]" 등
_SECTION_SPLITTER = re.compile(
    r"(?=제\s*\d+\s*(?:조|항)"
    r"|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]"
    r"|\n[가-하]\.\s"
    r"|\n\d+\.\s"
    r"|\n\(\d+\)\s"
    r"|\n\[\d+\]\s)"
)

# 보장·지급 키워드
_COVERAGE_KEYWORDS = re.compile(r"보장|지급|담보|지원")
# 면책·제외 키워드
_EXCLUSION_KEYWORDS = re.compile(r"면책|제외|보장\s*하지\s*않|지급\s*하지\s*않|해당\s*없")

_LLM_SYSTEM_PROMPT = """\
당신은 보험 약관 법률 준수 검토 전문가입니다.
두 약관 조항이 동일한 대상(상황, 질병, 비용 등)에 대해 서로 모순되는지 판단하세요.

판단 기준:
- 한 조항은 보장한다고 하고 다른 조항은 동일 대상을 제외한다고 명시 → 모순
- 대상이 달라 서로 독립적인 조항 → 모순 아님

반드시 JSON으로만 응답하세요:
{"is_contradiction": true, "subject": "충돌 대상 한 줄 요약", "reason": "한 문장 이유"}
또는
{"is_contradiction": false, "reason": "한 문장 이유"}
"""

_LLM_USER_TEMPLATE = """\
[조항 A]
{section_a}

[조항 B]
{section_b}

두 조항이 동일한 대상에 대해 모순됩니까?
"""

# 조항 쌍 최대 비교 수 (조합 폭발 방지)
_MAX_PAIRS = 30

# LLM 호출 실패를 나타내는 sentinel (None은 "모순 없음"과 구분)
_LLM_FAILED = object()


@dataclass
class _SectionPair:
    idx_a: int
    idx_b: int
    text_a: str
    text_b: str


class ContradictionDetector:
    """Rule 3: 조항 간 논리 충돌 탐지 (구조 분석 + LLM)"""

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
        sections = self._split_sections(data.content)
        candidate_pairs = self._filter_candidate_pairs(sections)
        violations: list[Violation] = []
        llm_failures = 0

        for pair in candidate_pairs[:_MAX_PAIRS]:
            result = self._check_contradiction_by_llm(pair)
            if result is _LLM_FAILED:
                llm_failures += 1
                continue
            if result:
                subject, reason = result
                violations.append(self._build_violation(pair, subject, reason))

        if llm_failures > 0:
            violations.append(Violation(
                violation_id="VIO_CON_LLM_FAIL",
                type=ViolationType.CONTRADICTION,
                severity=Severity.LOW,
                original_text="",
                regulation="보험업 감독업무 시행세칙 제5-17조",
                reason=(
                    f"조항 간 모순 검사 중 LLM 호출이 {llm_failures}회 실패하였습니다. "
                    "해당 조항 쌍에 대한 수동 검토가 권장됩니다."
                ),
            ))

        # coverage_context 기반 추가 모순 탐지
        ctx = data.coverage_context
        if ctx is not None:
            if ctx.exclusions:
                violations.extend(
                    self._check_exclusion_contradictions(data.content, ctx.exclusions, sections)
                )
            if ctx.mandatory_rider_yn:
                violations.extend(self._check_mandatory_rider_contradiction(data.content))

        return violations

    # ------------------------------------------------------------------

    def _split_sections(self, content: str) -> list[str]:
        parts = _SECTION_SPLITTER.split(content)
        return [p.strip() for p in parts if len(p.strip()) > 20]

    def _filter_candidate_pairs(self, sections: list[str]) -> list[_SectionPair]:
        """보장 조항 × 면책 조항 조합만 추려 LLM 호출 수를 줄인다."""
        coverage_idxs = [i for i, s in enumerate(sections) if _COVERAGE_KEYWORDS.search(s)]
        exclusion_idxs = [i for i, s in enumerate(sections) if _EXCLUSION_KEYWORDS.search(s)]

        pairs: list[_SectionPair] = []
        for i, j in itertools.product(coverage_idxs, exclusion_idxs):
            if i == j:
                continue
            pairs.append(
                _SectionPair(
                    idx_a=i,
                    idx_b=j,
                    text_a=sections[i][:500],
                    text_b=sections[j][:500],
                )
            )
        return pairs

    def _check_contradiction_by_llm(
        self, pair: _SectionPair
    ) -> tuple[str, str] | None | object:
        """모순이면 (subject, reason), 모순 없으면 None, LLM 오류면 _LLM_FAILED 반환."""
        try:
            prompt = _LLM_USER_TEMPLATE.format(
                section_a=pair.text_a,
                section_b=pair.text_b,
            )
            message = self.client.messages.create(
                model=self._model,
                max_tokens=256,
                temperature=0.1,
                system=_LLM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            result = _parse_llm_json(message.content[0].text)
            if result.get("is_contradiction"):
                return result.get("subject", "미상"), result.get("reason", "")
            return None
        except Exception:
            return _LLM_FAILED

    def _check_exclusion_contradictions(
        self, content: str, exclusions: list[str], sections: list[str]
    ) -> list[Violation]:
        """product_meta의 exclusions 항목이 보장 조항에 언급되면 모순으로 탐지."""
        coverage_sections = [s for s in sections if _COVERAGE_KEYWORDS.search(s)]
        violations: list[Violation] = []
        for idx, excl_item in enumerate(exclusions):
            for section in coverage_sections:
                if excl_item in section:
                    violations.append(Violation(
                        violation_id=f"VIO_CON_EXC_{idx:03d}",
                        type=ViolationType.CONTRADICTION,
                        severity=Severity.CRITICAL,
                        original_text=section[:100].replace("\n", " "),
                        regulation="보험업 감독업무 시행세칙 제5-17조",
                        reason=(
                            f"'{excl_item}'은 면책 항목으로 지정되었으나 "
                            "보장 조항에서 보장 대상으로 언급되고 있습니다."
                        ),
                    ))
                    break
        return violations

    def _check_mandatory_rider_contradiction(self, content: str) -> list[Violation]:
        """mandatory_rider_yn=True인데 약관에 '선택 가능' 표현이 있으면 모순."""
        optional_pattern = re.compile(r"선택\s*(?:가능|특약|사항)|선택적\s*(?:가입|담보)")
        match = optional_pattern.search(content)
        if not match:
            return []
        return [Violation(
            violation_id="VIO_CON_RIDER_001",
            type=ViolationType.CONTRADICTION,
            severity=Severity.HIGH,
            original_text=match.group(),
            regulation="보험업 감독업무 시행세칙 제5-17조",
            reason=(
                "상품 설계상 의무 가입(mandatory_rider_yn=True)이나 "
                "약관에 '선택 가능' 표현이 존재하여 모순됩니다."
            ),
        )]

    def _build_violation(
        self, pair: _SectionPair, subject: str, reason: str
    ) -> Violation:
        snippet_a = pair.text_a[:80].replace("\n", " ")
        snippet_b = pair.text_b[:80].replace("\n", " ")
        return Violation(
            violation_id=f"VIO_CON_{pair.idx_a:03d}_{pair.idx_b:03d}",
            type=ViolationType.CONTRADICTION,
            severity=Severity.CRITICAL,
            original_text=f"[조항{pair.idx_a}] {snippet_a}… ↔ [조항{pair.idx_b}] {snippet_b}…",
            regulation="보험업 감독업무 시행세칙 제5-17조",
            reason=f"'{subject}'에 대해 두 조항이 상충합니다. {reason}",
        )
