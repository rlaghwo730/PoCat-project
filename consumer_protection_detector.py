from __future__ import annotations
import re
from compliance_agent.models import DetectionInput, Severity, Violation, ViolationType

CONSUMER_PROTECTION_PROMPT = """당신은 금융감독원(금감원) 소비자보호 심사위원입니다.
보험약관이 「약관의 규제에 관한 법률」 제6조(불공정한 약관)를 위반하는지 검토합니다.

=== 불공정 약관의 유형 ===

1. SUBJECTIVE (모호한 표현)
   - 예: "합당한 범위", "필요하다고 인정", "통상적인 수준"

2. CONTRADICTION (소비자에게 불리한 모순)
   - 약관 여러 조항이 모순되어 소비자가 피해를 봄

3. OVERSTATEMENT (과도한 면책)
   - 보험사가 상식을 벗어날 정도로 많은 경우를 면책

=== 약관 조항 ===
{clause_text}

조항 정보:
- 보험회사: {company}
- 조항번호: {article}
- 제목: {title}

=== 출력 형식 (JSON) ===

위반 없음:
{{ "violations_found": false, "reason": "..." }}

위반 있음:
{{ "violations_found": true, "violation_type": "SUBJECTIVE" | "OVERSTATEMENT" | "CONTRADICTION" | "FORBIDDEN_WORD", "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW", "problematic_text": "...", "reason": "..." }}

JSON만 출력하세요.
"""

class ConsumerProtectionDetector:
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
        prompt = CONSUMER_PROTECTION_PROMPT.format(
            clause_text=data.content,
            company=data.product_meta.get("company", "unknown"),
            article=data.product_meta.get("article", "unknown"),
            title=data.product_meta.get("title", "unknown"),
        )

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
            violation_id=f"VIO_CP_LLM_{llm_result['violation_type']}",
            type=ViolationType[llm_result["violation_type"]],
            severity=Severity[llm_result.get("severity", "HIGH")],
            original_text=llm_result.get("problematic_text", ""),
            regulation="약관의 규제에 관한 법률 제6조",
            reason=llm_result.get("reason", ""),
        )

    def _detect_mock(self, data: DetectionInput) -> list[Violation]:
        violations = []

        # 모호 표현 패턴. "기타"는 "기타 사항", "기타 비용" 같은 정상 사용도 매칭하므로
        # catch-all 트리거(인정/판단/유사한/준하는/정하는)와 결합된 형태만 모호로 본다.
        subjective_words = [
            r"합당한\s*범위",
            r"필요하다고\s*인정",
            r"통상적인\s*수준",
            r"기타[^.。\n]{0,30}(?:인정|판단|유사한|비슷한|준하는|정하는)",
        ]

        for pattern in subjective_words:
            if re.search(pattern, data.content):
                violations.append(Violation(
                    violation_id="VIO_CP_SUBJECTIVE",
                    type=ViolationType.SUBJECTIVE,
                    severity=Severity.MEDIUM,
                    original_text=re.search(pattern, data.content).group(0),
                    regulation="약관의 규제에 관한 법률 제6조",
                    reason="소비자가 명확하게 이해하기 어려운 모호한 표현입니다.",
                ))
                break

        if self._has_excessive_exclusion(data.content):
            violations.append(Violation(
                violation_id="VIO_CP_OVERSTATEMENT",
                type=ViolationType.OVERSTATEMENT,
                severity=Severity.HIGH,
                original_text=self._extract_exclusion(data.content),
                regulation="약관의 규제에 관한 법률 제6조",
                reason="보험사의 면책 범위가 소비자가 합리적으로 예상할 수 있는 수준을 넘습니다.",
            ))

        return violations

    @staticmethod
    def _has_excessive_exclusion(content: str) -> bool:
        exclusion_patterns = [
            r"모든\s*(?:암|질병|심리질환).*?면책",
            r"(?:암|질병|심리질환).*?전액\s*미보상",
            r"정신질환.*?보장\s*불가",
        ]
        return any(re.search(p, content) for p in exclusion_patterns)

    @staticmethod
    def _extract_exclusion(content: str) -> str:
        patterns = [r"모든\s*(?:암|질병|심리질환).*?면책", r"(?:암|질병|심리질환).*?전액\s*미보상"]
        for p in patterns:
            match = re.search(p, content)
            if match:
                return match.group(0)
        return ""
