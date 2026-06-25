"""Final Validation Agent — 실손의료보험 최종 산출물 검증 에이전트 (독립 모듈)

약관 / 상품설명서 / 사업방법서 3종 최종본과 Compliance Agent가 보고한
위반 항목을 입력받아, 제출 가능 여부를 JSON으로 판정한다.

설계 메모:
  - LangGraph final_validation_node 에서 arun_final_validation()을 호출한다.
  - 입력(State 유사 dict) / 출력(dict) 구조는 그래프 노드와 단독 실행 양쪽에서
    재사용할 수 있도록 유지한다.
  - llm.py 의 get_llm_by_type() 스타일을 따르되, 외부 .env / API key 에
    의존하지 않도록 LLM 객체를 호출 측에서 '주입'하는 구조로 작성했다.
    (llm 인자를 주지 않으면 LLM 없이 규칙 기반 검증만 수행한다.)
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── 프롬프트 로더 ─────────────────────────────────────────────────────────────

def _prompt(name: str = "final_validation") -> str:
    """nodes.py 의 _prompt() 와 동일한 규약.

    본 모듈은 backend/src/agents/ 에 있고 프롬프트는 backend/src/prompts/ 에 있으므로
    부모(agents)의 부모(src) 아래 prompts/ 에서 로드한다.
    """
    path = Path(__file__).parent.parent / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")


# ── 상수 정의 ─────────────────────────────────────────────────────────────────

# 미완성 / 임시 문구 탐지 패턴
_INCOMPLETE_PATTERNS = [
    r"TODO", r"TBD", r"FIXME", r"XXX",
    r"\[예시\]", r"\(예시\)", r"\(임시\)", r"\[임시\]",
    r"여기에\s*작성", r"placeholder", r"_{3,}",
    r"\[수동검토필요",  # edit 단계에서 남은 수동 검토 태그
]

# 문서 키 → 한글 라벨 매핑 (출력 document 필드용)
_DOC_LABELS = {
    "draft_content": "약관",
    "final_content": "약관",
    "product_description": "상품설명서",
    "business_method": "사업방법서",
}

_VALID_ISSUE_TYPES = {"누락", "충돌", "형식오류", "규제잔존", "근거부족", "미완성문구"}
_VALID_SEVERITIES = {"high", "medium", "low"}


# ── 필드 접근 헬퍼 ────────────────────────────────────────────────────────────

def _vget(obj: Any, key: str, default: Any = None) -> Any:
    """violation 항목에서 필드를 꺼낸다 — dict / Pydantic 객체 모두 지원.

    compliance_node 는 dict 를 만들지만, ComplianceAgent.validate 가 반환하는
    원본 report.violations 는 Pydantic 객체(v.type, v.severity 등)이다.
    두 형태를 모두 받을 수 있도록 통일된 접근을 제공한다.

    추가로, Enum 처럼 .value 속성을 가진 값은 .value 를 풀어 문자열화하기 쉽게 한다.
    (예: v.type 이 ViolationType.OVERSTATEMENT 인 경우 "OVERSTATEMENT" 반환)
    """
    if obj is None:
        return default

    # dict 우선
    if isinstance(obj, dict):
        val = obj.get(key, default)
    else:
        # Pydantic / 일반 객체: 속성 접근
        val = getattr(obj, key, default)

    if val is None:
        return default

    # Enum 등 .value 보유 값은 내부 값으로 풀어준다
    if hasattr(val, "value"):
        return val.value
    return val


# ── 검증 에이전트 ─────────────────────────────────────────────────────────────

class FinalValidationAgent:
    """최종 산출물 검증 에이전트.

    Parameters
    ----------
    llm : Optional[Any]
        langchain Runnable (ainvoke 지원). None 이면 규칙 기반 검증만 수행한다.
        LangGraph 연결 시 nodes.py 에서 get_*_llm(model_override) 결과를 주입한다.
    """

    def __init__(self, llm: Optional[Any] = None):
        self.llm = llm
        try:
            self.system_prompt = _prompt("final_validation")
        except FileNotFoundError:
            logger.warning("[final_validation] 프롬프트 파일 없음 — 규칙 기반만 동작")
            self.system_prompt = ""

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def validate(self, payload: dict) -> dict:
        """동기 검증 진입점.

        Parameters
        ----------
        payload : dict
            {
              "final_content": str,        # 약관 최종본 (없으면 draft_content 사용)
              "product_description": str,  # 상품설명서
              "business_method": str,      # 사업방법서
              "violations": list,          # compliance agent 가 마지막에 보고한 위반 목록
            }

        Returns
        -------
        dict : 아래 JSON 스키마를 따르는 검증 결과
            {
              "passed": bool,
              "summary": str,
              "issues": [
                {document, issue_type, description, severity, suggestion}, ...
              ]
            }
        """
        docs = self._extract_documents(payload)
        violations = payload.get("violations", []) or []

        # 1) 규칙 기반 검증 — LLM 유무와 무관하게 항상 수행
        rule_issues = self._rule_based_checks(docs, violations)

        # 2) LLM 기반 검증 — 일관성·맥락 판단 (llm 주입 시에만)
        llm_result: Optional[dict] = None
        if self.llm is not None:
            try:
                llm_result = self._llm_check(docs, violations)
            except Exception as e:  # noqa: BLE001
                logger.error("[final_validation] LLM 검증 실패: %s", e)
                llm_result = None

        return self._merge_results(rule_issues, llm_result)

    async def avalidate(self, payload: dict) -> dict:
        """비동기 검증 진입점. nodes.py 의 async 노드에서 await 로 호출한다.

        규칙 기반 검증은 동기로 끝나므로 LLM 호출만 비동기로 처리한다.
        """
        docs = self._extract_documents(payload)
        violations = payload.get("violations", []) or []

        rule_issues = self._rule_based_checks(docs, violations)

        llm_result: Optional[dict] = None
        if self.llm is not None:
            try:
                llm_result = await self._allm_check(docs, violations)
            except Exception as e:  # noqa: BLE001
                logger.error("[final_validation] LLM 검증 실패: %s", e)
                llm_result = None

        return self._merge_results(rule_issues, llm_result)

    # ── 문서 추출 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_documents(payload: dict) -> dict:
        """payload 에서 3종 문서를 뽑아 표준 dict 로 정리."""
        terms = payload.get("final_content") or payload.get("draft_content") or ""
        return {
            "약관": (terms or "").strip(),
            "상품설명서": (payload.get("product_description") or "").strip(),
            "사업방법서": (payload.get("business_method") or "").strip(),
        }

    # ── 규칙 기반 검증 ──────────────────────────────────────────────────────────

    def _rule_based_checks(self, docs: dict, violations: list) -> list[dict]:
        issues: list[dict] = []
        issues.extend(self._check_completeness(docs))
        issues.extend(self._check_compliance_residual(docs, violations))
        issues.extend(self._check_incomplete_text(docs))
        return issues

    @staticmethod
    def _check_completeness(docs: dict) -> list[dict]:
        """3종 문서 존재 여부."""
        issues = []
        for label, content in docs.items():
            if not content:
                issues.append({
                    "document": label,
                    "issue_type": "누락",
                    "description": f"{label} 문서가 비어 있거나 생성되지 않았습니다.",
                    "severity": "high",
                    "suggestion": f"{label} 생성 단계를 재실행하여 문서를 채워주세요.",
                })
        return issues

    @staticmethod
    def _check_compliance_residual(docs: dict, violations: list) -> list[dict]:
        """compliance 가 지적한 original_text 가 약관/상품설명서/사업방법서
        3종 문서 어디에든 그대로 남아있는지 검사한다."""
        issues = []
        for v in violations:
            original = str(_vget(v, "original_text", "") or "").strip()
            if not original:
                continue
            # 너무 짧은 단편은 오탐 가능성이 커서 제외
            if len(original) < 4:
                continue
            for label, content in docs.items():
                if not content:
                    continue
                if original in content:
                    issues.append({
                        "document": label,
                        "issue_type": "규제잔존",
                        "description": (
                            f"Compliance 가 지적한 위반 표현이 {label} 최종본에 남아 있습니다: "
                            f"\"{original[:60]}\" ({_vget(v, 'type', 'UNKNOWN')})"
                        ),
                        "severity": "high",
                        "suggestion": _vget(v, "reason") or _vget(v, "regulation")
                        or "해당 표현을 약관 기준에 맞게 수정하세요.",
                    })
        return issues

    @staticmethod
    def _check_incomplete_text(docs: dict) -> list[dict]:
        """TODO / 예시 / 임시 문구 / 수동검토 태그 잔존 여부."""
        issues = []
        compiled = [re.compile(p, re.IGNORECASE) for p in _INCOMPLETE_PATTERNS]
        for label, content in docs.items():
            if not content:
                continue
            found = set()
            for pat in compiled:
                m = pat.search(content)
                if m:
                    found.add(m.group(0))
            if found:
                issues.append({
                    "document": label,
                    "issue_type": "미완성문구",
                    "description": (
                        f"{label}에 임시/미완성 문구가 남아 있습니다: "
                        f"{', '.join(sorted(found))}"
                    ),
                    "severity": "medium",
                    "suggestion": "임시 문구를 실제 내용으로 교체하거나 수동 검토를 완료하세요.",
                })
        return issues

    # ── LLM 기반 검증 ──────────────────────────────────────────────────────────

    def _build_llm_payload(self, docs: dict, violations: list) -> str:
        """LLM 입력(HumanMessage content) 문자열 구성."""
        viol_lines = []
        for v in violations:
            viol_lines.append(
                f"- type={_vget(v, 'type', '')} / "
                f"original=\"{str(_vget(v, 'original_text', '') or '')[:80]}\" / "
                f"regulation={_vget(v, 'regulation', '')} / "
                f"reason={_vget(v, 'reason', '')}"
            )
        viol_block = "\n".join(viol_lines) if viol_lines else "(보고된 위반 없음)"

        return (
            f"=== 약관 (final_content) ===\n{docs.get('약관', '')}\n\n"
            f"=== 상품설명서 (product_description) ===\n{docs.get('상품설명서', '')}\n\n"
            f"=== 사업방법서 (business_method) ===\n{docs.get('사업방법서', '')}\n\n"
            f"=== Compliance Agent가 마지막으로 보고한 위반 항목 ===\n{viol_block}"
        )

    def _llm_check(self, docs: dict, violations: list) -> Optional[dict]:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=self._build_llm_payload(docs, violations)),
        ]
        response = self.llm.invoke(messages)
        return self._parse_llm_json(getattr(response, "content", str(response)))

    async def _allm_check(self, docs: dict, violations: list) -> Optional[dict]:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=self._build_llm_payload(docs, violations)),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_llm_json(getattr(response, "content", str(response)))

    @staticmethod
    def _parse_llm_json(raw: str) -> Optional[dict]:
        """LLM 응답에서 JSON 본문만 추출/파싱. 코드펜스·머리말 방어."""
        if not raw:
            return None
        text = raw.strip()
        # ```json ... ``` 코드펜스 제거
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # 첫 { 부터 마지막 } 까지 추출
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.warning("[final_validation] LLM 응답에서 JSON 미발견")
            return None
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning("[final_validation] JSON 파싱 실패: %s", e)
            return None

    # ── 결과 병합 / 정규화 ──────────────────────────────────────────────────────

    def _merge_results(
        self, rule_issues: list[dict], llm_result: Optional[dict]
    ) -> dict:
        """규칙 기반 이슈 + LLM 이슈를 병합하고 passed 를 최종 판정."""
        issues: list[dict] = [self._normalize_issue(i) for i in rule_issues]

        llm_summary = ""
        if llm_result:
            llm_summary = str(llm_result.get("summary", "")).strip()
            for i in llm_result.get("issues", []) or []:
                issues.append(self._normalize_issue(i))

        issues = self._dedup(issues)

        # passed 판정: high 이슈가 하나라도 있으면 무조건 false
        has_high = any(i["severity"] == "high" for i in issues)
        if has_high:
            passed = False
        elif llm_result is not None and "passed" in llm_result:
            # high 가 없으면 LLM 판단을 존중 (단 issues 있으면 보수적으로 검토)
            passed = bool(llm_result["passed"]) and not issues
        else:
            passed = not issues

        summary = self._build_summary(passed, issues, llm_summary)
        return {"passed": passed, "summary": summary, "issues": issues}

    @staticmethod
    def _normalize_issue(raw: dict) -> dict:
        """필드 검증·기본값 보정으로 출력 스키마 강제."""
        issue_type = raw.get("issue_type", "")
        if issue_type not in _VALID_ISSUE_TYPES:
            issue_type = "형식오류"
        severity = str(raw.get("severity", "medium")).lower()
        if severity not in _VALID_SEVERITIES:
            severity = "medium"
        document = raw.get("document", "공통")
        if document not in {"약관", "상품설명서", "사업방법서", "공통"}:
            document = "공통"
        return {
            "document": document,
            "issue_type": issue_type,
            "description": str(raw.get("description", "")).strip(),
            "severity": severity,
            "suggestion": str(raw.get("suggestion", "")).strip(),
        }

    @staticmethod
    def _dedup(issues: list[dict]) -> list[dict]:
        """description 기준 중복 제거 (규칙·LLM 중복 탐지 대비)."""
        seen = set()
        out = []
        for i in issues:
            key = (i["document"], i["issue_type"], i["description"][:50])
            if key in seen:
                continue
            seen.add(key)
            out.append(i)
        return out

    @staticmethod
    def _build_summary(passed: bool, issues: list[dict], llm_summary: str) -> str:
        # passed=false 인 경우: 발견된 이슈를 명확히 알리는 issue 기반 summary 를 우선한다.
        # (LLM summary 가 이슈를 과소 보고해 최종 요약을 덮어쓰는 것을 방지)
        if not passed:
            high = sum(1 for i in issues if i["severity"] == "high")
            med = sum(1 for i in issues if i["severity"] == "medium")
            low = sum(1 for i in issues if i["severity"] == "low")
            return (
                f"검증 결과 총 {len(issues)}건의 이슈가 발견되었습니다 "
                f"(high {high} / medium {med} / low {low}). "
                f"high 이슈 해소 후 재검증이 필요합니다."
            )
        # passed=true 인 경우에만 LLM 의 서술형 요약을 그대로 사용한다.
        if llm_summary:
            return llm_summary
        return "3종 문서 검증을 통과했습니다. 제출 가능한 상태입니다."


# ── 함수형 진입점 (nodes.py 연결 편의용) ──────────────────────────────────────

def run_final_validation(payload: dict, llm: Optional[Any] = None) -> dict:
    """동기 헬퍼. 추후 nodes.py 에서 asyncio.to_thread 로 감싸 쓰기 좋다."""
    return FinalValidationAgent(llm=llm).validate(payload)


async def arun_final_validation(payload: dict, llm: Optional[Any] = None) -> dict:
    """비동기 헬퍼. nodes.py 의 async 노드에서 직접 await 가능.

    예시 (추후 nodes.py 연결 시):

        from ..agents.agents import get_supervisor_llm
        from ..agents.final_validation_agent import arun_final_validation

        async def final_validation_node(state, model_override=None):
            llm = get_supervisor_llm(model_override)
            result = await arun_final_validation({
                "final_content": state.get("final_content", ""),
                "product_description": state.get("product_description", ""),
                "business_method": state.get("business_method", ""),
                "violations": state.get("violations", []),
            }, llm=llm)
            return {
                "status": "PASS" if result["passed"] else "MANUAL_REVIEW",
                "messages": state["messages"] + [
                    {"role": "final_validation", "content": result["summary"]}
                ],
            }
    """
    return await FinalValidationAgent(llm=llm).avalidate(payload)


# ── 로컬 단독 실행 (스모크 테스트) ────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sample = {
        "final_content": "제1조 (목적) 본 약관은... 제2조 자기부담금 20%. TODO: 면책 조항 추가",
        "product_description": "본 상품은 자기부담금 30%를 적용합니다.",
        "business_method": "",
        "violations": [
            {
                "type": "OVERSTATEMENT",
                "original_text": "모든 질병을 100% 보장합니다",
                "regulation": "보험업법 제97조",
                "reason": "보장 범위를 약관 기준으로 한정해 기재",
            }
        ],
    }
    # llm 없이 규칙 기반만 — API key/.env 불필요
    out = run_final_validation(sample)
    print(json.dumps(out, ensure_ascii=False, indent=2))
