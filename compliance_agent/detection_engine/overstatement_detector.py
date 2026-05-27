"""
Rule 1 – OVERSTATEMENT 탐지기
탐지 레이어: Regex (LLM 불필요)

과장 표현이 있으나 자기부담금/제한사항이 동일·인접 문장에 명시되지 않은 경우 위반으로 판정.
근거: 보험업 감독업무 시행세칙 제5-18조 (보험안내자료 기재사항)
"""
from __future__ import annotations

import json
import re

import anthropic

from compliance_agent.models import DetectionInput, Severity, Violation, ViolationType
from .subjective_detector import _parse_llm_json


def _spaced(text: str) -> re.Pattern:
    """공백 허용 패턴을 생성한다.
    "전액 보장" → r"전액\\s*보장"  (전액보장 / 전액  보장 모두 매칭)
    """
    parts = [re.escape(p) for p in text.split()]
    return re.compile(r"\s*".join(parts))


# 과장 표현 패턴 – 전액·완전·무조건 계열
_OVERSTATEMENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (_spaced("전액 보장"), "전액보장"),
    (re.compile(r"100\s*%\s*보장"), "100% 보장"),
    (_spaced("완전 보장"), "완전보장"),
    (_spaced("무조건 보장"), "무조건 보장"),
    (_spaced("전부 보장"), "전부 보장"),
    (_spaced("모든 비용 보장"), "모든 비용 보장"),
    (re.compile(r"제한\s*없이\s*보장"), "제한 없이 보장"),
    (_spaced("무한 보장"), "무한 보장"),
    (_spaced("무한 지급"), "무한 지급"),
    (_spaced("전액 지급"), "전액 지급"),
    (_spaced("전부 지급"), "전부 지급"),
    # 신규 추가 패턴 (실무에서 자주 지적되는 과장 표현)
    (_spaced("끝까지 보장"), "끝까지 보장"),
    (_spaced("끝까지 책임"), "끝까지 책임"),
    (re.compile(r"예외\s*없이\s*(?:보장|지급)"), "예외 없이 보장/지급"),
    (re.compile(r"100\s*%\s*환급"), "100% 환급"),
    (re.compile(r"100\s*%\s*지급"), "100% 지급"),
    (re.compile(r"빠짐\s*없이\s*(?:보장|지급)"), "빠짐없이 보장/지급"),
]

# 자기부담금·한도 명시 표현 – 동일/인접 문장에 있으면 위반 아님
_CAVEAT_PATTERNS: list[re.Pattern] = [
    re.compile(r"자기부담금"),
    re.compile(r"공제금액"),
    re.compile(r"본인부담"),
    re.compile(r"보장\s*한도"),
    re.compile(r"한도\s*내"),
    re.compile(r"한도액"),
    re.compile(r"제외\s*(?:합니다|됩니다|됨|한다|되며|하며|하는\s*경우|되는\s*경우)"),
    re.compile(r"단,\s*"),
    re.compile(r"다만,\s*"),
    re.compile(r"면책"),
]

# 문장 종결 문자 (한국어 약관)
_SENTENCE_TERMINATORS = ".。!?\n"

# caveat 탐색 시 포함할 인접 문장 수 (현재 문장 기준 앞뒤 N개)
_NEIGHBOR_SENTENCES = 1

# 2단계 caveat 검증: LLM 프롬프트
_CAVEAT_LLM_SYSTEM = """\
당신은 보험 약관 법률 준수 검토 전문가입니다.
주어진 약관 문맥에서 과장 표현에 대한 제한 조건(caveat)이 실질적으로 명시되어 있는지 판단하세요.

판단 기준:
- 자기부담금 금액, 보장 한도, 면책 조건이 구체적으로 기재 → 실제 caveat (TRUE)
- 단순 면책 조항 나열이나 과장 표현과 무관한 제한 → 실제 caveat 아님 (FALSE)

반드시 JSON으로만 응답하세요:
{"is_real_caveat": true, "reason": "한 문장 이유"}
또는
{"is_real_caveat": false, "reason": "한 문장 이유"}
"""

_CAVEAT_LLM_USER = """\
약관 문맥:
\"\"\"
{window}
\"\"\"

과장 표현 [{label}] 에 대해 보장 범위를 실질적으로 제한하는 caveat이 위 문맥에 명시되어 있습니까?
"""


