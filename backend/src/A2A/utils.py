"""A2A 메시지 유틸 — 생성(create)과 누적(append) helper

핵심 원칙:
  - nodes.py 의 기존 노드들은 messages 를 'state["messages"] + [새 메시지]' 형태로
    전체 리스트를 통째로 반환한다(LangGraph 리듀서 없이 덮어쓰기 방식).
  - a2a_messages 도 똑같은 방식을 따른다. 그래서 append_a2a_message() 는
    '기존 리스트 + 새 메시지' 를 만들어 반환하고, 노드는 그 결과를 return dict 에 담는다.
  - 이렇게 하면 types.py 에 Annotated 리듀서를 추가할 필요가 없고,
    builder.py 의 edge 구조도 손대지 않아도 된다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .message_schema import A2AMessage


def create_a2a_message(
    sender: str,
    receiver: str,
    task: str,
    status: str,
    payload: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> A2AMessage:
    """A2A 메시지 한 건을 생성한다.

    payload/metadata 를 생략하면 빈 dict 로 채운다.
    metadata 에 timestamp 가 없으면 현재 UTC 시각(ISO8601)을 자동으로 넣어 준다.
    """
    meta = dict(metadata or {})
    meta.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

    return {
        "sender":   sender,
        "receiver": receiver,
        "task":     task,
        "status":   status,
        "payload":  dict(payload or {}),
        "metadata": meta,
    }


def append_a2a_message(state: dict, message: A2AMessage) -> list[A2AMessage]:
    """기존 a2a_messages 리스트에 새 메시지를 더한 '새 리스트'를 반환한다.

    state 를 직접 변형하지 않고 새 리스트를 만들어 반환하므로(불변성 유지),
    노드 return dict 에 그대로 담으면 LangGraph state 가 안전하게 갱신된다.

    사용 예 (nodes.py 안에서):
        msg = create_a2a_message("generation", "compliance", "약관 초안 검토 요청",
                                 A2AStatus.DRAFT_GENERATED,
                                 payload={"summary": "..."},
                                 metadata={"iteration": new_iter})
        return {
            ...기존 반환값...,
            "a2a_messages": append_a2a_message(state, msg),
        }
    """
    return state.get("a2a_messages", []) + [message]
