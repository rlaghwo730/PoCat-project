"""Compliance 판정 LLM을 생성한다.

선택 규칙:
  1. GEMINI_API_KEY가 있으면 Gemini 모델
     (기본: gemini-3.5-flash, GEMINI_COMPLIANCE_MODEL로 변경 가능)
  2. OPENROUTER_API_KEY와 model_override가 모두 있으면 선택한 OpenRouter 모델
     (최대 3회 재시도, Upstage가 있으면 런타임 폴백)
  3. UPSTAGE_API_KEY가 있으면 Upstage solar-pro (최대 3회 재시도)
  4. 그 외에는 명시적 오류

모델 객체는 각 detector가 model_override별로 캐시한다.
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace
from typing import Any, Optional

from langchain_core.messages import AIMessage, SystemMessage


_DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"


class GeminiComplianceLLM:
    """Minimal LangChain-like adapter for the Gemini generateContent API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = _DEFAULT_GEMINI_MODEL,
        temperature: float = 0.1,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    def invoke(self, messages: list[Any], config: Optional[dict] = None):
        del config  # Langfuse callbacks are handled by LangChain models only.
        payload = self._build_payload(messages)
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                import requests

                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return SimpleNamespace(content=self._extract_text(response.json()))
            except Exception as exc:  # pragma: no cover - exercised through callers
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)

        raise RuntimeError(f"Gemini compliance LLM 호출 실패: {last_error}") from last_error

    def _build_payload(self, messages: list[Any]) -> dict:
        system_parts: list[str] = []
        contents: list[dict] = []

        for message in messages:
            content = str(getattr(message, "content", message))
            if isinstance(message, SystemMessage) or getattr(message, "type", "") == "system":
                system_parts.append(content)
                continue

            role = "model" if isinstance(message, AIMessage) else "user"
            contents.append({"role": role, "parts": [{"text": content}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "responseMimeType": "application/json",
            },
        }
        if system_parts:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }
        return payload

    @staticmethod
    def _extract_text(data: dict) -> str:
        parts = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        text = "".join(str(part.get("text", "")) for part in parts).strip()
        if not text:
            raise ValueError(f"Gemini 응답에서 텍스트를 찾지 못했습니다: {data}")
        return text


def get_compliance_llm(model_override: Optional[str] = None):
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    upstage_key = os.getenv("UPSTAGE_API_KEY")

    if gemini_key:
        model = (
            model_override
            if model_override and model_override.startswith("gemini-")
            else os.getenv("GEMINI_COMPLIANCE_MODEL", _DEFAULT_GEMINI_MODEL)
        )
        return GeminiComplianceLLM(api_key=gemini_key, model=model)

    upstage_llm = None
    if upstage_key:
        from langchain_upstage import ChatUpstage

        upstage_llm = ChatUpstage(
            model="solar-pro",
            api_key=upstage_key,
        ).with_retry(stop_after_attempt=3)

    if openrouter_key and model_override:
        from langchain_openai import ChatOpenAI

        primary = ChatOpenAI(
            model=model_override,
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/rlaghwo730/pocat-project",
                "X-Title": "PoCat5-Insurance-Agent",
            },
        ).with_retry(stop_after_attempt=3)
        if upstage_llm is not None:
            return primary.with_fallbacks([upstage_llm])
        return primary

    if upstage_llm is not None:
        return upstage_llm

    raise ValueError(
        "Compliance LLM API 키가 없습니다. "
        "GEMINI_API_KEY, OPENROUTER_API_KEY+model_override, "
        "또는 UPSTAGE_API_KEY가 필요합니다."
    )
