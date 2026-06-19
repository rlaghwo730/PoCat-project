"""A2A(Agent-to-Agent) 보조 레이어 패키지.

기존 LangGraph 라우팅을 유지한 채, 노드 간 전달 내용을 표준 메시지로 기록한다.
"""
from .message_schema import A2AMessage, A2AStatus
from .utils import create_a2a_message, append_a2a_message

__all__ = [
    "A2AMessage",
    "A2AStatus",
    "create_a2a_message",
    "append_a2a_message",
]
