"""LangGraph StateGraph 구성

플로우:
  START → coordinator → planner → supervisor(허브)
  supervisor → generation → supervisor
  supervisor → compliance → supervisor
  supervisor → edit       → supervisor
  supervisor → END
"""
from langgraph.graph import StateGraph, END

from .types import State
from .nodes import (
    coordinator_node,
    planner_node,
    supervisor_node,
    generation_node,
    compliance_node,
    edit_node,
    route_supervisor,
)


def build_graph():
    graph = StateGraph(State)

    # 노드 등록
    graph.add_node("coordinator", coordinator_node)
    graph.add_node("planner",     planner_node)
    graph.add_node("supervisor",  supervisor_node)
    graph.add_node("generation",  generation_node)
    graph.add_node("compliance",  compliance_node)
    graph.add_node("edit",        edit_node)

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
            "end":        END,
        },
    )

    # 각 노드 완료 후 supervisor로 귀환
    graph.add_edge("generation", "supervisor")
    graph.add_edge("compliance", "supervisor")
    graph.add_edge("edit",       "supervisor")

    return graph.compile()


workflow = build_graph()
