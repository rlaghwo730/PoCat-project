"""Generation Agent와 동일한 우선순위로 Compliance 판정 LLM을 생성한다.

선택 규칙:
  1. OPENROUTER_API_KEY와 model_override가 모두 있으면 선택한 OpenRouter 모델
     (최대 3회 재시도, Upstage가 있으면 런타임 폴백)
  2. UPSTAGE_API_KEY가 있으면 Upstage solar-pro (최대 3회 재시도)
  3. 그 외에는 명시적 오류

모델 객체는 각 detector가 model_override별로 캐시한다.
"""
from __future__ import annotations

import os
from typing import Optional


def get_compliance_llm(model_override: Optional[str] = None):
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    upstage_key = os.getenv("UPSTAGE_API_KEY")

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
        "OPENROUTER_API_KEY+model_override 또는 UPSTAGE_API_KEY가 필요합니다."
    )
