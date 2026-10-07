import pytest

from sample_a2a_agents.llm import get_llm


def test_model_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL_NAME", raising=False)
    with pytest.raises(ValueError, match="OPENAI_MODEL_NAME"):
        get_llm()


def test_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL_NAME", "example-model")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        get_llm()


@pytest.mark.parametrize("variable", ["OPENAI_BASE_URL", "OPENAI_ENDPOINT"])
def test_openai_compatible_endpoint(monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_ENDPOINT", raising=False)
    monkeypatch.setenv(variable, "https://llm.example.test/v1")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "example-model")
    monkeypatch.setenv("OPENAI_API_KEY", "example-key")
    model = get_llm()
    assert model.model_name == "example-model"
    assert model.openai_api_base == "https://llm.example.test/v1"
