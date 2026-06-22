"""
Rule 2 – SUBJECTIVE 탐지기
탐지 레이어: Pattern Matching (카테고리 분류) → 객관적 기준 1차 스캔 → LLM (맥락 판단)

주관적·모호한 표현 후보를 카테고리화된 패턴으로 추출하고,
조문(제n조) 단위 문맥과 "객관적 기준 존재 여부" 힌트를 함께 LLM에 전달해
최종 위반 여부·모호성 유형·수정 방향을 판단한다.

근거: 약관규제법 제5조(약관의 작성 원칙), 보험업감독규정 보험약관 작성 원칙
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from compliance_agent.models import DetectionInput, Severity, Violation, ViolationType
from compliance_agent.providers import get_compliance_llm

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


def _spaced(text: str) -> re.Pattern:
    """공백 허용 패턴을 생성한다.
    "회사가 정하는" → r"회사가\\s*정하는" (띄어쓰기 변형을 모두 매칭)
    """
    parts = [re.escape(p) for p in text.split()]
    return re.compile(r"\s*".join(parts))


# ---------------------------------------------------------------------------
# 카테고리별 주관적·모호한 표현 패턴
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PatternSpec:
    code: str
    label: str
    regex: re.Pattern
    category: str
    base_severity: Severity
    description: str


_DISC = "insurer_discretion 표현은 회사가 자체 재량으로 판단할 수 있어"
_CATCH = "catch_all 표현은 열거되지 않은 사유까지 포괄적으로 위임할 수 있어"
_TIME = "vague_time 표현은 구체적인 기간·시점 기준이 없어"
_EVID = "vague_evidence 표현은 어떤 서류·자료가 필요한지 구체적 범위가 없어"
_SCOPE = "vague_scope 표현은 정도·범위를 가늠할 기준이 없어"
_EXC = "unclear_exception 표현은 예외 인정 기준이 구체적으로 정의되지 않아"

_SUBJECTIVE_PATTERNS: list[PatternSpec] = [
    # --- insurer_discretion: 회사/보험자의 재량 판단 표현 ---
    PatternSpec("DISC01", "회사가 필요하다고 인정", _spaced("회사가 필요하다고 인정"),
                "insurer_discretion", Severity.HIGH, _DISC),
    PatternSpec("DISC02", "회사가 정하는", _spaced("회사가 정하는"),
                "insurer_discretion", Severity.HIGH, _DISC),
    PatternSpec("DISC03", "회사의 판단에 따라", _spaced("회사의 판단에 따라"),
                "insurer_discretion", Severity.HIGH, _DISC),
    PatternSpec("DISC04", "회사가 요구하는", _spaced("회사가 요구하는"),
                "insurer_discretion", Severity.HIGH, _DISC),
    PatternSpec("DISC05", "보험자가 인정하는", _spaced("보험자가 인정하는"),
                "insurer_discretion", Severity.HIGH, _DISC),
    PatternSpec("DISC06", "객관적으로 인정되는", _spaced("객관적으로 인정되는"),
                "insurer_discretion", Severity.HIGH, _DISC),
    PatternSpec("DISC07", "필요하다고 인정되는", _spaced("필요하다고 인정되는"),
                "insurer_discretion", Severity.HIGH, _DISC),
    PatternSpec("DISC08", "인정되는/인정할 수 있는", re.compile(r"인정(?:되는|할\s*수\s*있는)"),
                "insurer_discretion", Severity.HIGH, _DISC),

    # --- catch_all: 기타·그 밖에·이에 준하는 등 포괄 열거 표현 ---
    PatternSpec("CATCH01", "기타 이에 준하는", _spaced("기타 이에 준하는"),
                "catch_all", Severity.HIGH, _CATCH),
    PatternSpec("CATCH02", "그 밖의 사유", _spaced("그 밖의 사유"),
                "catch_all", Severity.HIGH, _CATCH),
    PatternSpec("CATCH03", "그 밖의 사항", _spaced("그 밖의 사항"),
                "catch_all", Severity.HIGH, _CATCH),
    PatternSpec("CATCH04", "이에 준하는 사유", _spaced("이에 준하는 사유"),
                "catch_all", Severity.HIGH, _CATCH),
    PatternSpec("CATCH05", "이에 준하는 경우", _spaced("이에 준하는 경우"),
                "catch_all", Severity.HIGH, _CATCH),
    PatternSpec("CATCH06", "등 회사가 인정하는", _spaced("등 회사가 인정하는"),
                "catch_all", Severity.HIGH, _CATCH),

    # --- vague_time: 지체 없이·신속히·상당한 기간 등 시간 모호 표현 ---
    PatternSpec("TIME01", "지체 없이", _spaced("지체 없이"),
                "vague_time", Severity.MEDIUM, _TIME),
    PatternSpec("TIME02", "신속히", re.compile(r"신속히"),
                "vague_time", Severity.MEDIUM, _TIME),
    PatternSpec("TIME03", "즉시", re.compile(r"즉시"),
                "vague_time", Severity.MEDIUM, _TIME),
    PatternSpec("TIME04", "상당한 기간", _spaced("상당한 기간"),
                "vague_time", Severity.MEDIUM, _TIME),
    PatternSpec("TIME05", "일정한 기간", _spaced("일정한 기간"),
                "vague_time", Severity.MEDIUM, _TIME),
    PatternSpec("TIME06", "수시로", re.compile(r"수시로"),
                "vague_time", Severity.MEDIUM, _TIME),
    PatternSpec("TIME07", "필요 시", _spaced("필요 시"),
                "vague_time", Severity.MEDIUM, _TIME),
    PatternSpec("TIME08", "가능한 한 빨리", _spaced("가능한 한 빨리"),
                "vague_time", Severity.MEDIUM, _TIME),

    # --- vague_evidence: 필요한 서류·관련 서류·객관적 자료 등 증빙 모호 표현 ---
    PatternSpec("EVID01", "필요한 서류", _spaced("필요한 서류"),
                "vague_evidence", Severity.MEDIUM, _EVID),
    PatternSpec("EVID02", "관련 서류", _spaced("관련 서류"),
                "vague_evidence", Severity.MEDIUM, _EVID),
    PatternSpec("EVID03", "기타 필요한 서류", _spaced("기타 필요한 서류"),
                "vague_evidence", Severity.MEDIUM, _EVID),
    PatternSpec("EVID04", "객관적 자료", _spaced("객관적 자료"),
                "vague_evidence", Severity.MEDIUM, _EVID),
    PatternSpec("EVID05", "충분한 증빙", re.compile(r"(?<!불)충분한\s*증빙"),
                "vague_evidence", Severity.MEDIUM, _EVID),
    PatternSpec("EVID06", "회사가 요구하는 자료", _spaced("회사가 요구하는 자료"),
                "vague_evidence", Severity.MEDIUM, _EVID),

    # --- vague_scope: 상당한·합리적·적절한·과도한·중대한·현저한 등 범위 모호 표현 ---
    PatternSpec("SCOPE01", "중대한 사유", _spaced("중대한 사유"),
                "vague_scope", Severity.MEDIUM, _SCOPE),
    PatternSpec("SCOPE02", "중대한 위반", _spaced("중대한 위반"),
                "vague_scope", Severity.MEDIUM, _SCOPE),
    PatternSpec("SCOPE03", "현저한", re.compile(r"현저한"),
                "vague_scope", Severity.MEDIUM, _SCOPE),
    PatternSpec("SCOPE04", "경미한", re.compile(r"경미한"),
                "vague_scope", Severity.MEDIUM, _SCOPE),
    PatternSpec("SCOPE05", "통상적인", re.compile(r"통상적(?:인|으로)"),
                "vague_scope", Severity.MEDIUM, _SCOPE),
    PatternSpec("SCOPE06", "사회통념상", re.compile(r"사회통념(?:상|에|적)?"),
                "vague_scope", Severity.MEDIUM, _SCOPE),
    PatternSpec("SCOPE07", "합리적", re.compile(r"합리적(?:인|으로)?"),
                "vague_scope", Severity.MEDIUM, _SCOPE),
    # "부적절한"(부정형) 오탐 방지: 직전 글자가 "부"가 아닐 때만 매칭
    PatternSpec("SCOPE08", "적절한", re.compile(r"(?<!부)적절한"),
                "vague_scope", Severity.MEDIUM, _SCOPE),
    PatternSpec("SCOPE09", "상당히/상당한", re.compile(r"상당(?:히|한)"),
                "vague_scope", Severity.MEDIUM, _SCOPE),
    PatternSpec("SCOPE10", "과도한", re.compile(r"과도한"),
                "vague_scope", Severity.MEDIUM, _SCOPE),
    # "불충분한"(부정형) 오탐 방지: 직전 글자가 "불"이 아닐 때만 매칭
    PatternSpec("SCOPE11", "충분한", re.compile(r"(?<!불)충분한"),
                "vague_scope", Severity.MEDIUM, _SCOPE),

    # --- unclear_exception: 부득이한·불가피한·정당한·상당한 사유 등 예외 모호 표현 ---
    PatternSpec("EXC01", "부득이한 경우", _spaced("부득이한 경우"),
                "unclear_exception", Severity.HIGH, _EXC),
    PatternSpec("EXC02", "불가피한 사유", _spaced("불가피한 사유"),
                "unclear_exception", Severity.HIGH, _EXC),
    PatternSpec("EXC03", "특별한 사정", _spaced("특별한 사정"),
                "unclear_exception", Severity.HIGH, _EXC),
    PatternSpec("EXC04", "정당한 사유", _spaced("정당한 사유"),
                "unclear_exception", Severity.HIGH, _EXC),
    PatternSpec("EXC05", "상당한 사유", _spaced("상당한 사유"),
                "unclear_exception", Severity.HIGH, _EXC),
]

# ---------------------------------------------------------------------------
# 객관적 기준 1차 스캔 (정규식 휴리스틱 — 최종 판단은 LLM이 내림)
# ---------------------------------------------------------------------------

_OBJECTIVE_ANCHOR_PATTERNS: list[re.Pattern] = [
    re.compile(r"\d+\s*(?:일|영업일|개월|년|회|시간|분|%|퍼센트)"),
    re.compile(r"다음\s*각\s*호"),
    re.compile(r"각\s*호의\s*어느\s*하나"),
    re.compile(r"제\s*\d+\s*조"),
    re.compile(r"제\s*\d+\s*호"),
    re.compile(r"별표\s*\d+"),
    re.compile(r"예를\s*들어"),
    re.compile(r"구체적으로"),
    re.compile(r"다음과\s*같다"),
    re.compile(r"이라\s*함은"),
    re.compile(r"말한다"),
    re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]"),
    re.compile(r"(?:^|\n)\s*\d+\.\s"),
    re.compile(r"(?:^|\n)\s*[가나다라마바사아자차카타파하]\.\s"),
]


def _has_objective_standard(context: str) -> bool:
    """문맥에 수치·조문·열거 등 객관적 기준으로 볼 수 있는 단서가 있는지 1차 스캔한다.
    True여도 무조건 정상 처리하지 않으며, LLM 판단에 참고용 힌트로만 전달한다."""
    return any(p.search(context) for p in _OBJECTIVE_ANCHOR_PATTERNS)


# ---------------------------------------------------------------------------
# 조문(제n조) 단위 문맥 추출
# ---------------------------------------------------------------------------

_CONTEXT_WINDOW = 200  # 조문 마커가 없을 때의 전후 탐색 범위 (글자)
_MAX_CLAUSE_CONTEXT = 1200  # 조문 단위 문맥이 너무 길면 LLM 비용 보호를 위해 폴백
_CLAUSE_MARKER = re.compile(r"제\s*\d+\s*조")


def _extract_clause_context(content: str, match_start: int, match_end: int) -> str:
    """match가 속한 조문(제n조 ~ 다음 제n조 이전) 구간을 반환한다.
    조문 마커가 전혀 없는 문서면 빈 문자열을 반환해 호출 측이 폴백하도록 한다."""
    boundaries = [m.start() for m in _CLAUSE_MARKER.finditer(content)]
    if not boundaries:
        return ""
    clause_start = None
    for boundary in boundaries:
        if boundary <= match_start:
            clause_start = boundary
        else:
            break
    if clause_start is None:
        return ""
    clause_end = next((b for b in boundaries if b > match_end), len(content))
    return content[clause_start:clause_end]


def _build_context(content: str, match_start: int, match_end: int) -> str:
    clause = _extract_clause_context(content, match_start, match_end)
    if clause and len(clause) <= _MAX_CLAUSE_CONTEXT:
        return clause.replace("\n", " ").strip()
    ctx_start = max(0, match_start - _CONTEXT_WINDOW)
    ctx_end = min(len(content), match_end + _CONTEXT_WINDOW)
    return content[ctx_start:ctx_end].replace("\n", " ").strip()


_REGULATION_BASIS = (
    "보험업 감독업무 시행세칙 제5-17조 · "
    "약관규제법 제5조(약관의 작성 원칙) · "
    "보험업감독규정 보험약관 작성 원칙"
)

_LLM_SYSTEM_PROMPT = """\
당신은 보험 약관 법률 준수 검토 전문가입니다.
주어진 약관 문맥에서 강조된 표현이 객관적 기준 없이 모호하게 사용되었는지 판단하세요.

