from typing import TypedDict


class State(TypedDict):
    messages: list
    request: dict
    draft_content: str
    violations: list
    iteration: int
    final_content: str
    product_description: str
    business_method: str
    status: str
    next_step: str
    dictionary_findings: list
    semantic_findings: list
    risk_dictionary_summary: dict
