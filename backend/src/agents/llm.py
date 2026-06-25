import os
import logging
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_MODEL_MAP = {
    "generation":  "qwen/qwen3-235b-a22b:free",
    "compliance":  "meta-llama/llama-3.3-70b-instruct:free",
    "edit":        "qwen/qwen-2.5-72b-instruct:free",
}

_UPSTAGE_TYPES = {"basic", "reasoning", "supervisor"}


def get_llm_by_type(llm_type: str, model_override: Optional[str] = None):
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    upstage_key = os.getenv("UPSTAGE_API_KEY")

    # basic / reasoning / supervisor → Upstage Solar-Pro 직접 사용
    if llm_type in _UPSTAGE_TYPES:
        if not upstage_key:
            raise ValueError(
                f"llm_type='{llm_type}'은 Upstage Solar-Pro가 필요합니다.\n"
                ".env 파일에 UPSTAGE_API_KEY를 설정해주세요."
            )
        from langchain_upstage import ChatUpstage
        logger.info("[LLM] Upstage Solar-Pro 사용 (type=%s)", llm_type)
        return ChatUpstage(model="solar-pro", api_key=upstage_key)

    # generation / edit / compliance → OpenRouter (폴백: Upstage)
    upstage_llm = None
    if upstage_key:
        from langchain_upstage import ChatUpstage
        upstage_llm = ChatUpstage(model="solar-pro", api_key=upstage_key)

    if openrouter_key:
        from langchain_openai import ChatOpenAI
        model = model_override or _MODEL_MAP.get(llm_type, _MODEL_MAP["generation"])
        logger.info("[LLM] OpenRouter 사용: %s", model)
        temperature_map = {
            "generation": 0.3,
            "compliance": 0.1,
        }
        temperature = temperature_map.get(llm_type, 0.5)
        primary = ChatOpenAI(
            model=model,
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=temperature,
        ).with_retry(stop_after_attempt=3)
        if upstage_llm:
            logger.info("[LLM] Upstage Solar 폴백 등록")
            return primary.with_fallbacks([upstage_llm])
        return primary

    if upstage_llm:
        logger.info("[LLM] Upstage Solar 사용: solar-pro")
        return upstage_llm

    raise ValueError(
        "LLM API 키가 설정되지 않았습니다.\n"
        ".env 파일에 OPENROUTER_API_KEY 또는 UPSTAGE_API_KEY를 설정해주세요."
    )
