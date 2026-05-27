from __future__ import annotations

import logging
import os

from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler

logger = logging.getLogger(__name__)

_initialized = False


def _load_keys() -> tuple[str, str, str]:
    """st.secrets → 환경변수 순으로 Langfuse 키를 탐색한다."""
    default_host = "https://us.cloud.langfuse.com"
    try:
        import streamlit as st
        public_key = st.secrets.get("LANGFUSE_PUBLIC_KEY", os.getenv("LANGFUSE_PUBLIC_KEY", ""))
        secret_key = st.secrets.get("LANGFUSE_SECRET_KEY", os.getenv("LANGFUSE_SECRET_KEY", ""))
        host = st.secrets.get("LANGFUSE_HOST", os.getenv("LANGFUSE_HOST", default_host))
    except Exception:
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
        host = os.getenv("LANGFUSE_HOST", default_host)
    return public_key, secret_key, host


def _ensure_client() -> None:
    """Langfuse v3 전역 클라이언트를 1회 초기화한다 (키 주입)."""
    global _initialized
    if _initialized:
        return
    public_key, secret_key, host = _load_keys()
    try:
        Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    except Exception as exc:
        logger.warning("Langfuse 클라이언트 초기화 실패 — 트레이싱 비활성화: %s", exc)
    _initialized = True


def create_langfuse_handler() -> CallbackHandler:
    """매 요청마다 새로운 Langfuse CallbackHandler를 생성한다 (세션 오염 방지).

    v3에서 CallbackHandler는 무인자로 생성하며, 키는 전역 클라이언트에서 가져온다.
    """
    _ensure_client()
    return CallbackHandler()


def bind_session(session_id: str, user_id: str = "anonymous") -> None:
    """현재 활성 trace에 session_id / user_id를 연결한다 (v3).

    @observe로 감싼 컨텍스트 안에서 호출해야 하며, 그 안의 모든 LLM 호출이
    동일 세션으로 묶인다. 키가 없거나 활성 trace가 없으면 조용히 무시한다.
    """
    _ensure_client()
    try:
        get_client().update_current_trace(session_id=session_id, user_id=user_id)
    except Exception as exc:
        logger.debug("session 바인딩 생략 (활성 trace 없음 또는 비활성): %s", exc)
