from .llm import get_llm_by_type
from ..config.agents import AGENT_LLM_MAP


def _make(name: str):
    return get_llm_by_type(AGENT_LLM_MAP[name])


coordinator_llm = _make("coordinator")
planner_llm     = _make("planner")
supervisor_llm  = _make("supervisor")
generation_llm  = _make("generation")
compliance_llm  = _make("compliance")
edit_llm        = _make("edit")
