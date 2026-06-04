import os
import logging
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_MODEL_MAP = {
    "basic":      "openai/gpt-oss-120b:free",
    "reasoning":  "openai/gpt-oss-120b:free",
    "supervisor": "openai/gpt-oss-120b:free",
}


def get_llm_by_type(llm_type: str, model_override: Optional[str] = None):
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    upstage_key = os.getenv("UPSTAGE_API_KEY")

    if openrouter_key:
        from langchain_openai import ChatOpenAI
        model = model_override or _MODEL_MAP.get(llm_type, _MODEL_MAP["basic"])
        logger.info("[LLM] OpenRouter 사용: %s", model)
        return ChatOpenAI(
            model=model,
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
        )

    if upstage_key:
        from langchain_upstage import ChatUpstage
        logger.info("[LLM] Upstage Solar 사용: solar-pro")
        return ChatUpstage(model="solar-pro", api_key=upstage_key)

    raise ValueError(
        "LLM API 키가 설정되지 않았습니다.\n"
        ".env 파일에 OPENROUTER_API_KEY 또는 UPSTAGE_API_KEY를 설정해주세요."
    )
