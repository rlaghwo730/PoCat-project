from __future__ import annotations
import re
from compliance_agent.models import DetectionInput, Severity, Violation, ViolationType

LEGAL_REVIEW_PROMPT = """당신은 보험 규제 전문가입니다.
주어진 보험약관 조항이 보험업법, 시행령, 금감원 감독규정을 위반하는지 검토합니다.

=== 검토 기준 ===

1. CONTRADICTION (법령 위반)
   - 약관 조항이 명시적으로 법령과 충돌하는가?

2. OVERSTATEMENT (과도한 면책)
   - 법령이 허용하는 범위를 벗어나 과도하게 면책하는가?

=== 약관 조항 ===
{clause_text}

조항 정보:
- 보험회사: {company}
- 조항번호: {article}
- 제목: {title}
- 구간: {section}

=== 출력 형식 (JSON) ===

위반 없음:
{{ "violations_found": false, "reason": "..." }}

위반 있음:
{{ "violations_found": true, "violation_type": "CONTRADICTION" | "OVERSTATEMENT", "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW", "problematic_text": "...", "regulation": "...", "reason": "..." }}

JSON만 출력하세요.
"""

MEDICAL_LOSS_SPECIFIC_PROMPT = """추가 검토 기준 (실손의료보험 전용):

1. 본인부담금: 80% 보상이 표준
2. 갱신/변경: 보험사가 일방적 거절 불가
3. 면책 기간: 자살 면책기간 2년이 표준
4. 청구/지급: 거절 사유가 명확해야 함
"""

class LegalReviewDetector:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.use_mock = llm_client is None

    def detect(self, data: DetectionInput) -> list[Violation]:
        violations = []
        if self.use_mock:
            violations.extend(self._detect_mock(data))
        else:
            violations.extend(self._detect_with_llm(data))
        return violations

    def _detect_with_llm(self, data: DetectionInput) -> list[Violation]:
        prompt = LEGAL_REVIEW_PROMPT.format(
            clause_text=data.content,
            company=data.product_meta.get("company", "unknown"),
            article=data.product_meta.get("article", "unknown"),
            title=data.product_meta.get("title", "unknown"),
            section=data.product_meta.get("section", "unknown"),
        )

        if data.product_meta.get("policy_type") == "medical_loss":
            prompt += "\n" + MEDICAL_LOSS_SPECIFIC_PROMPT

        try:
            response = self.llm_client.messages.create(
                model="claude-opus-4-20250805",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )

            import json
            result = json.loads(response.content[0].text)
            if result.get("violations_found"):
                return [self._build_violation_from_llm(result, data)]
            return []
        except Exception as e:
            print(f"LLM 호출 실패: {e}. Mock 모드로 전환")
            return self._detect_mock(data)

    def _build_violation_from_llm(self, llm_result: dict, data: DetectionInput) -> Violation:
        # violation_id에 iteration을 넣지 않는다 — 동일 위반이 재생성된 약관에서도
        # 같은 ID를 가져야 IterationTracker의 FAIL_LOOP 판정이 작동한다.
        return Violation(
            violation_id=f"VIO_LR_LLM_{llm_result['violation_type']}",
            type=ViolationType[llm_result["violation_type"]],
            severity=Severity[llm_result.get("severity", "HIGH")],
            original_text=llm_result.get("problematic_text", ""),
            regulation=llm_result.get("regulation", "보험업법/감독규정"),
            reason=llm_result.get("reason", ""),
        )

    def _detect_mock(self, data: DetectionInput) -> list[Violation]:
        violations = []

        if self._has_excessive_suicide_exclusion(data.content):
            violations.append(Violation(
                violation_id="VIO_LR_SUICIDE",
                type=ViolationType.OVERSTATEMENT,
                severity=Severity.HIGH,
                original_text=self._extract_suicide_clause(data.content),
                regulation="보험업 감독업무 시행세칙",
                reason="자살 면책기간이 2년을 초과합니다.",
            ))

        if self._has_mental_illness_exclusion(data.content):
            violations.append(Violation(
                violation_id="VIO_LR_MENTAL",
                type=ViolationType.OVERSTATEMENT,
                severity=Severity.MEDIUM,
                original_text=self._extract_mental_illness_clause(data.content),
                regulation="보험업 감독업무 시행세칙",
                reason="심리질환에 대한 과도한 면책.",
            ))

        return violations

    @staticmethod
    def _has_excessive_suicide_exclusion(content: str) -> bool:
        """자살 면책기간이 표준(2년)을 초과하는 경우 탐지.

        표준: 자살 면책기간 2년(=24개월).
        위반: 3년 이상 또는 25개월 이상.
        """
        if "자살" not in content:
            return False
        for m in re.finditer(r"자살", content):
            window = content[m.start():m.start() + 100]
            # 3년 이상 (단, 두 자리 이상 숫자가 앞에 붙은 경우 제외)
            if re.search(r"(?<!\d)([3-9]|[1-9][0-9]+)\s*년", window):
                return True
            # 25개월 이상 (2년=24개월 초과)
            for month_m in re.finditer(r"(?<!\d)(\d+)\s*개월", window):
                try:
                    if int(month_m.group(1)) >= 25:
                        return True
                except ValueError:
                    continue
        return False

    @staticmethod
    def _extract_suicide_clause(content: str) -> str:
        """자살 + 면책기간 수치를 포함한 구간 추출."""
        match = re.search(r"자살[^.。\n]*?\d+\s*(?:년|개월)[^.。\n]*", content)
        return match.group(0).strip() if match else ""

    @staticmethod
    def _has_mental_illness_exclusion(content: str) -> bool:
        mental_keywords = ["심리질환", "정신질환", "신경증", "우울증"]
        exclusion_keywords = ["면책", "보장하지 않", "제외"]
        has_mental = any(kw in content for kw in mental_keywords)
        has_exclusion = any(kw in content for kw in exclusion_keywords)
        return has_mental and has_exclusion

    @staticmethod
    def _extract_mental_illness_clause(content: str) -> str:
        match = re.search(r"심리질환[^。]*?(?:면책|제외)[^。]*", content)
        return match.group(0) if match else ""