판단 기준:
- 구체적인 수치, 기간, 조건, 열거된 사례, 법령·별표·조문 참조가 문맥에 명시되어 있으면 명확할 가능성이 높습니다.
- 단순히 '상당한', '합리적인', '적절한', '필요한' 같은 단어가 있다는 것만으로 곧바로 위반으로 판단하지 마세요.
- 표현이 고객의 권리 제한, 보험금 지급 제한, 계약 해지, 면책, 서류 제출 의무, 보험료 변경, 회사 재량 행사와 연결되어 있으면 더 엄격하게 판단하세요.
- '기타', '그 밖의', '등'은 단순 예시 열거라면 허용될 수 있으나, 보험금 부지급 사유·계약자 의무·회사 면책·계약 해지 사유를 확장하는 방식이면 위험합니다.
- 판단이 애매하면 is_subjective=true로 보되 confidence를 0.5~0.7 사이로 두세요.

반드시 다음 JSON 스키마로만 응답하세요. 다른 텍스트를 덧붙이지 마세요.
{
  "is_subjective": true,
  "ambiguity_type": "insurer_discretion | catch_all | vague_time | vague_evidence | vague_scope | unclear_exception | none",
  "has_objective_standard": false,
  "missing_standard": "무엇이 부족한지 한 문장",
  "reason": "판단 이유 한 문장",
  "suggested_revision": "수정 방향 한 문장",
  "confidence": 0.0
}
"""

_LLM_USER_TEMPLATE = """\
약관 문맥:
\"\"\"
{context}
\"\"\"

