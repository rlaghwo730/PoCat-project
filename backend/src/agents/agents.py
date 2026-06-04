from typing import Optional

from .llm import get_llm_by_type
from ..config.agents import AGENT_LLM_MAP


def get_coordinator_llm(model_override: Optional[str] = None):
    return get_llm_by_type(AGENT_LLM_MAP["coordinator"], model_override)

def get_planner_llm(model_override: Optional[str] = None):
    return get_llm_by_type(AGENT_LLM_MAP["planner"], model_override)

def get_supervisor_llm(model_override: Optional[str] = None):
    return get_llm_by_type(AGENT_LLM_MAP["supervisor"], model_override)

def get_generation_llm(model_override: Optional[str] = None):
    return get_llm_by_type(AGENT_LLM_MAP["generation"], model_override)

def get_compliance_llm(model_override: Optional[str] = None):
    return get_llm_by_type(AGENT_LLM_MAP["compliance"], model_override)

def get_edit_llm(model_override: Optional[str] = None):
    return get_llm_by_type(AGENT_LLM_MAP["edit"], model_override)
