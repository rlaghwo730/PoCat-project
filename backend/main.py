"""PoCat 백엔드 서버 진입점"""
import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv

# 프로젝트 루트(PoCat-project/)를 sys.path에 등록 — 기존 에이전트 패키지 임포트용
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

load_dotenv(os.path.join(_ROOT, ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _print_startup_info() -> None:
    """사용 중인 LLM 공급자와 DB 연결 여부를 출력"""
    if os.getenv("OPENROUTER_API_KEY"):
        llm_info = "OpenRouter (basic=Llama-3.1-8B / supervisor=GPT-4o)"
    elif os.getenv("UPSTAGE_API_KEY"):
        llm_info = "Upstage Solar Pro"
    else:
        llm_info = "Ollama 로컬 (qwen2.5:14b)"

    db_info = "Neon PostgreSQL 연결됨" if os.getenv("DB_API_URL") else "DB 미연결 (MOCK 모드)"

    logger.info("=" * 60)
    logger.info("PoCat API v2.0  [LangManus 아키텍처]")
    logger.info("LLM  : %s", llm_info)
    logger.info("DB   : %s", db_info)
    logger.info("=" * 60)


if __name__ == "__main__":
    _print_startup_info()

    port   = int(os.getenv("PORT", 8000))
    reload = os.getenv("ENV", "development") != "production"

    uvicorn.run(
        "src.api.app:app",
        host="0.0.0.0",
        port=port,
        reload=reload,
        log_level="info",
    )
