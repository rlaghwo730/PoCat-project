from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from compliance_agent.providers.llm import GeminiComplianceLLM, get_compliance_llm


def test_gemini_api_key가_있으면_기본_compliance_model_사용():
    with patch.dict(
        "os.environ",
        {
            "GEMINI_API_KEY": "gemini-key",
            "OPENROUTER_API_KEY": "test-key",
            "UPSTAGE_API_KEY": "upstage-key",
        },
        clear=False,
    ):
        llm = get_compliance_llm("openai/gpt-oss-20b:free")

    assert isinstance(llm, GeminiComplianceLLM)
    assert llm.model == "gemini-3.5-flash"


def test_gemini_model_override는_gemini_모델명만_허용():
    with patch.dict(
        "os.environ",
        {"GEMINI_API_KEY": "gemini-key", "GEMINI_COMPLIANCE_MODEL": "gemini-3.1-flash-lite"},
        clear=False,
    ):
        llm = get_compliance_llm("gemini-3.5-flash")

    assert isinstance(llm, GeminiComplianceLLM)
    assert llm.model == "gemini-3.5-flash"


def test_gemini_adapter가_generate_content_payload를_만든다():
    llm = GeminiComplianceLLM(api_key="gemini-key", model="gemini-3.5-flash")

    payload = llm._build_payload([
        SystemMessage(content="JSON only"),
        HumanMessage(content="판단해줘"),
    ])

    assert payload["systemInstruction"]["parts"][0]["text"] == "JSON only"
    assert payload["contents"] == [{"role": "user", "parts": [{"text": "판단해줘"}]}]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_openrouter와_선택모델이_있으면_해당모델_사용():
    chat_openai = MagicMock()
    with patch.dict(
        "os.environ",
        {
            "GEMINI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "OPENROUTER_API_KEY": "test-key",
            "UPSTAGE_API_KEY": "",
        },
        clear=False,
    ), patch.dict(
        "sys.modules",
        {"langchain_openai": SimpleNamespace(ChatOpenAI=chat_openai)},
    ):
        get_compliance_llm("openai/gpt-oss-20b:free")

    assert chat_openai.call_args.kwargs["model"] == "openai/gpt-oss-20b:free"
    assert chat_openai.call_args.kwargs["base_url"] == "https://openrouter.ai/api/v1"
    chat_openai.return_value.with_retry.assert_called_once_with(stop_after_attempt=3)


def test_선택모델이_없으면_upstage_solar_pro_사용():
    chat_upstage = MagicMock()
    with patch.dict(
        "os.environ",
        {
            "GEMINI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "OPENROUTER_API_KEY": "test-key",
            "UPSTAGE_API_KEY": "upstage-key",
        },
        clear=False,
    ), patch.dict(
        "sys.modules",
        {"langchain_upstage": SimpleNamespace(ChatUpstage=chat_upstage)},
    ):
        get_compliance_llm(None)

    assert chat_upstage.call_args.kwargs["model"] == "solar-pro"
    chat_upstage.return_value.with_retry.assert_called_once_with(stop_after_attempt=3)


def test_openrouter_실패시_upstage_런타임_폴백을_등록():
    chat_openai = MagicMock()
    chat_upstage = MagicMock()
    primary_with_retry = MagicMock()
    upstage_with_retry = MagicMock()
    chat_openai.return_value.with_retry.return_value = primary_with_retry
    chat_upstage.return_value.with_retry.return_value = upstage_with_retry

    with patch.dict(
        "os.environ",
        {
            "GEMINI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "OPENROUTER_API_KEY": "test-key",
            "UPSTAGE_API_KEY": "upstage-key",
        },
        clear=False,
    ), patch.dict(
        "sys.modules",
        {
            "langchain_openai": SimpleNamespace(ChatOpenAI=chat_openai),
            "langchain_upstage": SimpleNamespace(ChatUpstage=chat_upstage),
        },
    ):
        get_compliance_llm("openai/gpt-oss-120b:free")

    primary_with_retry.with_fallbacks.assert_called_once_with([upstage_with_retry])


def test_사용가능한_키_조합이_없으면_명시적_오류():
    with patch.dict(
        "os.environ",
        {
            "GEMINI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "OPENROUTER_API_KEY": "test-key",
            "UPSTAGE_API_KEY": "",
        },
        clear=False,
    ):
        with pytest.raises(ValueError, match="Compliance LLM API 키"):
            get_compliance_llm(None)