def _find_sentence_bounds(content: str, pos: int) -> tuple[int, int]:
    """pos를 포함하는 문장의 (start, end_exclusive)을 반환한다."""
    start = pos
    while start > 0 and content[start - 1] not in _SENTENCE_TERMINATORS:
        start -= 1
    end = pos
    while end < len(content) and content[end] not in _SENTENCE_TERMINATORS:
        end += 1
    return start, end


def _expand_sentences(content: str, start: int, end: int, n_neighbors: int) -> tuple[int, int]:
    """현재 문장 범위를 앞뒤 n_neighbors개 문장만큼 확장한다."""
    # 앞쪽 확장
    cur_start = start
    for _ in range(n_neighbors):
        if cur_start <= 0:
            break
        # 직전 terminator 건너뛰기
        cur_start -= 1
        while cur_start > 0 and content[cur_start - 1] not in _SENTENCE_TERMINATORS:
            cur_start -= 1
    # 뒤쪽 확장
    cur_end = end
    for _ in range(n_neighbors):
        if cur_end >= len(content):
            break
        cur_end += 1  # terminator 건너뛰기
        while cur_end < len(content) and content[cur_end] not in _SENTENCE_TERMINATORS:
            cur_end += 1
    return cur_start, cur_end


def _get_caveat_window(content: str, match_start: int, match_end: int) -> str:
    s_start, s_end = _find_sentence_bounds(content, match_start)
    w_start, w_end = _expand_sentences(content, s_start, s_end, _NEIGHBOR_SENTENCES)
    return content[w_start:w_end]


def _has_caveat(content: str, match_start: int, match_end: int) -> bool:
    """매칭된 표현의 문장 + 앞뒤 1개 문장 범위에서 caveat 패턴 1차 탐색."""
    window = _get_caveat_window(content, match_start, match_end)
    return any(p.search(window) for p in _CAVEAT_PATTERNS)


class OverstatementDetector:
    """Rule 1: 과장·절대적 보장 표현 탐지 (Regex + 2단계 LLM caveat 검증)"""

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self._client: anthropic.Anthropic | None = None
        self._model = model

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def detect(self, data: DetectionInput) -> list[Violation]:
        violations: list[Violation] = []
        content = data.content

        for idx, (pattern, label) in enumerate(_OVERSTATEMENT_PATTERNS, start=1):
            for seq, match in enumerate(pattern.finditer(content), start=1):
                if _has_caveat(content, match.start(), match.end()):
                    # 2단계: LLM으로 caveat 실효성 검증 (false positive 방지)
                    window = _get_caveat_window(content, match.start(), match.end())
                    if self._is_real_caveat_by_llm(window, label):
                        continue  # LLM이 진짜 caveat 확인 → 통과

                # 원문 스니펫: 매칭 전후 40자
                snip_start = max(0, match.start() - 40)
                snip_end = min(len(content), match.end() + 40)
                snippet = content[snip_start:snip_end].replace("\n", " ").strip()

                violations.append(
                    Violation(
                        violation_id=f"VIO_OVR_{idx:03d}_{seq:03d}",
                        type=ViolationType.OVERSTATEMENT,
                        severity=Severity.HIGH,
                        original_text=snippet,
                        regulation="보험업 감독업무 시행세칙 제5-18조",
                        reason=(
                            f"'{label}' 표현은 절대적 보장을 암시하나 "
                            "동일·인접 문장에 자기부담금 또는 보장 한도가 명시되지 않았습니다."
                        ),
                    )
                )

        return violations

    def _is_real_caveat_by_llm(self, window: str, label: str) -> bool:
        """LLM에게 caveat이 실제로 보장 범위를 제한하는지 판단시킨다.
        오류 시 False 반환 → 위반으로 처리 (CLAUDE.md: 불확실하면 위반)."""
        try:
            prompt = _CAVEAT_LLM_USER.format(window=window, label=label)
            message = self.client.messages.create(
                model=self._model,
                max_tokens=128,
                temperature=0.1,
                system=_CAVEAT_LLM_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            result = _parse_llm_json(message.content[0].text)
            return bool(result.get("is_real_caveat", False))
        except Exception:
            return False  # 불확실하면 위반으로 처리
