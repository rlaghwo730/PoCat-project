import pytest
from compliance_agent.models import DetectionInput


@pytest.fixture
def sample_input():
    return DetectionInput(
        iteration=1,
        section_type="약관",
        content="",
        product_meta={"product_name": "테스트 실손보험", "deductible": 10000},
    )


def make_input(content: str, section_type: str = "약관", iteration: int = 1) -> DetectionInput:
    return DetectionInput(
        iteration=iteration,
        section_type=section_type,
        content=content,
        product_meta={"product_name": "테스트 실손보험", "deductible": 10000},
    )
