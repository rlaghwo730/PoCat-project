import os
import logging
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_MODEL_MAP = {
    "basic":       "openai/gpt-oss-20b:free",
    "reasoning":   "openai/gpt-oss-20b:free",
    "supervisor":  "openai/gpt-oss-20b:free",
    "generation":  "nvidia/nemotron-3-ultra-550b-a55b:free",
    "compliance":  "nousresearch/hermes-3-llama-3.1-405b:free",
}


def get_llm_by_type(llm_type: str, model_override: Optional[str] = None):
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    upstage_key = os.getenv("UPSTAGE_API_KEY")

    upstage_llm = None
    if upstage_key:
        from langchain_upstage import ChatUpstage
        upstage_llm = ChatUpstage(model="solar-pro", api_key=upstage_key)

    if openrouter_key:
        from langchain_openai import ChatOpenAI
        model = model_override or _MODEL_MAP.get(llm_type, _MODEL_MAP["basic"])
        logger.info("[LLM] OpenRouter 사용: %s", model)
        primary = (
            ChatOpenAI(
                model=model,
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1",
            )
            .with_retry(stop_after_attempt=3)
        )
        if upstage_llm:
            logger.info("[LLM] Upstage Solar 폴백 등록")
            return (
                primary
                .with_fallbacks([upstage_llm])
            )
        return primary

    if upstage_llm:
        logger.info("[LLM] Upstage Solar 사용: solar-pro")
        return upstage_llm

    raise ValueError(
        "LLM API 키가 설정되지 않았습니다.\n"
        ".env 파일에 OPENROUTER_API_KEY 또는 UPSTAGE_API_KEY를 설정해주세요."
    )
