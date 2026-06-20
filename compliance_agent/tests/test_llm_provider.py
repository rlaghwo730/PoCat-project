from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from compliance_agent.providers.llm import get_compliance_llm


def test_openrouter와_선택모델이_있으면_해당모델_사용():
    chat_openai = MagicMock()
    with patch.dict(
        "os.environ",
        {"OPENROUTER_API_KEY": "test-key", "UPSTAGE_API_KEY": ""},
        clear=False,
    ), patch.dict(
        "sys.modules",
        {"langchain_openai": SimpleNamespace(ChatOpenAI=chat_openai)},
    ):
        get_compliance_llm("openai/gpt-oss-20b:free")

    assert chat_openai.call_args.kwargs["model"] == "openai/gpt-oss-20b:free"
    assert chat_openai.call_args.kwargs["base_url"] == "https://openrouter.ai/api/v1"


def test_선택모델이_없으면_upstage_solar_pro_사용():
    chat_upstage = MagicMock()
    with patch.dict(
        "os.environ",
        {"OPENROUTER_API_KEY": "test-key", "UPSTAGE_API_KEY": "upstage-key"},
        clear=False,
    ), patch.dict(
        "sys.modules",
        {"langchain_upstage": SimpleNamespace(ChatUpstage=chat_upstage)},
    ):
        get_compliance_llm(None)

    assert chat_upstage.call_args.kwargs["model"] == "solar-pro"


def test_사용가능한_키_조합이_없으면_명시적_오류():
    with patch.dict(
        "os.environ",
        {"OPENROUTER_API_KEY": "test-key", "UPSTAGE_API_KEY": ""},
        clear=False,
    ):
        with pytest.raises(ValueError, match="Compliance LLM API 키"):
            get_compliance_llm(None)
