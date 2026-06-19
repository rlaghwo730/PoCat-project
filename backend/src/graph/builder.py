"""LangGraph StateGraph 구성

플로우 (AI 생성 모드):
  START → coordinator → planner → supervisor(허브)
  supervisor → generation → supervisor
  supervisor → compliance → supervisor
  supervisor → edit       → supervisor
  supervisor → END

플로우 (사용자 작성 약관 검증·수정 모드):
  START → coordinator → planner → supervisor(허브)
  supervisor → compliance → supervisor   (generation 건너뜀)
  supervisor → revise     → supervisor   (위반 수정 반복)
  supervisor → END                       (약관만 출력)
"""
from typing import Optional

from langgraph.graph import StateGraph, END

from .types import State
from .nodes import (
    coordinator_node,
    planner_node,
    supervisor_node,
    generation_node,
    compliance_node,
    edit_node,
    revise_node,
    route_supervisor,
)


def build_graph(model_override: Optional[str] = None):
    graph = StateGraph(State)

    # 노드 등록
    async def _coordinator(s): return await coordinator_node(s, model_override)
    async def _planner(s):     return await planner_node(s, model_override)
    async def _supervisor(s):  return await supervisor_node(s, model_override)
    async def _generation(s):  return await generation_node(s, model_override)
    async def _compliance(s):  return await compliance_node(s, model_override)
    async def _edit(s):        return await edit_node(s, model_override)
    async def _revise(s):      return await revise_node(s, model_override)

    graph.add_node("coordinator", _coordinator)
    graph.add_node("planner",     _planner)
    graph.add_node("supervisor",  _supervisor)
    graph.add_node("generation",  _generation)
    graph.add_node("compliance",  _compliance)
    graph.add_node("edit",        _edit)
    graph.add_node("revise",      _revise)

    # 진입점 → coordinator → planner → supervisor(허브)
    graph.set_entry_point("coordinator")
    graph.add_edge("coordinator", "planner")
    graph.add_edge("planner",     "supervisor")

    # supervisor 조건부 분기
    graph.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "generation": "generation",
            "compliance": "compliance",
            "edit":       "edit",
            "revise":     "revise",
            "end":        END,
        },
    )

    # 각 노드 완료 후 supervisor로 귀환
    graph.add_edge("generation", "supervisor")
    graph.add_edge("compliance", "supervisor")
    graph.add_edge("edit",       "supervisor")
    graph.add_edge("revise",     "supervisor")

    return graph.compile()


workflow = build_graph()