검토 대상 표현: [{expression}]
1차 분류(참고용, 최종 판단은 본인이 하세요): {category}
문맥 내 객관적 기준 단서(숫자·기간·조문·열거 등) 발견 여부(참고용): {has_objective_anchor}

이 표현이 구체적 기준 없이 모호하게 사용되었습니까?
"""


@dataclass
class _Candidate:
    spec: PatternSpec
    match_text: str
    start: int
    end: int
    context: str
    snippet: str
    seq: int
    has_objective_anchor: bool


def _dedupe_candidates(raw: list[_Candidate]) -> list[_Candidate]:
    """겹치는 후보를 정리한다.
    1) 같은 (start, end, category, label)은 1개만 남긴다.
    2) span이 겹치면 심각도가 높은 후보를 우선하고, 같으면 더 긴 후보를 남긴다.

    더 긴 MEDIUM 패턴 때문에 그 안에 포함된 HIGH 패턴이 제거되면 실제 위험도를
    낮게 평가하게 되므로, 구체성보다 심각도를 먼저 비교한다.
    """
    seen: set[tuple[int, int, str, str]] = set()
    unique: list[_Candidate] = []
    for candidate in raw:
        key = (candidate.start, candidate.end, candidate.spec.category, candidate.spec.label)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)

    severity_rank = {
        Severity.LOW: 1,
        Severity.MEDIUM: 2,
        Severity.HIGH: 3,
    }
    kept: list[_Candidate] = []
    for candidate in sorted(
        unique,
        key=lambda c: (severity_rank[c.spec.base_severity], c.end - c.start),
        reverse=True,
    ):
        overlaps = any(
            candidate.start < k.end and candidate.end > k.start for k in kept
        )
        if overlaps:
            continue
        kept.append(candidate)

    kept.sort(key=lambda c: c.start)
    return kept


class SubjectiveDetector:
    """Rule 2: 주관적·모호한 표현 탐지 (카테고리화된 Pattern + LLM)"""

    def __init__(self, llm_factory=None) -> None:
        self._llm_factory = llm_factory
        self._llm_cache: dict[str, object] = {}

    def _get_llm(self, model_override: str | None):
        key = model_override or "__upstage_fallback__"
        if key not in self._llm_cache:
            factory = self._llm_factory or get_compliance_llm
            self._llm_cache[key] = factory(model_override)
        return self._llm_cache[key]

    def detect(self, data: DetectionInput) -> list[Violation]:
        candidates = self._extract_candidates(data.content)
        violations: list[Violation] = []
        failed: list[_Candidate] = []

        for candidate in candidates:
            result = self._judge_candidate(
                candidate, data.model_override, data.langfuse_callbacks
            )
            if result is None:
                failed.append(candidate)
            elif result["is_subjective"]:
                violations.append(self._build_violation(candidate, result))

        violations.extend(self._build_failure_violations(failed))
        return violations

    # ------------------------------------------------------------------

    def _extract_candidates(self, content: str) -> list[_Candidate]:
        raw: list[_Candidate] = []
        for spec in _SUBJECTIVE_PATTERNS:
            for seq, match in enumerate(spec.regex.finditer(content), start=1):
                start, end = match.start(), match.end()
                context = _build_context(content, start, end)

                snip_start = max(0, start - 40)
                snip_end = min(len(content), end + 40)
                snippet = content[snip_start:snip_end].replace("\n", " ").strip()

                raw.append(
                    _Candidate(
                        spec=spec,
                        match_text=match.group(),
                        start=start,
                        end=end,
                        context=context,
                        snippet=snippet,
                        seq=seq,
                        has_objective_anchor=_has_objective_standard(context),
                    )
                )
        return _dedupe_candidates(raw)

    def _judge_candidate(
        self,
        candidate: _Candidate,
        model_override: str | None,
        callbacks: list,
    ) -> dict | None:
        """LLM 판단 결과를 정규화된 dict로 반환한다. None은 호출·파싱 실패를 뜻한다."""
        try:
            prompt = _LLM_USER_TEMPLATE.format(
                context=candidate.context,
                expression=candidate.match_text,
                category=candidate.spec.category,
                has_objective_anchor="있음" if candidate.has_objective_anchor else "없음",
            )
            message = self._get_llm(model_override).invoke([
                SystemMessage(content=_LLM_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ], config={"callbacks": callbacks})
            raw = _parse_llm_json(str(message.content))
            return {
                "is_subjective": bool(raw.get("is_subjective", True)),
                "ambiguity_type": str(raw.get("ambiguity_type") or candidate.spec.category),
                "has_objective_standard": bool(raw.get("has_objective_standard", False)),
                "missing_standard": str(raw.get("missing_standard") or ""),
                "reason": str(raw.get("reason") or ""),
                "suggested_revision": str(raw.get("suggested_revision") or ""),
                "confidence": float(raw.get("confidence", 0.6)),
            }
        except Exception:
            return None

    def _build_violation(self, candidate: _Candidate, result: dict) -> Violation:
        spec = candidate.spec
        ambiguity_type = result["ambiguity_type"]
        reason = (
            f"'{candidate.match_text}' 표현은 {ambiguity_type} 유형의 모호한 표현으로, "
            f"{spec.description} 계약자가 권리·의무의 범위를 예측하기 어렵습니다."
        )
        if result["reason"]:
            reason += f" ({result['reason']})"
        if result["missing_standard"]:
            reason += f" 보완 필요 기준: {result['missing_standard']}."
        if result["suggested_revision"]:
            reason += f" 수정 방향: {result['suggested_revision']}"

        return Violation(
            violation_id=f"VIO_SUB_{spec.code}_{candidate.seq:03d}",
            type=ViolationType.SUBJECTIVE,
            severity=spec.base_severity,
            original_text=candidate.snippet,
            regulation=_REGULATION_BASIS,
            reason=reason,
            suggested_revision=result["suggested_revision"],
        )

    def _build_failure_violations(self, failed: list[_Candidate]) -> list[Violation]:
        if not failed:
            return []

        labels = ", ".join(
            f"{candidate.spec.label}({candidate.spec.category})"
            for candidate in failed[:5]
        )
        if len(failed) > 5:
            labels += f" 외 {len(failed) - 5}건"

        return [Violation(
            # 기존 소비자와 테스트가 사용하는 안정적인 오류 ID를 유지한다.
            violation_id="VIO_SUB_LLM_FAIL",
            type=ViolationType.SUBJECTIVE,
            severity=Severity.LOW,
            original_text=failed[0].snippet,
            regulation=_REGULATION_BASIS,
            reason=(
                f"주관적 표현 검사 중 LLM 판단이 {len(failed)}회 실패했습니다. "
                f"자동 판정하지 않은 후보: {labels}. 수동 검토가 필요합니다."
            ),
            manual_flag=True,
        )]
