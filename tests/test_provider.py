from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.models import DraftAnswer
from app.provider import InvalidModelResponse, OpenAIProvider


async def test_openai_model_and_structured_contract(passages):
    provider = OpenAIProvider(Settings(_env_file=None, openai_api_key="test-key"))
    draft = DraftAnswer(status="insufficient_evidence", statements=[], message="Insufficient support.")
    parse = AsyncMock(return_value=SimpleNamespace(status="completed", output_parsed=draft, usage=None))
    provider.client.responses.parse = parse
    try:
        result = await provider.generate("question", passages[:1])
        assert result == draft
        kwargs = parse.call_args.kwargs
        assert kwargs["model"] == "gpt-6-luna"
        assert kwargs["text_format"] is DraftAnswer
        assert kwargs["store"] is False
        assert "tools" not in kwargs
        assert "history" not in kwargs
        assert passages[0].id in kwargs["input"]
    finally:
        await provider.close()


async def test_refusal_or_incomplete_response_is_not_an_answer():
    provider = OpenAIProvider(Settings(_env_file=None, openai_api_key="test-key"))
    provider.client.responses.parse = AsyncMock(
        return_value=SimpleNamespace(status="completed", output_parsed=None)
    )
    try:
        with pytest.raises(InvalidModelResponse):
            await provider.generate("question", [])
    finally:
        await provider.close()


async def test_embeddings_are_matched_by_input_index():
    provider = OpenAIProvider(Settings(_env_file=None, openai_api_key="test-key"))
    provider.client.embeddings.create = AsyncMock(
        return_value=SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0, 1]),
                SimpleNamespace(index=0, embedding=[1, 0]),
            ]
        )
    )
    try:
        assert await provider.embed(["first", "second"]) == [[1, 0], [0, 1]]
        assert provider.client.embeddings.create.call_args.kwargs["model"] == "text-embedding-3-small"
        with pytest.raises(InvalidModelResponse):
            await provider.embed(["first"])
    finally:
        await provider.close()
