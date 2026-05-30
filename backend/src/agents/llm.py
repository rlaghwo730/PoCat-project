import os
import logging

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_MODEL_MAP = {
    "basic":      "meta-llama/llama-3.1-8b-instruct:free",
    "reasoning":  "anthropic/claude-3.5-sonnet",
    "supervisor": "openai/gpt-4o",
}


def get_llm_by_type(llm_type: str):
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    upstage_key = os.getenv("UPSTAGE_API_KEY")

    if openrouter_key:
        from langchain_openai import ChatOpenAI
        model = _MODEL_MAP.get(llm_type, _MODEL_MAP["basic"])
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

    from langchain_ollama import ChatOllama
    logger.info("[LLM] Ollama 로컬 사용: qwen2.5:14b")
    return ChatOllama(model="qwen2.5:14b")
